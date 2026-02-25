"""
Thesis Bot — Orchestrator
The core engine: receives tasks, routes to models, executes tool loops,
manages checkpoints, and summarizes results.
"""
import json
import anthropic

import db
from config import (
    ANTHROPIC_API_KEY,
    COST_LIMIT_PER_TASK,
    COST_LIMIT_DAILY,
    MAX_STEPS_PER_TASK,
    CHECKPOINT_STEP_RATIO,
)
from router import classify_task, calculate_cost
from context import build_system_prompt, build_messages, extract_keywords
from tools import ALL_TOOLS, execute_tool, get_tools_description

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


class TaskResult:
    """Result of processing a task."""
    def __init__(self, task_id: str, status: str, response: str, needs_checkpoint: bool = False, checkpoint_reason: str = ""):
        self.task_id = task_id
        self.status = status           # "completed" | "checkpoint" | "failed" | "stalled"
        self.response = response       # Final text to send to user
        self.needs_checkpoint = needs_checkpoint
        self.checkpoint_reason = checkpoint_reason


async def process_task(task_description: str) -> TaskResult:
    """
    Main entry point: process a task end-to-end.

    1. Create task in DB
    2. Classify → pick model
    3. Build context
    4. Run agentic loop (Claude ↔ tools)
    5. Summarize and store
    6. Return result
    """
    # 1. Create task
    task = await db.create_task(task_description, max_steps=MAX_STEPS_PER_TASK)
    task_id = task["id"]
    await db.update_task(task_id, status="classifying")

    # 2. Classify
    model, tier, max_input, max_output = await classify_task(task_description)
    await db.update_task(task_id, status="in_progress", model=model)

    # 3. Build context
    keywords = extract_keywords(task_description)
    system_prompt = await build_system_prompt(tools_description=get_tools_description())
    messages = await build_messages(task_description, relevant_keywords=keywords)

    # 4. Agentic loop
    step = 0
    final_response = ""

    try:
        while step < MAX_STEPS_PER_TASK:
            step += 1
            await db.update_task(task_id, step_count=step)

            # Check cost limits
            current_task = await db.get_task(task_id)
            if current_task and current_task["token_cost"] > COST_LIMIT_PER_TASK:
                await db.update_task(task_id, status="stalled", error="Cost limit exceeded")
                return TaskResult(
                    task_id, "stalled",
                    f"⚠️ Task halted — cost limit (${COST_LIMIT_PER_TASK}) exceeded. Spent ${current_task['token_cost']:.4f} so far.",
                )

            daily_cost = await db.get_daily_cost()
            if daily_cost > COST_LIMIT_DAILY:
                await db.update_task(task_id, status="stalled", error="Daily cost limit exceeded")
                return TaskResult(
                    task_id, "stalled",
                    f"⚠️ Daily budget limit (${COST_LIMIT_DAILY}) reached. Total today: ${daily_cost:.4f}.",
                )

            # Check if we should checkpoint (approaching step limit)
            if step >= MAX_STEPS_PER_TASK * CHECKPOINT_STEP_RATIO:
                await db.update_task(task_id, status="checkpoint")
                return TaskResult(
                    task_id, "checkpoint",
                    final_response or "Task is taking many steps.",
                    needs_checkpoint=True,
                    checkpoint_reason=f"Approaching step limit ({step}/{MAX_STEPS_PER_TASK})",
                )

            # Call Claude
            response = await client.messages.create(
                model=model,
                max_tokens=max_output,
                system=system_prompt,
                messages=messages,
                tools=ALL_TOOLS,
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

            # Collect text response so far
            if text_parts:
                final_response = "\n".join(text_parts)

            # If no tool calls, we're done
            if response.stop_reason == "end_turn" or not tool_uses:
                break

            # Execute tool calls and continue the loop
            # Add assistant message to history
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and collect results
            tool_results = []
            for tool_use in tool_uses:
                result = await execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})

            # Check for uncertainty markers → checkpoint
            if final_response and _should_checkpoint(final_response, task_description):
                await db.update_task(task_id, status="checkpoint")
                return TaskResult(
                    task_id, "checkpoint",
                    final_response,
                    needs_checkpoint=True,
                    checkpoint_reason="Claude expressed uncertainty",
                )

        # 5. Task completed — summarize and store
        await db.update_task(task_id, status="completed", result=final_response[:1000])

        # Generate and store summary
        summary = {
            "description": task_description[:200],
            "result": final_response[:300] if final_response else "No text output",
            "model": model,
            "steps": step,
        }
        tags = keywords
        await db.save_session_memory(task_id, summary, tags)

        return TaskResult(task_id, "completed", final_response)

    except Exception as e:
        error_msg = str(e)
        await db.update_task(task_id, status="failed", error=error_msg)
        return TaskResult(task_id, "failed", f"❌ Task failed: {error_msg}")


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
        f"📊 **Status**\n"
        f"Queue: {queued} | Active: {in_progress}\n"
        f"Today: ${daily:.4f} | Month: ${monthly:.4f}"
    )


async def recover_stale_tasks() -> list[str]:
    """Find and handle tasks stuck in 'in_progress' (crash recovery)."""
    stale = await db.get_stale_tasks()
    messages = []
    for task in stale:
        await db.update_task(task["id"], status="failed", error="Recovered after restart — was in_progress")
        messages.append(f"🔄 Recovered stale task `{task['id']}`: {task['description'][:80]}")
    return messages
