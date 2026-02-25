"""
File operation tools for the thesis bot.
"""
import os
import glob
from config import THESIS_DIR

FILE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns first 200 lines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the thesis directory, or absolute path.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start reading from this line (1-indexed). Default: 1.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Read up to this line. Default: 200.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates directories if needed. Overwrites existing files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the thesis directory.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace a specific string in a file with new content. The old string must appear exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact text to find and replace (must be unique in file).",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory. Returns file names, sizes, and modification times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to thesis directory. Default: root of thesis directory.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py', '*.csv'). Default: all files.",
                },
            },
        },
    },
    {
        "name": "search_files",
        "description": "Search for a text pattern across files in the thesis directory. Returns matching lines with context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Text or regex pattern to search for.",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern for files to search (e.g., '**/*.py'). Default: all files.",
                },
            },
            "required": ["pattern"],
        },
    },
]


def _resolve_path(path: str) -> str:
    """Resolve path relative to thesis directory."""
    if os.path.isabs(path):
        return path
    return os.path.join(THESIS_DIR, path)


async def handle_file_tool(name: str, input_data: dict) -> str:
    """Handle file operation tools."""

    if name == "read_file":
        path = _resolve_path(input_data["path"])
        if not os.path.exists(path):
            return f"File not found: {path}"
        start = input_data.get("start_line", 1) - 1  # convert to 0-indexed
        end = input_data.get("end_line", 200)
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            total = len(lines)
            selected = lines[start:end]
            content = "".join(selected)
            header = f"[{path} — lines {start+1}-{min(end, total)} of {total}]\n"
            return header + content
        except UnicodeDecodeError:
            return f"Cannot read binary file: {path}"

    elif name == "write_file":
        path = _resolve_path(input_data["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(input_data["content"])
        size = os.path.getsize(path)
        return f"Written {size} bytes to {path}"

    elif name == "edit_file":
        path = _resolve_path(input_data["path"])
        if not os.path.exists(path):
            return f"File not found: {path}"
        with open(path, "r") as f:
            content = f.read()
        old_text = input_data["old_text"]
        count = content.count(old_text)
        if count == 0:
            return f"Text not found in {path}"
        if count > 1:
            return f"Text appears {count} times in {path} — must be unique. Provide more context."
        new_content = content.replace(old_text, input_data["new_text"], 1)
        with open(path, "w") as f:
            f.write(new_content)
        return f"Edited {path}: replaced 1 occurrence."

    elif name == "list_files":
        dir_path = _resolve_path(input_data.get("path", ""))
        if not os.path.isdir(dir_path):
            return f"Directory not found: {dir_path}"
        pattern = input_data.get("pattern", "*")
        matches = glob.glob(os.path.join(dir_path, pattern))
        if not matches:
            return f"No files matching '{pattern}' in {dir_path}"
        lines = []
        for m in sorted(matches)[:50]:
            stat = os.stat(m)
            size_kb = stat.st_size / 1024
            name_str = os.path.basename(m)
            if os.path.isdir(m):
                name_str += "/"
            lines.append(f"  {name_str:<40} {size_kb:>8.1f} KB")
        header = f"[{dir_path}] — {len(matches)} items"
        if len(matches) > 50:
            header += f" (showing first 50)"
        return header + "\n" + "\n".join(lines)

    elif name == "search_files":
        import re
        base = THESIS_DIR
        file_pat = input_data.get("file_pattern", "**/*")
        search_pat = input_data["pattern"]
        matches = []
        for filepath in glob.glob(os.path.join(base, file_pat), recursive=True):
            if os.path.isdir(filepath):
                continue
            try:
                with open(filepath, "r") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(search_pat, line, re.IGNORECASE):
                            rel = os.path.relpath(filepath, base)
                            matches.append(f"  {rel}:{i}: {line.rstrip()}")
                            if len(matches) >= 20:
                                break
            except (UnicodeDecodeError, PermissionError):
                continue
            if len(matches) >= 20:
                break
        if not matches:
            return f"No matches for '{search_pat}'"
        return f"Found {len(matches)} matches:\n" + "\n".join(matches)

    return f"Unknown file tool: {name}"
