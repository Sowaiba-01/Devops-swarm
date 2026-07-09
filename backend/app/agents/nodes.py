"""
LangGraph agent node functions.

Each node implements a ReAct loop using Groq + Llama 3.3 70B.
Thoughts and tool calls are broadcast to WebSocket clients in real time
and persisted to the database via AgentLog records.

Node functions are async and follow the LangGraph contract:
  async def node(state: SwarmState) -> dict   # returns partial state update

ROUTING NOTE: Only supervisor_node sets the 'phase' field.
Agent nodes (architect, coder, reviewer, pr) only update their own fields.

POWER-UPS in this version:
- Architect automatically pre-fetches full repo context before ReAct loop.
- Architect posts implementation plan as GitHub issue comment.
- Coder has web search, URL fetch, find_in_files, linter, auto-install tools.
- Coder auto-detects ModuleNotFoundError and installs missing packages.
- PR node posts a success comment on the original issue with the PR link.
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

MAX_REACT_ITERATIONS = 25  # raised from 20 — web search adds extra steps


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
    malformed_retries = 0
    MAX_MALFORMED_RETRIES = 3

    for step in range(MAX_REACT_ITERATIONS):
        try:
            response: AIMessage = await llm.ainvoke(messages)
        except Exception as llm_err:
            err_str = str(llm_err)
            if "tool_use_failed" in err_str or "failed_generation" in err_str:
                malformed_retries += 1
                if malformed_retries > MAX_MALFORMED_RETRIES:
                    await _emit(run_id, agent_name, "status",
                                f"Too many malformed tool calls ({malformed_retries}). Stopping.")
                    break
                # Pick the first available tool name to give the model a concrete target
                first_tool = tools[0].name if tools else "a tool"
                await _emit(run_id, agent_name, "status",
                            f"LLM generated malformed tool call — retrying ({malformed_retries}/{MAX_MALFORMED_RETRIES})...")
                messages.append(HumanMessage(
                    content=f"Your previous response had a malformed tool call. "
                            f"You MUST use proper JSON function-call format. "
                            f"Do NOT write any prose. "
                            f"Call `{first_tool}` right now with the correct arguments."
                ))
                continue
            raise
        messages.append(response)

        if response.content:
            await _emit(run_id, agent_name, "thought", str(response.content))
            final_response = str(response.content)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            call_id = tc["id"]

            await _emit(
                run_id, agent_name, "tool_call",
                f"Calling `{tool_name}`",
                extra={"tool": tool_name, "args": tool_args},
            )

            try:
                fn = tool_map.get(tool_name)
                if fn is None:
                    result_str = f"ERROR: Unknown tool '{tool_name}'"
                else:
                    result = await asyncio.to_thread(fn.invoke, tool_args)
                    result_str = str(result)
            except Exception as exc:
                result_str = f"ERROR executing {tool_name}: {exc}"
                logger.exception("Tool execution error: %s", tool_name)

            await _emit(
                run_id, agent_name, "tool_result",
                result_str[:1500],
                extra={"tool": tool_name},
            )

            messages.append(
                ToolMessage(content=result_str, tool_call_id=call_id)
            )

    return final_response


# ---------------------------------------------------------------------------
# Supervisor (pure routing — no LLM call)
# ---------------------------------------------------------------------------

async def supervisor_node(state: SwarmState) -> dict:
    """Sole authority for setting 'phase'. Pure logic — no LLM."""
    run_id = state["run_id"]

    if state.get("status") == "failed":
        await _emit(run_id, "supervisor", "status", "Run marked failed — stopping.")
        return {"phase": "done"}

    if state.get("pr_url"):
        return {"phase": "done"}

    if not state.get("plan"):
        await _emit(run_id, "supervisor", "status", "Routing to Architect...")
        return {"phase": "architect"}

    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.MAX_CORRECTION_ITERATIONS)

    if state.get("test_passed") is None or (
        state.get("test_passed") is False and iteration < max_iter
    ):
        await _emit(
            run_id, "supervisor", "status",
            f"Routing to Coder (iteration {iteration + 1}/{max_iter})...",
        )
        return {"phase": "coder"}

    if not state.get("review_notes"):
        await _emit(run_id, "supervisor", "status", "Routing to Reviewer...")
        return {"phase": "reviewer"}

    await _emit(run_id, "supervisor", "status", "Routing to PR Creator...")
    return {"phase": "pr"}


# ---------------------------------------------------------------------------
# Architect
# ---------------------------------------------------------------------------

async def architect_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    owner  = state["repo_owner"]
    repo   = state["repo_name"]
    token  = state["github_token"]

    await _emit(run_id, "architect", "status",
                "Fetching full repository context...")

    gh_tools = make_github_tools(token=token, owner=owner, repo=repo)

    # ── Step 1: Pre-fetch full repo context automatically ──────────────
    # This gives the architect the complete file tree + key files BEFORE
    # it starts reasoning — so it doesn't waste ReAct steps on blind exploration.
    context_tool = next(t for t in gh_tools if t.name == "get_full_repo_context")
    try:
        repo_context = await asyncio.to_thread(context_tool.invoke, {})
        await _emit(run_id, "architect", "status",
                    f"Repo context loaded ({len(repo_context)} chars).")
    except Exception as ctx_err:
        repo_context = f"Unable to fetch repo context: {ctx_err}"
        await _emit(run_id, "architect", "status", f"Context fetch warning: {ctx_err}")

    # ── Step 2: Check issue comments for extra requirements ────────────
    comments_tool = next(t for t in gh_tools if t.name == "get_issue_comments")
    try:
        issue_comments = await asyncio.to_thread(
            comments_tool.invoke, {"issue_number": state["issue_number"]}
        )
    except Exception:
        issue_comments = "(Could not fetch comments)"

    # Architect gets read-only tools + context already injected
    read_tools = [t for t in gh_tools if t.name in (
        "get_file_contents", "list_directory", "search_code",
        "get_repo_structure", "get_issue_comments",
    )]

    user_msg = (
        f"Repository: {owner}/{repo}\n\n"
        f"GitHub Issue #{state['issue_number']}: {state['issue_title']}\n\n"
        f"Issue Description:\n{state['issue_body']}\n\n"
        f"Issue Comments:\n{issue_comments}\n\n"
        f"=== REPOSITORY CONTEXT (pre-fetched) ===\n{repo_context}\n"
        f"=== END CONTEXT ===\n\n"
        "The repository context above has already been fetched. "
        "Now read the specific files most relevant to this issue, "
        "then produce a detailed implementation plan."
    )

    await _emit(run_id, "architect", "status", "Planning implementation...")

    plan = await _react_loop(
        run_id=run_id,
        agent_name="architect",
        system_prompt=ARCHITECT_PROMPT,
        user_message=user_msg,
        tools=read_tools,
    )

    # ── Step 3: Post the plan as a GitHub issue comment ────────────────
    # This makes the swarm transparent — repo owner sees the plan before code is written.
    comment_tool = next(t for t in gh_tools if t.name == "add_issue_comment")
    plan_comment = (
        "## 🤖 DevOps Swarm — Implementation Plan\n\n"
        f"{plan[:3500]}\n\n"
        "---\n"
        "*The swarm is now coding this. A draft PR will be opened when complete.*\n"
        "*Built by Sowaiba Arshad — DevOps Swarm AI*"
    )
    try:
        await asyncio.to_thread(
            comment_tool.invoke,
            {"issue_number": state["issue_number"], "body": plan_comment},
        )
        await _emit(run_id, "architect", "status",
                    "Implementation plan posted as GitHub comment.")
    except Exception as comment_err:
        await _emit(run_id, "architect", "status",
                    f"Could not post plan comment: {comment_err}")

    await _emit(run_id, "architect", "status", "Planning complete.")
    return {"plan": plan, "repo_context": repo_context}


# ---------------------------------------------------------------------------
# Coder
# ---------------------------------------------------------------------------

async def coder_node(state: SwarmState) -> dict:
    run_id    = state["run_id"]
    iteration = state.get("iteration", 0)
    token     = state["github_token"]
    owner     = state["repo_owner"]
    repo      = state["repo_name"]

    await _emit(
        run_id, "coder", "status",
        f"Coding iteration {iteration + 1}/{state.get('max_iterations', 3)}...",
    )

    # Generate branch name on first iteration
    branch_name = state.get("branch_name")
    if not branch_name:
        safe_title = re.sub(r"[^a-zA-Z0-9-]", "-", state["issue_title"])[:40].lower().rstrip("-")
        branch_name = f"swarm/issue-{state['issue_number']}-{safe_title}"

    # Create branch on GitHub (idempotent)
    gh_tools = make_github_tools(token=token, owner=owner, repo=repo)
    branch_tool = next(t for t in gh_tools if t.name == "create_branch")
    try:
        await asyncio.to_thread(branch_tool.invoke, {"branch_name": branch_name})
    except Exception as e:
        await _emit(run_id, "coder", "status",
                    f"Branch note: {e} (may already exist, continuing)")

    # All E2B tools including the new power-ups
    e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)

    # Build context for retry iterations
    prior_failure = ""
    if state.get("test_output") and state.get("test_passed") is False:
        prior_failure = (
            f"\n\n⚠️  PREVIOUS ATTEMPT FAILED — you MUST fix this:\n"
            f"{state['test_output'][-2000:]}\n"
            "Read the error carefully. Fix the specific failing assertion or import."
        )

    # Include repo context if architect captured it
    repo_ctx_snippet = ""
    if state.get("repo_context"):
        # Include just the file tree part (first 2000 chars) so coder knows what exists
        repo_ctx_snippet = (
            f"\n=== REPO FILE TREE (for reference) ===\n"
            f"{state['repo_context'][:2000]}\n"
            f"=== END ===\n"
        )

    user_msg = (
        f"Repository: {owner}/{repo}\n"
        f"Branch to work on: {branch_name}\n"
        f"Issue #{state['issue_number']}: {state['issue_title']}\n"
        f"{repo_ctx_snippet}"
        f"\n=== ARCHITECT'S IMPLEMENTATION PLAN ===\n"
        f"{state['plan']}\n"
        f"=== END PLAN ==={prior_failure}\n\n"
        "Your steps:\n"
        "1. setup_workspace() — FIRST, always.\n"
        "2. find_in_files() — understand existing patterns before writing.\n"
        "3. search_web() or fetch_url() if unsure about any library API.\n"
        "4. Implement ALL changes from the plan.\n"
        "5. run_linter() — fix any issues before committing.\n"
        "6. git_commit_all('feat: <description>') — commit everything.\n"
        "7. run_tests() — if ModuleNotFoundError, call install_package() and retry.\n"
        "8. End with TESTS_PASSED or TESTS_FAILED: <reason>."
    )

    result = await _react_loop(
        run_id=run_id,
        agent_name="coder",
        system_prompt=CODER_PROMPT,
        user_message=user_msg,
        tools=e2b_tools,
    )

    tests_passed = "TESTS_PASSED" in result.upper()

    # ── Auto-recovery: detect import errors and re-run ─────────────────
    # If the LLM forgot to call install_package itself, we catch it here
    if not tests_passed and "ModuleNotFoundError: No module named" in result:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", result)
        if match:
            pkg = match.group(1).split(".")[0]
            await _emit(run_id, "coder", "status",
                        f"Auto-installing missing package: {pkg}")
            install_tool = next(t for t in e2b_tools if t.name == "install_package")
            await asyncio.to_thread(install_tool.invoke, {"package_name": pkg})

            test_tool = next(t for t in e2b_tools if t.name == "run_tests")
            retry_result = await asyncio.to_thread(test_tool.invoke, {})
            await _emit(run_id, "coder", "tool_result",
                        f"Tests after auto-install:\n{retry_result[:1000]}")

            if "passed" in retry_result.lower() and "failed" not in retry_result.lower():
                tests_passed = True
                result = result + f"\n\nAuto-install of '{pkg}' fixed the issue.\n{retry_result}\nTESTS_PASSED"

    test_summary = (
        result.split("TESTS_FAILED:")[-1].strip()
        if not tests_passed and "TESTS_FAILED:" in result
        else ("All tests passed." if tests_passed else result[-300:])
    )

    await _emit(
        run_id, "coder", "status",
        "✅ Tests passed." if tests_passed else f"❌ Tests failed: {test_summary[:200]}",
    )

    # Push immediately while sandbox is warm
    await _emit(run_id, "coder", "status", f"Pushing branch {branch_name} to GitHub...")
    push_tool = next(t for t in e2b_tools if t.name == "git_push")
    try:
        push_result = await asyncio.to_thread(push_tool.invoke, {"branch": branch_name})
        await _emit(run_id, "coder", "status", f"Push: {push_result}")
    except Exception as push_err:
        await _emit(run_id, "coder", "status",
                    f"Push warning: {push_err} (will retry in PR step)")

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
    await _emit(run_id, "reviewer", "status",
                "Reviewing code, running security scan...")

    e2b_tools = make_e2b_tools(
        run_id=run_id,
        token=state["github_token"],
        owner=state["repo_owner"],
        repo=state["repo_name"],
    )
    review_tools = [t for t in e2b_tools if t.name in (
        "read_file", "list_files", "get_git_diff", "run_security_scan", "find_in_files",
    )]

    tests_status = (
        "PASSED ✅"
        if state.get("test_passed")
        else f"FAILED ❌\n{state.get('test_output', '')[-1500:]}"
    )

    user_msg = (
        f"Repository: {state['repo_owner']}/{state['repo_name']}\n"
        f"Issue #{state['issue_number']}: {state['issue_title']}\n\n"
        f"Implementation Plan:\n{state.get('plan', 'N/A')[:800]}\n\n"
        f"Test Result: {tests_status}\n"
        f"Iterations used: {state.get('iteration', 0)} / {state.get('max_iterations', 3)}\n\n"
        "Review the changes:\n"
        "1. get_git_diff() — see every line changed.\n"
        "2. run_security_scan() — automated checks.\n"
        "3. read_file() any modified files for full context.\n"
        "4. find_in_files() if you need to check patterns.\n"
        "5. Produce your full structured review."
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

    token       = state["github_token"]
    owner       = state["repo_owner"]
    repo        = state["repo_name"]
    branch_name = state["branch_name"]

    # Safety-net push (primary push already done in coder_node)
    try:
        e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)
        push_tool = next(t for t in e2b_tools if t.name == "git_push")
        push_result = await asyncio.to_thread(push_tool.invoke, {"branch": branch_name})
        await _emit(run_id, "system", "status", f"Push result: {push_result}")
    except Exception as push_err:
        await _emit(run_id, "system", "status",
                    f"Push skipped (already pushed): {push_err}")

    # Build PR description
    pr_body = PR_DESCRIPTION_TEMPLATE.format(
        summary=state.get("plan", "")[:600],
        changes=f"See diff on branch `{branch_name}`",
        test_output=(state.get("test_output") or "N/A")[-1200:],
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
            "base_branch": "main",
            "draft": True,
        },
    )

    pr_url = ""
    if "https://" in pr_result:
        pr_url = "https://" + pr_result.split("https://")[-1].strip()

    await _emit(run_id, "system", "status", pr_result)

    # ── Post success comment on the original issue ─────────────────────
    # This notifies the issue author that the swarm is done.
    if pr_url:
        comment_tool = next(t for t in gh_tools if t.name == "add_issue_comment")
        iterations_used = state.get("iteration", 0)
        verdict = "APPROVED" if "APPROVED" in (state.get("review_notes") or "") else "reviewed"
        success_comment = (
            f"## ✅ DevOps Swarm — Issue Resolved\n\n"
            f"A draft pull request has been opened: **{pr_url}**\n\n"
            f"**Summary:** {state.get('plan', '')[:300]}\n\n"
            f"**Iterations:** {iterations_used} / {state.get('max_iterations', 3)}\n"
            f"**Review verdict:** {verdict}\n\n"
            f"Please review the PR and merge if everything looks good.\n\n"
            f"---\n*DevOps Swarm AI — LangGraph + Groq Llama 3.3 70B + E2B*\n"
            f"*Built by Sowaiba Arshad*"
        )
        try:
            await asyncio.to_thread(
                comment_tool.invoke,
                {"issue_number": state["issue_number"], "body": success_comment},
            )
            await _emit(run_id, "system", "status",
                        "Success comment posted on GitHub issue.")
        except Exception as ce:
            await _emit(run_id, "system", "status",
                        f"Could not post success comment: {ce}")

    # Update Run record in DB
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
