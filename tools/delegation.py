"""
Delegation tool — allows a planner agent to spawn focused sub-agents.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Coroutine

import db
from config import (
    MAX_DELEGATION_DEPTH,
    MAX_SUBTASK_BUDGET,
    MAX_SUBTASKS_PER_TASK,
    MIN_SUBTASK_BUDGET,
)

if TYPE_CHECKING:
    pass

DELEGATION_TOOLS = [
    {
        "name": "delegate_task",
        "description": (
            "Delegate a focused subtask to a sub-agent. The sub-agent runs independently "
            "with its own tools and returns only its result. Use this to decompose work. "
            "Each subtask must be self-contained — the sub-agent has NO memory of this conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": (
                        "Clear, specific description. Include all needed context (file paths, "
                        "section names, requirements). The sub-agent knows nothing else."
                    ),
                },
                "expected_output": {
                    "type": "string",
                    "description": (
                        "What the result should look like. E.g., 'A 500-word draft saved to "
                        "chapters/methods.tex' or 'Summary of key findings from data/results.csv'"
                    ),
                },
                "budget_usd": {
                    "type": "number",
                    "description": (
                        "Max budget in USD. Typical: $0.03 for reads, $0.10 for analysis, "
                        "$0.50 for writing tasks."
                    ),
                },
                "context_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional file paths (relative to thesis dir) the sub-agent should "
                        "read before starting. Provide paths instead of pasting content."
                    ),
                },
            },
            "required": ["task_description", "expected_output", "budget_usd"],
        },
    }
]


async def handle_delegation(
    input_data: dict[str, Any],
    *,
    parent_task_id: str,
    parent_depth: int,
    parent_budget_remaining: float,
    progress_callback: Callable[..., Coroutine] | None = None,
) -> str:
    """Execute a delegate_task tool call by spawning a sub-agent."""
    # Lazy import to avoid circular dependency
    from orchestrator import run_subtask

    task_desc = input_data["task_description"]
    expected = input_data["expected_output"]
    budget = float(input_data["budget_usd"])
    context_files = input_data.get("context_files")

    # Validate depth
    child_depth = parent_depth + 1
    if child_depth > MAX_DELEGATION_DEPTH:
        return f"Error: Max delegation depth ({MAX_DELEGATION_DEPTH}) reached. Execute directly instead."

    # Validate subtask count
    count = await db.get_subtask_count(parent_task_id)
    if count >= MAX_SUBTASKS_PER_TASK:
        return f"Error: Max subtask limit ({MAX_SUBTASKS_PER_TASK}) reached for this task."

    # Validate budget
    budget = max(budget, MIN_SUBTASK_BUDGET)
    budget = min(budget, MAX_SUBTASK_BUDGET, parent_budget_remaining)
    if budget < MIN_SUBTASK_BUDGET:
        return f"Error: Insufficient budget remaining (${parent_budget_remaining:.4f})."

    # Full description for the sub-agent
    full_desc = f"{task_desc}\n\nExpected output: {expected}"

    # Run the subtask
    result = await run_subtask(
        description=full_desc,
        parent_task_id=parent_task_id,
        parent_depth=parent_depth,
        budget=budget,
        context_files=context_files,
        progress_callback=progress_callback,
    )

    # Cascade cost to parent chain
    child_task = await db.get_task(result.task_id)
    child_cost = child_task["token_cost"] if child_task else 0.0
    await db.cascade_cost_to_parent(result.task_id, child_cost)

    # Fire progress callback
    if progress_callback:
        await progress_callback("subtask_completed", {
            "task_id": result.task_id,
            "description": task_desc[:100],
            "cost": child_cost,
            "status": result.status,
        })

    # Truncate result for the parent context — keep short to avoid blowing up
    # the planner's input tokens on subsequent calls
    response = result.response or "(no output)"
    if len(response) > 500:
        response = response[:450] + f"\n... [truncated, {len(response)} chars total]"

    status_prefix = f"[{result.status}] " if result.status != "completed" else ""
    return f"{status_prefix}Subtask result (${child_cost:.4f}):\n{response}"
