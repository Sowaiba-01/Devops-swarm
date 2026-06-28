"""
LangGraph agent node functions.

Each node implements a ReAct loop using Groq + Llama 3.3 70B.
Thoughts and tool calls are broadcast to WebSocket clients in real time
and persisted to the database via AgentLog records.

Node functions are async and follow the LangGraph contract:
  async def node(state: SwarmState) -> dict   # returns partial state update

ROUTING NOTE: Only supervisor_node sets the 'phase' field.
Agent nodes (architect, coder, reviewer, pr) only update their own fields.
"""

import asyncio
import datetime
import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_groq import ChatGroq

from app.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import AgentLog, Run
from app.tools.e2b_tools import close_sandbox, make_e2b_tools
from app.tools.github_tools import make_github_tools
from app.ws_manager import manager

from .prompts import (
    ARCHITECT_PROMPT,
    CODER_PROMPT,
    PR_DESCRIPTION_TEMPLATE,
    REVIEWER_PROMPT,
)
from .state import SwarmState

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 20  # safety cap per agent invocation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm(tools: list) -> Any:
    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        temperature=0,
        api_key=settings.GROQ_API_KEY,
    )
    return llm.bind_tools(tools)


async def _emit(run_id: str, agent: str, log_type: str, content: str, extra: dict | None = None) -> None:
    """Broadcast a log event via WebSocket and persist to DB."""
    msg = {
        "type": log_type,
        "agent": agent,
        "content": content,
        "run_id": run_id,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    if extra:
        msg.update(extra)

    await manager.broadcast(run_id, msg)

    async with AsyncSessionLocal() as session:
        log = AgentLog(
            id=str(uuid.uuid4()),
            run_id=run_id,
            agent=agent,
            log_type=log_type,
            content=content[:4000],
            extra=json.dumps(extra) if extra else None,
        )
        session.add(log)
        await session.commit()


async def _react_loop(
    run_id: str,
    agent_name: str,
    system_prompt: str,
    user_message: str,
    tools: list,
) -> str:
    """
    Run a ReAct (Reason + Act) loop until the LLM stops calling tools.
    Streams each thought and tool result to WebSocket.
    Returns the final text response from the LLM.
    """
    llm = _make_llm(tools)
    tool_map = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    final_response = ""

    for step in range(MAX_REACT_ITERATIONS):
        try:
            response: AIMessage = await llm.ainvoke(messages)
        except Exception as llm_err:
            # Groq raises BadRequestError when the model generates a malformed
            # tool call (e.g. <function=foo{...}> instead of JSON).
            # Fix: trim the last message and re-prompt more strictly.
            err_str = str(llm_err)
            if "tool_use_failed" in err_str or "failed_generation" in err_str:
                await _emit(run_id, agent_name, "status",
                            "LLM generated malformed tool call — retrying with strict prompt...")
                # Add a corrective user message and retry
                messages.append(HumanMessage(
                    content="Your previous response had a malformed tool call. "
                            "You MUST call tools using the proper JSON function-call format only. "
                            "Do NOT write any prose before calling a tool. Call a tool now."
                ))
                continue
            raise
        messages.append(response)

        # Emit the LLM reasoning text (may be empty if it only called tools)
        if response.content:
            await _emit(run_id, agent_name, "thought", str(response.content))
            final_response = str(response.content)

        if not response.tool_calls:
            break  # No more tool calls - done

        # Execute each requested tool call
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            call_id = tc["id"]

            await _emit(
                run_id,
                agent_name,
                "tool_call",
                f"Calling `{tool_name}`",
                extra={"tool": tool_name, "args": tool_args},
            )

            try:
                fn = tool_map.get(tool_name)
                if fn is None:
                    result_str = f"ERROR: Unknown tool '{tool_name}'"
                else:
                    # Run sync tools in a thread pool to avoid blocking the event loop
                    result = await asyncio.to_thread(fn.invoke, tool_args)
                    result_str = str(result)
            except Exception as exc:
                result_str = f"ERROR executing {tool_name}: {exc}"
                logger.exception("Tool execution error: %s", tool_name)

            await _emit(
                run_id,
                agent_name,
                "tool_result",
                result_str[:1000],  # truncate for broadcast
                extra={"tool": tool_name},
            )

            messages.append(
                ToolMessage(content=result_str, tool_call_id=call_id)
            )

    return final_response


# ---------------------------------------------------------------------------
# Supervisor (pure routing - no LLM call)
# ---------------------------------------------------------------------------

async def supervisor_node(state: SwarmState) -> dict:
    """
    Sole authority for setting 'phase'.
    Derives next phase purely from logical state fields.
    """
    run_id = state["run_id"]

    # Hard stop if run is already marked failed
    if state.get("status") == "failed":
        await _emit(run_id, "supervisor", "status", "Run marked failed, stopping.")
        return {"phase": "done"}

    # PR already created -> done
    if state.get("pr_url"):
        return {"phase": "done"}

    # No plan yet -> architect
    if not state.get("plan"):
        await _emit(run_id, "supervisor", "status", "Routing to Architect...")
        return {"phase": "architect"}

    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.MAX_CORRECTION_ITERATIONS)

    # Coder hasn't run yet OR tests failed and we still have retries left
    if state.get("test_passed") is None or (
        state.get("test_passed") is False and iteration < max_iter
    ):
        await _emit(
            run_id,
            "supervisor",
            "status",
            f"Routing to Coder (iteration {iteration + 1}/{max_iter})...",
        )
        return {"phase": "coder"}

    # Tests passed (or exhausted retries) and no review yet -> reviewer
    if not state.get("review_notes"):
        await _emit(run_id, "supervisor", "status", "Routing to Reviewer...")
        return {"phase": "reviewer"}

    # Review done, no PR yet -> create PR
    await _emit(run_id, "supervisor", "status", "Routing to PR Creator...")
    return {"phase": "pr"}


