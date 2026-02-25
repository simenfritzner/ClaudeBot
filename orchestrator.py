"""
Thesis Bot — Orchestrator
The core engine: receives tasks, routes to models, executes tool loops,
manages checkpoints, delegates subtasks, and summarizes results.
"""
from __future__ import annotations

import re
import json
from typing import Any, Callable, Coroutine

import anthropic

import db
from config import (
    ANTHROPIC_API_KEY,
    COST_LIMIT_DAILY,
    MAX_STEPS_PER_TASK,
    CHECKPOINT_STEP_RATIO,
    MODEL_SONNET_LATEST,
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    DEFAULT_TASK_BUDGET,
    MAX_TASK_BUDGET,
    MAX_SUBTASK_BUDGET,
    PLANNER_RESERVE_BUDGET,
    STEPS_BY_DEPTH,
)
from router import classify_task, calculate_cost
from context import (
    build_system_prompt,
    build_planner_prompt,
    build_worker_prompt,
    build_messages,
    build_subtask_messages,
    extract_keywords,
)
from tools import (
    get_tools_for_depth,
    get_tools_description_for_depth,
    get_tools_description,
    execute_tool,
)
from tools.delegation import handle_delegation

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Budget-parsing regex: $15 or $2.50 at start of message
_BUDGET_RE = re.compile(r"^\$(\d+\.?\d*)\s+")

# Signals that a task should be decomposed
_DECOMPOSE_SIGNALS = [
    "explore", "write the thesis", "go through", "comprehensive", "entire",
    "all chapters", "run experiments", "and then", "step by step",
    "systematically", "complete the", "full analysis", "every",
]


class TaskResult:
    """Result of processing a task."""

    def __init__(
        self,
        task_id: str,
        status: str,
        response: str,
        needs_checkpoint: bool = False,
        checkpoint_reason: str = "",
        conversation_history: list[dict] | None = None,
    ):
        self.task_id = task_id
        self.status = status           # "completed" | "checkpoint" | "failed" | "stalled"
        self.response = response       # Final text to send to user
        self.needs_checkpoint = needs_checkpoint
        self.checkpoint_reason = checkpoint_reason
        self.conversation_history = conversation_history  # for planner continuation


def _parse_budget(description: str) -> tuple[float, str]:
    """Extract $N budget prefix from description. Returns (budget, clean_description)."""
    match = _BUDGET_RE.match(description)
    if match:
        budget = float(match.group(1))
        budget = max(0.01, min(budget, MAX_TASK_BUDGET))
        return budget, description[match.end():]
    return DEFAULT_TASK_BUDGET, description


def _is_decomposable(description: str, budget: float) -> bool:
    """Cheap heuristic: should this task be decomposed by a planner?"""
    if budget > 2.00:
        return True
    lower = description.lower()
    if any(signal in lower for signal in _DECOMPOSE_SIGNALS):
        return True
    if len(description) > 300:
        return True
    return False


async def process_task(
    task_description: str,
    progress_callback: Callable[..., Coroutine] | None = None,
) -> TaskResult:
    """
    Main entry point: process a task end-to-end.

    1. Parse budget prefix
    2. Create task in DB
    3. Determine role (planner vs worker)
    4. Run appropriate agent loop
    5. Return result
    """
    # 1. Parse budget
    budget, description = _parse_budget(task_description)

    # 2. Create root task
    max_steps = STEPS_BY_DEPTH.get(0, MAX_STEPS_PER_TASK)
    task = await db.create_task(description, max_steps=max_steps, budget=budget, depth=0)
    task_id = task["id"]

    # 3. Determine role
    if _is_decomposable(description, budget):
        role = "planner"
    else:
        role = "worker"

    await db.update_task(task_id, status="classifying")

    try:
        # 4. Run agent loop
        result = await run_agent_loop(
            task_id=task_id,
            description=description,
            depth=0,
            budget=budget,
            role=role,
            progress_callback=progress_callback,
        )
        return result

    except Exception as e:
        error_msg = str(e)
        await db.update_task(task_id, status="failed", error=error_msg)
        return TaskResult(task_id, "failed", f"Task failed: {error_msg}")


