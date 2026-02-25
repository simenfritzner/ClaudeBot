"""
Thesis Bot — Context Manager
Assembles context for each API call from the three-tier memory system.
"""
import json
from config import (
    SYSTEM_PROMPT,
    MAX_SESSION_MEMORIES_INJECTED,
    MAX_LONGTERM_MEMORIES_INJECTED,
    THESIS_DIR,
)
import db


def _format_memory(mem: dict) -> str:
    """Format a memory row into a concise string."""
    try:
        summary = json.loads(mem["summary"])
        if isinstance(summary, dict):
            desc = summary.get("description", "")
            result = summary.get("result", "")
            return f"- {desc}: {result}"
        return f"- {summary}"
    except (json.JSONDecodeError, TypeError):
        return f"- {mem.get('summary', '')}"


async def build_system_prompt(tools_description: str = "") -> str:
    """Build the system prompt with injected context."""
    # Get recent session memories
    recent = await db.get_recent_session_memories(limit=MAX_SESSION_MEMORIES_INJECTED)
    recent_text = "\n".join(_format_memory(m) for m in recent) if recent else "No recent tasks."

    # Thesis state (could be expanded to read from a state file)
    thesis_state = "No thesis state loaded yet."

    return SYSTEM_PROMPT.format(
        tools=tools_description or "Standard tools available.",
        thesis_state=thesis_state,
        recent_context=recent_text,
    )


async def build_messages(
    task_description: str,
    conversation_history: list[dict] | None = None,
    relevant_keywords: list[str] | None = None,
) -> list[dict]:
    """
    Build the messages array for an API call.

    Args:
        task_description: The current task/user message
        conversation_history: Optional ongoing conversation for multi-step tasks
        relevant_keywords: Optional keywords to search long-term memory
    """
    messages = []

    # Inject relevant long-term memories if keywords provided
    if relevant_keywords:
        memories = await db.search_memories(relevant_keywords, limit=MAX_LONGTERM_MEMORIES_INJECTED)
        if memories:
            context = "Relevant context from past work:\n"
            context += "\n".join(_format_memory(m) for m in memories)
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "Understood, I'll keep that context in mind."})

    # Add conversation history (for multi-step tasks)
    if conversation_history:
        messages.extend(conversation_history)

    # Add the current task
    messages.append({"role": "user", "content": task_description})

    return messages


def extract_keywords(text: str) -> list[str]:
    """Extract simple keywords from text for memory search."""
    # Basic keyword extraction — skip common words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "about", "between",
        "through", "after", "before", "during", "without", "it", "its",
        "this", "that", "these", "those", "i", "you", "he", "she", "we",
        "they", "my", "your", "his", "her", "our", "their", "me", "him",
        "and", "or", "but", "not", "so", "if", "then", "than", "also",
        "just", "please", "help", "want", "need", "make", "get", "run",
    }
    words = text.lower().split()
    keywords = [w.strip(".,!?;:'\"()[]{}") for w in words if len(w) > 2 and w.lower() not in stop_words]
    # Return unique keywords, max 5
    seen = set()
    result = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
        if len(result) >= 5:
            break
    return result
