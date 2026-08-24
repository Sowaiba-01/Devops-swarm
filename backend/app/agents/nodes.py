"""
Agent nodes.

Each node runs a ReAct loop against Groq and returns a partial state update.
Only `supervisor_node` writes `phase`.

Notable corrections against the previous implementation:

* Tool results were truncated to 450 characters before being handed back to the
  model. A source file, a diff, and a pytest failure are all larger than that,
  so the Coder was reasoning about fragments. The budget is now configurable and
  defaults to 6000, with head-and-tail truncation that preserves the error at
  the end of a test run.
* The Reviewer's verdict was parsed with `"APPROVED" in text`, which also
  matches "NOT APPROVED" and "cannot be APPROVED". It is parsed from the
  structured verdict line.
* A run whose tests failed was still written to the database as `success`.
  Pipeline completion and test outcome are now recorded separately.
* `handle_error` swallowed failures that happened *inside* it, leaving runs
  wedged in `running` forever.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from app.config import settings
from app.core.logging import get_logger, run_id_var
from app.core.metrics import (
    agent_node_duration,
    llm_calls_total,
    observe,
    tool_calls_total,
    tool_duration,
)
from app.db import repository
from app.tools.e2b_tools import make_e2b_tools
from app.tools.github_tools import make_github_tools
from app.tools.sandbox import close_sandbox
from app.ws_manager import manager

from .prompts import ARCHITECT_PROMPT, CODER_PROMPT, PR_DESCRIPTION_TEMPLATE, REVIEWER_PROMPT
from .state import MAX_AGENT_ATTEMPTS, SwarmState

logger = get_logger(__name__)

# Stop the model hammering one tool. Applies to identical (name, args) pairs, so
# legitimate repeats — reading five different files — are not penalised.
MAX_IDENTICAL_TOOL_CALLS = 3
MAX_MALFORMED_TOOL_CALLS = 3

_VERDICT_RE = re.compile(r"###\s*Verdict:\s*(APPROVED|NEEDS_REVISION)", re.IGNORECASE)
_TESTS_PASSED_RE = re.compile(r"\bTESTS_PASSED\b")
_TESTS_FAILED_RE = re.compile(r"\bTESTS_FAILED\s*:?\s*(.*)", re.IGNORECASE)
_MODULE_ERROR_RE = re.compile(r"No module named ['\"]([A-Za-z0-9_.\-]+)['\"]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, budget: int) -> str:
    """
    Trim to `budget` characters, keeping both ends.

    Head-only truncation is the wrong choice for command output: a pytest run's
    verdict and traceback are at the *end*, so cutting the tail throws away the
    only part the model needs.
    """
    if len(text) <= budget:
        return text
    head = budget * 2 // 3
    tail = budget - head - 40
    return f"{text[:head]}\n\n...[{len(text) - budget} characters elided]...\n\n{text[-tail:]}"


def _make_llm(tools: Sequence[Any]) -> Any:
    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        api_key=SecretStr(settings.GROQ_API_KEY),
        max_retries=settings.LLM_MAX_RETRIES,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )
    return llm.bind_tools(list(tools))


async def emit(
    run_id: str,
    agent: str,
    log_type: str,
    content: str,
    extra: dict | None = None,
) -> None:
    """
    Persist an agent event and push it to watchers.

    Redaction happens inside `append_log`, so this is the single choke point
    where agent output reaches storage and the network.
    """
    try:
        payload = await repository.append_log(
            run_id=run_id, agent=agent, log_type=log_type, content=content, extra=extra
        )
        await manager.broadcast(run_id, payload)
    except Exception:
        # Telemetry must never abort a run.
        logger.exception("Failed to emit agent event", extra={"run_id": run_id})


async def _react_loop(
    *,
    run_id: str,
    agent_name: str,
    system_prompt: str,
    user_message: str,
    tools: Sequence[Any],
) -> str:
    """Run Reason/Act until the model stops calling tools. Returns its final prose."""
    llm = _make_llm(tools)
    tool_map = {t.name: t for t in tools}
    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    final_response = ""
    malformed = 0
    call_counts: dict[str, int] = {}

    for _ in range(settings.MAX_REACT_ITERATIONS):
        try:
            response: AIMessage = await llm.ainvoke(messages)
            llm_calls_total.labels(agent=agent_name, outcome="ok").inc()
        except Exception as exc:
            detail = str(exc)
            is_malformed = "tool_use_failed" in detail or "failed_generation" in detail
            llm_calls_total.labels(
                agent=agent_name, outcome="malformed" if is_malformed else "error"
            ).inc()
            if not is_malformed:
                raise
            malformed += 1
            if malformed > MAX_MALFORMED_TOOL_CALLS:
                await emit(
                    run_id,
                    agent_name,
                    "status",
                    f"Stopping: {malformed} malformed tool calls in a row.",
                )
                break
            await emit(
                run_id,
                agent_name,
                "status",
                f"Malformed tool call — retrying ({malformed}/{MAX_MALFORMED_TOOL_CALLS}).",
            )
            messages.append(
                HumanMessage(
                    content=(
                        "Your last response contained a malformed tool call. Emit a valid "
                        "JSON function call with no surrounding prose, or give your final "
                        "answer as plain text."
                    )
                )
            )
            continue

        messages.append(response)

        if response.content:
            text = str(response.content)
            final_response = text
            await emit(run_id, agent_name, "thought", text)

        if not response.tool_calls:
            break

        for call in response.tool_calls:
            name, args, call_id = call["name"], call["args"], call["id"]

            # Key on name *and* arguments: repeating an identical call is a
            # loop, but reading several different files is normal work.
            signature = f"{name}:{sorted(args.items()) if isinstance(args, dict) else args}"
            call_counts[signature] = call_counts.get(signature, 0) + 1
            if call_counts[signature] > MAX_IDENTICAL_TOOL_CALLS:
                await emit(
                    run_id,
                    agent_name,
                    "status",
                    f"`{name}` called {call_counts[signature]}x with identical arguments — stopping.",
                )
                messages.append(
                    ToolMessage(
                        content=(
                            f"You have already called {name} with these exact arguments "
                            f"{call_counts[signature]} times and the result will not change. "
                            "Take a different action or give your final answer now."
                        ),
                        tool_call_id=call_id,
                    )
                )
                continue

            await emit(
                run_id, agent_name, "tool_call", f"{name}", extra={"tool": name, "args": args}
            )

            tool_obj = tool_map.get(name)
            if tool_obj is None:
                result = f"ERROR: unknown tool '{name}'. Available: {', '.join(sorted(tool_map))}"
                tool_calls_total.labels(tool=name, outcome="unknown").inc()
            else:
                try:
                    with observe(tool_duration, tool=name):
                        result = str(await asyncio.to_thread(tool_obj.invoke, args))
                    tool_calls_total.labels(tool=name, outcome="ok").inc()
                except Exception as exc:
                    logger.exception("Tool %s raised", name, extra={"run_id": run_id})
                    result = f"ERROR executing {name}: {exc}"
                    tool_calls_total.labels(tool=name, outcome="error").inc()

            budgeted = _truncate(result, settings.TOOL_RESULT_CHAR_BUDGET)
            await emit(run_id, agent_name, "tool_result", budgeted, extra={"tool": name})
            messages.append(ToolMessage(content=budgeted, tool_call_id=call_id))
    else:
        await emit(
            run_id,
            agent_name,
            "status",
            f"Reached the {settings.MAX_REACT_ITERATIONS}-step limit for this agent.",
        )

    return final_response


# ---------------------------------------------------------------------------
# Supervisor — pure routing, no LLM
# ---------------------------------------------------------------------------


async def supervisor_node(state: SwarmState) -> dict:
    """Sole writer of `phase`."""
    run_id = state["run_id"]
    run_id_var.set(run_id)

    if state.get("status") == "failed":
        await emit(run_id, "supervisor", "status", "Run failed — stopping.")
        return {"phase": "done"}

    if state.get("pr_url"):
        return {"phase": "done"}

    plan = (state.get("plan") or "").strip()
    if not plan:
        attempts = state.get("architect_attempts", 0)
        if attempts >= MAX_AGENT_ATTEMPTS:
            # Without this the supervisor bounced back to the architect forever.
            message = (
                f"Architect produced no plan after {attempts} attempts. "
                "The model returned no usable text — check GROQ_MODEL and the API quota."
            )
            await emit(run_id, "supervisor", "error", message)
            return {"phase": "done", "status": "failed", "error_message": message}
        await emit(run_id, "supervisor", "status", "Routing to Architect.")
        await repository.set_phase(run_id, "architect")
        return {"phase": "architect"}

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", settings.MAX_CORRECTION_ITERATIONS)
    tests_passed = state.get("test_passed")

    if tests_passed is None or (tests_passed is False and iteration < max_iterations):
        await emit(
            run_id,
            "supervisor",
            "status",
            f"Routing to Coder (attempt {iteration + 1}/{max_iterations}).",
        )
        await repository.set_phase(run_id, "coder")
        return {"phase": "coder"}

    if not (state.get("review_notes") or "").strip():
        attempts = state.get("reviewer_attempts", 0)
        if attempts >= MAX_AGENT_ATTEMPTS:
            await emit(
                run_id,
                "supervisor",
                "status",
                "Reviewer returned nothing twice — proceeding to PR without a review.",
            )
            await repository.set_phase(run_id, "pr")
            return {
                "phase": "pr",
                "review_notes": "Review unavailable: the reviewer agent produced no output.",
                "review_verdict": "UNKNOWN",
            }
        await emit(run_id, "supervisor", "status", "Routing to Reviewer.")
        await repository.set_phase(run_id, "reviewer")
        return {"phase": "reviewer"}

    await emit(run_id, "supervisor", "status", "Routing to PR creation.")
    await repository.set_phase(run_id, "pr")
    return {"phase": "pr"}


# ---------------------------------------------------------------------------
# Architect
# ---------------------------------------------------------------------------


async def architect_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    run_id_var.set(run_id)
    owner, repo = state["repo_owner"], state["repo_name"]

    with observe(agent_node_duration, agent="architect"):
        gh_tools = make_github_tools(token=state["github_token"], owner=owner, repo=repo)
        by_name = {t.name: t for t in gh_tools}

        await emit(run_id, "architect", "status", "Fetching repository context.")
        repo_context = state.get("repo_context")
        if not repo_context:
            try:
                repo_context = str(
                    await asyncio.to_thread(by_name["get_full_repo_context"].invoke, {})
                )
                await emit(
                    run_id,
                    "architect",
                    "status",
                    f"Repository context loaded ({len(repo_context):,} characters).",
                )
            except Exception as exc:
                repo_context = f"(repository context unavailable: {exc})"
                await emit(run_id, "architect", "status", repo_context)

        try:
            comments = str(
                await asyncio.to_thread(
                    by_name["get_issue_comments"].invoke, {"issue_number": state["issue_number"]}
                )
            )
        except Exception:
            comments = "(issue comments unavailable)"

        read_only = [
            t
            for t in gh_tools
            if t.name
            in {"get_file_contents", "list_directory", "search_code", "get_repo_structure"}
        ]

        user_message = (
            f"Repository: {owner}/{repo}\n"
            f"Issue #{state['issue_number']}: {state['issue_title']}\n\n"
            f"Description:\n{state['issue_body'][:4000]}\n\n"
            f"Comments:\n{comments[:3000]}\n\n"
            f"=== REPOSITORY CONTEXT (already fetched) ===\n"
            f"{_truncate(repo_context, settings.REPO_CONTEXT_CHAR_BUDGET)}\n"
            f"=== END CONTEXT ===\n\n"
            "Read the files most relevant to this issue, then write the implementation plan."
        )

        await emit(run_id, "architect", "status", "Planning.")
        plan = await _react_loop(
            run_id=run_id,
            agent_name="architect",
            system_prompt=ARCHITECT_PROMPT,
            user_message=user_message,
            tools=read_only,
        )

        attempts = state.get("architect_attempts", 0) + 1
        if not plan.strip():
            await emit(run_id, "architect", "status", "No plan produced on this attempt.")
            return {"repo_context": repo_context, "architect_attempts": attempts}

        # Post the plan so a human can object before any code is written.
        try:
            await asyncio.to_thread(
                by_name["add_issue_comment"].invoke,
                {
                    "issue_number": state["issue_number"],
                    "body": (
                        "## DevOps Swarm — implementation plan\n\n"
                        f"{plan[:5000]}\n\n---\n"
                        "*The swarm is implementing this now. A draft PR will follow.*"
                    ),
                },
            )
            await emit(run_id, "architect", "status", "Plan posted to the issue.")
        except Exception as exc:
            await emit(run_id, "architect", "status", f"Could not post the plan comment: {exc}")

        await emit(run_id, "architect", "status", "Planning complete.")
        return {"plan": plan, "repo_context": repo_context, "architect_attempts": attempts}


# ---------------------------------------------------------------------------
# Coder
# ---------------------------------------------------------------------------


def _branch_name(issue_number: int, issue_title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", issue_title.lower()).strip("-")[:40].strip("-")
    return f"swarm/issue-{issue_number}" + (f"-{slug}" if slug else "")


async def coder_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    run_id_var.set(run_id)
    owner, repo, token = state["repo_owner"], state["repo_name"], state["github_token"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", settings.MAX_CORRECTION_ITERATIONS)

    with observe(agent_node_duration, agent="coder"):
        await emit(run_id, "coder", "status", f"Coding attempt {iteration + 1}/{max_iterations}.")

        branch = state.get("branch_name") or _branch_name(
            state["issue_number"], state["issue_title"]
        )
        if not state.get("branch_name"):
            gh_tools = make_github_tools(token=token, owner=owner, repo=repo)
            create_branch = next(t for t in gh_tools if t.name == "create_branch")
            result = await asyncio.to_thread(create_branch.invoke, {"branch_name": branch})
            await emit(run_id, "coder", "status", str(result))

        e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)

        prior_failure = ""
        if state.get("test_passed") is False and state.get("test_output"):
            prior_failure = (
                "\nThe previous attempt failed. Fix the specific error below — "
                "do not restart from scratch:\n"
                f"{_truncate(state.get('test_output') or '', 3000)}\n"
            )

        user_message = (
            f"Repository: {owner}/{repo}\nBranch: {branch}\n"
            f"Issue #{state['issue_number']}: {state['issue_title']}\n\n"
            f"=== IMPLEMENTATION PLAN ===\n"
            f"{_truncate(state.get('plan') or '', settings.PLAN_CHAR_BUDGET)}\n"
            f"=== END PLAN ===\n"
            f"{prior_failure}\n"
            "Work through it: setup_workspace, write the code, run_linter, "
            "git_commit_all, run_tests. Finish with TESTS_PASSED or TESTS_FAILED: <reason>."
        )

        result = await _react_loop(
            run_id=run_id,
            agent_name="coder",
            system_prompt=CODER_PROMPT,
            user_message=user_message,
            tools=e2b_tools,
        )

        tests_passed = bool(_TESTS_PASSED_RE.search(result))
        by_name = {t.name: t for t in e2b_tools}

        # A repository with no test suite cannot fail its tests; treat linting
        # as the gate rather than looping three times over nothing.
        if not tests_passed and "NO_TESTS_FOUND" in result:
            await emit(
                run_id,
                "coder",
                "status",
                "Repository has no test suite — accepting the change on lint alone.",
            )
            tests_passed = True

        # Recover from a missing dependency the model failed to install itself.
        if not tests_passed:
            match = _MODULE_ERROR_RE.search(result)
            if match:
                package = match.group(1).split(".")[0]
                await emit(run_id, "coder", "status", f"Installing missing dependency '{package}'.")
                await asyncio.to_thread(
                    by_name["install_package"].invoke, {"package_name": package}
                )
                retry = str(await asyncio.to_thread(by_name["run_tests"].invoke, {}))
                await emit(
                    run_id,
                    "coder",
                    "tool_result",
                    _truncate(retry, 4000),
                    extra={"tool": "run_tests"},
                )
                if "exit_code: 0" in retry:
                    tests_passed = True
                    result = f"{result}\n\nAfter installing '{package}':\n{retry}\nTESTS_PASSED"

        await emit(
            run_id,
            "coder",
            "status",
            "Tests passed." if tests_passed else f"Tests failed: {_failure_reason(result)}",
        )

        # Push while the sandbox is still warm.
        await emit(run_id, "coder", "status", f"Pushing {branch}.")
        push = str(await asyncio.to_thread(by_name["git_push"].invoke, {"branch": branch}))
        await emit(run_id, "coder", "status", _truncate(push, 2000))

        return {
            "branch_name": branch,
            "test_output": result,
            "test_passed": tests_passed,
            "iteration": iteration + 1,
        }


def _failure_reason(result: str) -> str:
    match = _TESTS_FAILED_RE.search(result)
    if match and match.group(1).strip():
        return match.group(1).strip()[:300]
    return result.strip()[-300:] or "no reason given"


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


def parse_verdict(review_text: str) -> str:
    """
    Extract the reviewer's verdict.

    Substring matching on "APPROVED" also matches "NOT APPROVED" and "cannot be
    APPROVED", so a rejection was read as an approval. Match the structured
    verdict line, preferring the last one if the model restates itself.
    """
    matches = _VERDICT_RE.findall(review_text or "")
    if matches:
        return matches[-1].upper()
    tail = (review_text or "")[-400:].upper()
    if "NEEDS_REVISION" in tail:
        return "NEEDS_REVISION"
    if re.search(r"(?<!NOT )\bAPPROVED\b", tail):
        return "APPROVED"
    return "UNKNOWN"


async def reviewer_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    run_id_var.set(run_id)

    with observe(agent_node_duration, agent="reviewer"):
        await emit(run_id, "reviewer", "status", "Reviewing the diff and scanning for issues.")

        e2b_tools = make_e2b_tools(
            run_id=run_id,
            token=state["github_token"],
            owner=state["repo_owner"],
            repo=state["repo_name"],
        )
        review_tools = [
            t
            for t in e2b_tools
            if t.name
            in {"read_file", "list_files", "get_git_diff", "run_security_scan", "find_in_files"}
        ]

        tests = (
            "passed"
            if state.get("test_passed")
            else f"FAILED\n{_truncate(state.get('test_output') or '', 2000)}"
        )
        user_message = (
            f"Repository: {state['repo_owner']}/{state['repo_name']}\n"
            f"Issue #{state['issue_number']}: {state['issue_title']}\n\n"
            f"Plan:\n{_truncate(state.get('plan') or '', 2000)}\n\n"
            f"Test result: {tests}\n\n"
            "Call get_git_diff() first, then run_security_scan(). "
            "Finish with the verdict line."
        )

        review_notes = await _react_loop(
            run_id=run_id,
            agent_name="reviewer",
            system_prompt=REVIEWER_PROMPT,
            user_message=user_message,
            tools=review_tools,
        )

        attempts = state.get("reviewer_attempts", 0) + 1
        if not review_notes.strip():
            await emit(run_id, "reviewer", "status", "No review produced on this attempt.")
            return {"reviewer_attempts": attempts}

        verdict = parse_verdict(review_notes)
        await emit(run_id, "reviewer", "status", f"Review complete — verdict: {verdict}.")
        return {
            "review_notes": review_notes,
            "review_verdict": verdict,
            "reviewer_attempts": attempts,
        }


# ---------------------------------------------------------------------------
# Pull request
# ---------------------------------------------------------------------------

_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


async def pr_node(state: SwarmState) -> dict:
    run_id = state["run_id"]
    run_id_var.set(run_id)
    owner, repo, token = state["repo_owner"], state["repo_name"], state["github_token"]
    branch = state.get("branch_name")

    with observe(agent_node_duration, agent="pr"):
        if not branch:
            message = "No branch was created — there is nothing to open a pull request from."
            await emit(run_id, "system", "error", message)
            await repository.mark_failed(run_id, message)
            close_sandbox(run_id)
            return {"status": "failed", "error_message": message, "phase": "done"}

        await emit(run_id, "system", "status", "Pushing and opening the pull request.")

        e2b_tools = make_e2b_tools(run_id=run_id, token=token, owner=owner, repo=repo)
        push_tool = next(t for t in e2b_tools if t.name == "git_push")
        push = str(await asyncio.to_thread(push_tool.invoke, {"branch": branch}))
        await emit(run_id, "system", "status", _truncate(push, 1500))

        tests_passed = bool(state.get("test_passed"))
        verdict = state.get("review_verdict") or "UNKNOWN"

        # The PR body states the real outcome. Opening a PR for a change whose
        # tests fail is useful, but it must say so at the top.
        banner = (
            "> **Tests passed** and the review verdict was " f"`{verdict}`."
            if tests_passed
            else "> ⚠️ **Tests did not pass.** This PR is opened for human inspection; "
            "do not merge it as-is."
        )

        body = PR_DESCRIPTION_TEMPLATE.format(
            banner=banner,
            summary=_truncate(state.get("plan") or "No plan recorded.", 3000),
            branch=branch,
            iterations=state.get("iteration", 0),
            max_iterations=state.get("max_iterations", settings.MAX_CORRECTION_ITERATIONS),
            test_status="passed" if tests_passed else "failed",
            test_output=_truncate(state.get("test_output") or "N/A", 4000),
            review_verdict=verdict,
            review_notes=_truncate(state.get("review_notes") or "N/A", 6000),
            issue_number=state["issue_number"],
        )
        prefix = "fix" if tests_passed else "wip"
        title = f"{prefix}: {state['issue_title']}"[:250]

        gh_tools = make_github_tools(token=token, owner=owner, repo=repo)
        by_name = {t.name: t for t in gh_tools}

        pr_result = str(
            await asyncio.to_thread(
                by_name["create_pull_request"].invoke,
                {"title": title, "body": body, "head_branch": branch, "draft": True},
            )
        )
        await emit(run_id, "system", "status", pr_result)

        match = _PR_URL_RE.search(pr_result)
        if not match:
            message = f"Pull request creation failed: {pr_result[:500]}"
            await emit(run_id, "system", "error", message)
            await repository.mark_failed(run_id, message, branch_name=branch)
            close_sandbox(run_id)
            return {"status": "failed", "error_message": message, "phase": "done"}

        pr_url = match.group(0)

        try:
            await asyncio.to_thread(
                by_name["add_issue_comment"].invoke,
                {
                    "issue_number": state["issue_number"],
                    "body": (
                        f"## DevOps Swarm — {'resolved' if tests_passed else 'needs attention'}\n\n"
                        f"Draft pull request: {pr_url}\n\n"
                        f"- Tests: **{'passed' if tests_passed else 'failed'}**\n"
                        f"- Review verdict: **{verdict}**\n"
                        f"- Correction rounds: {state.get('iteration', 0)}/"
                        f"{state.get('max_iterations', 3)}\n"
                    ),
                },
            )
        except Exception as exc:
            await emit(run_id, "system", "status", f"Could not post the completion comment: {exc}")

        await repository.mark_succeeded(
            run_id,
            pr_url=pr_url,
            branch_name=branch,
            iteration_count=state.get("iteration", 0),
            tests_passed=tests_passed,
            review_verdict=verdict,
        )
        close_sandbox(run_id)
        return {"pr_url": pr_url, "status": "success", "phase": "done"}


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


async def handle_error(run_id: str, error: BaseException) -> None:
    """
    Terminal handler for anything that escapes the graph.

    Every step is individually guarded: if emitting the log fails, the run must
    still be marked failed, and if that fails the sandbox must still be released.
    Otherwise one bad exception leaves a run stuck at `running` and a paid
    sandbox alive.
    """
    message = f"{type(error).__name__}: {error}"
    logger.exception("Swarm run failed", extra={"run_id": run_id})

    try:
        await emit(run_id, "system", "error", message)
    except Exception:
        logger.exception("Could not record the failure event", extra={"run_id": run_id})

    try:
        await repository.mark_failed(run_id, message)
    except Exception:
        logger.exception("Could not mark the run failed", extra={"run_id": run_id})

    try:
        close_sandbox(run_id)
    except Exception:
        logger.exception("Could not release the sandbox", extra={"run_id": run_id})