async def continue_task(
    task_id: str,
    conversation_history: list[dict],
    budget: float,
    progress_callback: Callable[..., Coroutine] | None = None,
) -> TaskResult:
    """Continue a planner task after checkpoint approval."""
    task = await db.get_task(task_id)
    if not task:
        return TaskResult(task_id, "failed", "Task not found.")

    await db.update_task(task_id, status="in_progress")

    return await run_agent_loop(
        task_id=task_id,
        description=task["description"],
        depth=0,
        budget=budget,
        role="planner",
        progress_callback=progress_callback,
        conversation_history=conversation_history,
    )


async def run_agent_loop(
    task_id: str,
    description: str,
    depth: int,
    budget: float,
    role: str,
    progress_callback: Callable[..., Coroutine] | None = None,
    conversation_history: list[dict] | None = None,
    context_files: list[str] | None = None,
) -> TaskResult:
    """
    Core agentic loop used for both planners and workers at any depth.

    Args:
        task_id: The task ID in the database
        description: Task description
        depth: Nesting depth (0 = root)
        budget: Budget for this task
        role: "planner" or "worker"
        progress_callback: Optional callback for progress events
        conversation_history: Optional pre-existing conversation (for continuation)
        context_files: Optional file paths to inject as context
    """
    # Model selection
    if role == "planner":
        model = MODEL_SONNET_LATEST
        max_input = MAX_INPUT_TOKENS["planner"]
        max_output = MAX_OUTPUT_TOKENS["planner"]
    else:
        # Workers get classified by router
        model, tier, max_input, max_output = await classify_task(description)

    await db.update_task(task_id, status="in_progress", model=model)

    # System prompt
    tools_desc = get_tools_description_for_depth(depth)
    if role == "planner":
        system_prompt = await build_planner_prompt(tools_desc, budget)
    elif depth == 0:
        # Root worker: full context with memory
        system_prompt = await build_system_prompt(tools_description=get_tools_description())
    else:
        # Sub-worker: minimal prompt
        system_prompt = build_worker_prompt(tools_desc, budget)

    # Tools for this depth
    tools = get_tools_for_depth(depth)

    # Build messages
    if conversation_history:
        messages = conversation_history
    elif depth > 0 and context_files:
        messages = build_subtask_messages(description, context_files)
    elif depth == 0:
        keywords = extract_keywords(description)
        messages = await build_messages(description, relevant_keywords=keywords)
    else:
        messages = [{"role": "user", "content": description}]

    # Step limits
    max_steps = STEPS_BY_DEPTH.get(depth, 3)
    step = 0
    final_response = ""
    planner_first_response = True if role == "planner" and not conversation_history else False

    try:
        while step < max_steps:
            step += 1
            await db.update_task(task_id, step_count=step)

            # Check task budget
            current_task = await db.get_task(task_id)
            if current_task and current_task["token_cost"] > budget:
                await db.update_task(task_id, status="stalled", error="Budget exceeded")
                return TaskResult(
                    task_id, "stalled",
                    f"Task halted — budget (${budget:.2f}) exceeded. Spent ${current_task['token_cost']:.4f}.",
                )

            # Check daily limit (global safety net)
            daily_cost = await db.get_daily_cost()
            if daily_cost > COST_LIMIT_DAILY:
                await db.update_task(task_id, status="stalled", error="Daily cost limit exceeded")
                return TaskResult(
                    task_id, "stalled",
                    f"Daily budget limit (${COST_LIMIT_DAILY:.2f}) reached. Total today: ${daily_cost:.4f}.",
                )

            # Call Claude
            response = await client.messages.create(
                model=model,
                max_tokens=max_output,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

            # Log cost
            cost = calculate_cost(model, response.usage.input_tokens, response.usage.output_tokens)
            await db.log_cost(task_id, model, response.usage.input_tokens, response.usage.output_tokens, cost)

            # Process response
            assistant_content = response.content
            text_parts = []
            tool_uses = []

            for block in assistant_content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if text_parts:
                final_response = "\n".join(text_parts)

            # Planner checkpoint: after first response, return plan for user approval
            if planner_first_response and final_response:
                planner_first_response = False
                # Add this response to history for continuation
                messages.append({"role": "assistant", "content": assistant_content})

                # If there are tool calls, we need to checkpoint before executing them
                if tool_uses:
                    await db.update_task(task_id, status="checkpoint")
                    return TaskResult(
                        task_id, "checkpoint",
                        final_response,
                        needs_checkpoint=True,
                        checkpoint_reason="Plan ready for approval",
                        conversation_history=messages,
                    )

            # If no tool calls, we're done
            if response.stop_reason == "end_turn" or not tool_uses:
                break

            # Add assistant message to history (if not already added by checkpoint logic)
            if not (role == "planner" and step == 1 and not conversation_history):
                messages.append({"role": "assistant", "content": assistant_content})

            # Execute tool calls
            tool_results = []
            for tool_use in tool_uses:
                if tool_use.name == "delegate_task":
                    # Calculate remaining budget for this task
                    current_task = await db.get_task(task_id)
                    spent = current_task["token_cost"] if current_task else 0.0
                    remaining = budget - spent

                    result_text = await handle_delegation(
                        tool_use.input,
                        parent_task_id=task_id,
                        parent_depth=depth,
                        parent_budget_remaining=remaining,
                        progress_callback=progress_callback,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result_text,
                    })
                else:
                    result_text = await execute_tool(tool_use.name, tool_use.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result_text,
                    })

            messages.append({"role": "user", "content": tool_results})

            # Uncertainty checkpoint (depth=0 workers only)
            if depth == 0 and role == "worker" and final_response:
                if _should_checkpoint(final_response, description):
                    await db.update_task(task_id, status="checkpoint")
                    return TaskResult(
                        task_id, "checkpoint",
                        final_response,
                        needs_checkpoint=True,
                        checkpoint_reason="Claude expressed uncertainty",
                    )

        # Task completed — summarize and store
        await db.update_task(task_id, status="completed", result=final_response[:1000])

        # Save session memory only for depth=0
        if depth == 0:
            keywords = extract_keywords(description)
            summary = {
                "description": description[:200],
                "result": final_response[:300] if final_response else "No text output",
                "model": model,
                "steps": step,
                "role": role,
            }
            await db.save_session_memory(task_id, summary, keywords)

        return TaskResult(task_id, "completed", final_response)

    except Exception as e:
        error_msg = str(e)
        await db.update_task(task_id, status="failed", error=error_msg)
        return TaskResult(task_id, "failed", f"Task failed: {error_msg}")