# ---------------------------------------------------------------------------
# Architect
# ---------------------------------------------------------------------------

async def architect_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    await _emit(run_id, "architect", "status", "Analyzing issue and planning implementation...")

    gh_tools = make_github_tools(
        token=state["github_token"],
        owner=state["repo_owner"],
        repo=state["repo_name"],
    )

    # Architect only needs read-only GitHub tools
    read_tools = [t for t in gh_tools if t.name in (
        "get_file_contents", "list_directory", "search_code", "get_repo_structure"
    )]

    user_msg = (
        f"Repository: {state['repo_owner']}/{state['repo_name']}\n\n"
        f"GitHub Issue #{state['issue_number']}: {state['issue_title']}\n\n"
        f"{state['issue_body']}\n\n"
        "Please explore the repository structure, understand the codebase, "
        "and produce a detailed implementation plan."
    )

    plan = await _react_loop(
        run_id=run_id,
        agent_name="architect",
        system_prompt=ARCHITECT_PROMPT,
        user_message=user_msg,
        tools=read_tools,
    )

    await _emit(run_id, "architect", "status", "Planning complete.")
    return {"plan": plan}


# ---------------------------------------------------------------------------
# Coder
# ---------------------------------------------------------------------------

async def coder_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    iteration = state.get("iteration", 0)
    token = state["github_token"]
    owner = state["repo_owner"]
    repo = state["repo_name"]

    await _emit(
        run_id,
        "coder",
        "status",
        f"Coding (iteration {iteration + 1}/{state.get('max_iterations', 3)})...",
    )

    # Generate a branch name on first iteration
    branch_name = state.get("branch_name")
    if not branch_name:
        safe_title = re.sub(r"[^a-zA-Z0-9-]", "-", state["issue_title"])[:40].lower().rstrip("-")
        branch_name = f"swarm/issue-{state['issue_number']}-{safe_title}"

    # Create branch on GitHub (idempotent if already exists)
    gh_tools = make_github_tools(token=token, owner=owner, repo=repo)
    branch_tool = next(t for t in gh_tools if t.name == "create_branch")
    try:
        await asyncio.to_thread(branch_tool.invoke, {"branch_name": branch_name})
    except Exception as e:
        await _emit(run_id, "coder", "status", f"Branch creation note: {e} (may already exist, continuing)")

    # E2B tools bound to this run's sandbox
    e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)

    prior_failure = ""
    if state.get("test_output") and state.get("test_passed") is False:
        prior_failure = f"\n\nPREVIOUS TEST FAILURE (you MUST fix this):\n{state['test_output']}"

    user_msg = (
        f"Repository: {owner}/{repo}\n"
        f"Branch to work on: {branch_name}\n"
        f"Issue #{state['issue_number']}: {state['issue_title']}\n\n"
        f"=== ARCHITECT'S PLAN ===\n{state['plan']}\n=== END PLAN ==={prior_failure}\n\n"
        "Steps:\n"
        "1. Call setup_workspace() FIRST (clones the repo if not already done).\n"
        "2. Implement all changes described in the plan.\n"
        "3. Call git_commit_all() with a descriptive commit message.\n"
        "4. Call run_tests() and report the exact output.\n"
        "5. End your response with TESTS_PASSED or TESTS_FAILED: <one-line reason>."
    )

    result = await _react_loop(
        run_id=run_id,
        agent_name="coder",
        system_prompt=CODER_PROMPT,
        user_message=user_msg,
        tools=e2b_tools,
    )

    tests_passed = "TESTS_PASSED" in result.upper()
    test_summary = (
        result.split("TESTS_FAILED:")[-1].strip()
        if not tests_passed
        else "All tests passed."
    )

    await _emit(
        run_id,
        "coder",
        "status",
        "Tests passed." if tests_passed else f"Tests failed: {test_summary}",
    )

    # Push immediately while sandbox is still alive.
    # We do this here rather than in pr_node to avoid sandbox timeout issues.
    await _emit(run_id, "coder", "status", f"Pushing branch {branch_name} to GitHub...")
    push_tool = next(t for t in e2b_tools if t.name == "git_push")
    try:
        push_result = await asyncio.to_thread(push_tool.invoke, {"branch": branch_name})
        await _emit(run_id, "coder", "status", f"Push: {push_result}")
    except Exception as push_err:
        await _emit(run_id, "coder", "status", f"Push warning: {push_err} (will retry in PR step)")

    return {
        "branch_name": branch_name,
        "test_output": result,
        "test_passed": tests_passed,
        "iteration": iteration + 1,
    }


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------

