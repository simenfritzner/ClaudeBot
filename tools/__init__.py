"""
Thesis Bot — Tools
Tool definitions for Claude's tool use and their implementations.
"""
from tools.file_ops import FILE_TOOLS, handle_file_tool
from tools.scripts import SCRIPT_TOOLS, handle_script_tool

# All tool definitions (sent to Claude)
ALL_TOOLS = FILE_TOOLS + SCRIPT_TOOLS

# Tool name → handler mapping
TOOL_HANDLERS = {}
for tool in FILE_TOOLS:
    TOOL_HANDLERS[tool["name"]] = handle_file_tool
for tool in SCRIPT_TOOLS:
    TOOL_HANDLERS[tool["name"]] = handle_script_tool


async def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool by name and return the result as a string."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return f"Error: Unknown tool '{name}'"
    try:
        result = await handler(name, input_data)
        # Truncate long outputs
        if len(result) > 8000:
            return result[:7500] + f"\n\n... [truncated, {len(result)} chars total]"
        return result
    except Exception as e:
        return f"Error executing {name}: {str(e)}"


def get_tools_description() -> str:
    """Get a human-readable description of available tools."""
    lines = []
    for tool in ALL_TOOLS:
        lines.append(f"- {tool['name']}: {tool['description']}")
    return "\n".join(lines)