async def run_subtask(
    description: str,
    parent_task_id: str,
    parent_depth: int,
    budget: float,
    context_files: list[str] | None = None,
    progress_callback: Callable[..., Coroutine] | None = None,
) -> TaskResult:
    """Spawn and run a worker subtask."""
    child_depth = parent_depth + 1
    max_steps = STEPS_BY_DEPTH.get(child_depth, 3)

    # Create subtask record
    task = await db.create_subtask(
        description=description,
        parent_task_id=parent_task_id,
        depth=child_depth,
        budget=budget,
        max_steps=max_steps,
    )

    return await run_agent_loop(
        task_id=task["id"],
        description=description,
        depth=child_depth,
        budget=budget,
        role="worker",
        progress_callback=progress_callback,
        context_files=context_files,
    )


def _should_checkpoint(response_text: str, task_description: str) -> bool:
    """Check if Claude's response indicates uncertainty that warrants a checkpoint."""
    uncertainty_markers = [
        "i'm not sure",
        "i'm unsure",
        "this could go either way",
        "do you want me to",
        "should i proceed",
        "before i continue",
        "a few options",
        "which approach",
        "let me know if",
        "would you prefer",
    ]
    lower = response_text.lower()
    return any(marker in lower for marker in uncertainty_markers)


async def get_status() -> str:
    """Get a status summary for the heartbeat."""
    active = await db.get_active_tasks()
    daily = await db.get_daily_cost()
    monthly = await db.get_monthly_cost()

    queued = sum(1 for t in active if t["status"] == "queued")
    in_progress = sum(1 for t in active if t["status"] == "in_progress")

    return (
        f"**Status**\n"
        f"Queue: {queued} | Active: {in_progress}\n"
        f"Today: ${daily:.4f} | Month: ${monthly:.4f}"
    )


async def recover_stale_tasks() -> list[str]:
    """Find and handle tasks stuck in 'in_progress' (crash recovery)."""
    stale = await db.get_stale_tasks()
    messages = []
    for task in stale:
        await db.update_task(task["id"], status="failed", error="Recovered after restart — was in_progress")
        messages.append(f"Recovered stale task `{task['id']}`: {task['description'][:80]}")
    return messages
