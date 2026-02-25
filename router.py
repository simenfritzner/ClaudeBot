"""
Thesis Bot — Router
Classifies tasks and selects the appropriate model (Haiku vs Sonnet).
"""
import anthropic

from config import (
    ANTHROPIC_API_KEY,
    MODEL_HAIKU,
    MODEL_SONNET,
    MODEL_SONNET_LATEST,
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    PRICING,
)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

ROUTER_PROMPT = """Classify this task into exactly one category. Respond with ONLY the category name, nothing else.

HAIKU — file reads, status checks, simple formatting, short summaries, listing files, simple questions
SONNET — thesis writing, analysis, experiment design, code debugging, multi-step reasoning, literature review, data interpretation, explainable AI analysis

Task: {task_description}"""


async def classify_task(
    description: str,
    force_model: str | None = None,
) -> tuple[str, str, int, int]:
    """
    Classify a task and return (model, tier, max_input, max_output).
    Uses Haiku for the classification itself.

    Args:
        description: Task description to classify
        force_model: Optional model override — skip classification entirely

    Returns:
        model: The model string to use
        tier: 'simple' | 'standard' | 'complex'
        max_input: Max input tokens for the task
        max_output: Max output tokens for the task
    """
    # Direct model override (used by orchestrator for planners/forced models)
    if force_model:
        if force_model == MODEL_HAIKU:
            return MODEL_HAIKU, "simple", MAX_INPUT_TOKENS["simple"], MAX_OUTPUT_TOKENS["simple"]
        return force_model, "complex", MAX_INPUT_TOKENS["complex"], MAX_OUTPUT_TOKENS["complex"]

    # Check for user overrides in description
    lower = description.lower()
    if lower.startswith("!sonnet"):
        description = description[7:].strip()
        return MODEL_SONNET, "complex", MAX_INPUT_TOKENS["complex"], MAX_OUTPUT_TOKENS["complex"]
    if lower.startswith("!haiku"):
        description = description[6:].strip()
        return MODEL_HAIKU, "simple", MAX_INPUT_TOKENS["simple"], MAX_OUTPUT_TOKENS["simple"]

    try:
        response = await client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=MAX_OUTPUT_TOKENS["route"],
            messages=[{
                "role": "user",
                "content": ROUTER_PROMPT.format(task_description=description),
            }],
        )

        classification = response.content[0].text.strip().upper()

        if "HAIKU" in classification:
            return MODEL_HAIKU, "simple", MAX_INPUT_TOKENS["simple"], MAX_OUTPUT_TOKENS["simple"]
        else:
            # Default to Sonnet for anything non-trivial
            if len(description) > 500 or any(kw in lower for kw in ["write", "analyze", "design", "debug", "compare", "explain"]):
                return MODEL_SONNET, "complex", MAX_INPUT_TOKENS["complex"], MAX_OUTPUT_TOKENS["complex"]
            return MODEL_SONNET, "standard", MAX_INPUT_TOKENS["standard"], MAX_OUTPUT_TOKENS["standard"]

    except Exception as e:
        # If routing fails, default to Sonnet standard (safe fallback)
        print(f"Router error: {e}, defaulting to Sonnet")
        return MODEL_SONNET, "standard", MAX_INPUT_TOKENS["standard"], MAX_OUTPUT_TOKENS["standard"]


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for an API call."""
    pricing = PRICING.get(model, PRICING[MODEL_SONNET])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