async def reviewer_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    await _emit(run_id, "reviewer", "status", "Reviewing code and running security scan...")

    e2b_tools = make_e2b_tools(
        run_id=run_id,
        token=state["github_token"],
        owner=state["repo_owner"],
        repo=state["repo_name"],
    )
    review_tools = [t for t in e2b_tools if t.name in (
        "read_file", "list_files", "get_git_diff", "run_security_scan"
    )]

    tests_status = (
        "PASSED"
        if state.get("test_passed")
        else f"FAILED\n{state.get('test_output', '')}"
    )

    user_msg = (
        f"Plan:\n{state['plan']}\n\n"
        f"Test Result: {tests_status}\n"
        f"Iterations used: {state.get('iteration', 0)} / {state.get('max_iterations', 3)}\n\n"
        "Please:\n"
        "1. Get the git diff with get_git_diff().\n"
        "2. Run run_security_scan().\n"
        "3. Read any files you need for a thorough review.\n"
        "4. Produce your structured review."
    )

    review_notes = await _react_loop(
        run_id=run_id,
        agent_name="reviewer",
        system_prompt=REVIEWER_PROMPT,
        user_message=user_msg,
        tools=review_tools,
    )

    await _emit(run_id, "reviewer", "status", "Review complete.")
    return {"review_notes": review_notes}


# ---------------------------------------------------------------------------
# PR Creator
# ---------------------------------------------------------------------------

async def pr_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    await _emit(run_id, "system", "status", "Pushing changes and opening pull request...")

    token = state["github_token"]
    owner = state["repo_owner"]
    repo = state["repo_name"]
    branch_name = state["branch_name"]

    # Push was already done in coder_node while the sandbox was warm.
    # Attempt a re-push here as a safety net in case coder's push failed.
    try:
        e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)
        push_tool = next(t for t in e2b_tools if t.name == "git_push")
        push_result = await asyncio.to_thread(push_tool.invoke, {"branch": branch_name})
        await _emit(run_id, "system", "status", f"Push result: {push_result}")
    except Exception as push_err:
        await _emit(run_id, "system", "status", f"Push skipped (already pushed): {push_err}")

    # Build PR description
    pr_body = PR_DESCRIPTION_TEMPLATE.format(
        summary=state.get("plan", "")[:500],
        changes=f"See diff on branch `{branch_name}`",
        test_output=(state.get("test_output") or "N/A")[:1000],
        review_notes=state.get("review_notes") or "N/A",
        issue_number=state["issue_number"],
    )

    pr_title = f"fix: {state['issue_title']} (closes #{state['issue_number']})"

    gh_tools = make_github_tools(token=token, owner=owner, repo=repo)
    pr_tool = next(t for t in gh_tools if t.name == "create_pull_request")

    pr_result: str = await asyncio.to_thread(
        pr_tool.invoke,
        {
            "title": pr_title,
            "body": pr_body,
            "head_branch": branch_name,
            "base_branch": "main",   # create_pull_request auto-detects the real default branch
            "draft": True,
        },
    )

    # Extract URL from "PR #5 created: https://..."
    pr_url = ""
    if "https://" in pr_result:
        pr_url = "https://" + pr_result.split("https://")[-1].strip()

    await _emit(run_id, "system", "status", pr_result)

    # Update Run record
    from sqlalchemy import update as sql_update

    async with AsyncSessionLocal() as session:
        await session.execute(
            sql_update(Run)
            .where(Run.id == run_id)
            .values(
                status="success",
                pr_url=pr_url,
                branch_name=branch_name,
                iteration_count=state.get("iteration", 0),
                completed_at=datetime.datetime.utcnow(),
            )
        )
        await session.commit()

    # Clean up E2B sandbox
    close_sandbox(run_id)

    return {"pr_url": pr_url, "status": "success"}


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

async def handle_error(run_id: str, error: Exception) -> None:
    """Called when an unhandled exception escapes a node."""
    msg = f"Swarm error: {type(error).__name__}: {error}"
    logger.exception(msg)
    await _emit(run_id, "system", "error", msg)

    from sqlalchemy import update as sql_update

    async with AsyncSessionLocal() as session:
        await session.execute(
            sql_update(Run)
            .where(Run.id == run_id)
            .values(
                status="failed",
                error_message=str(error)[:1000],
                completed_at=datetime.datetime.utcnow(),
            )
        )
        await session.commit()

    close_sandbox(run_id)
