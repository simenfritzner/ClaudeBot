"""
Script execution tools for the thesis bot.
Runs Python scripts and shell commands with timeout and output capture.
"""
import asyncio
import os
import tempfile
from config import THESIS_DIR

SCRIPT_TOOLS = [
    {
        "name": "run_python",
        "description": "Execute a Python code snippet. Has access to numpy, pandas, scipy, scikit-learn, shap, matplotlib, seaborn. Working directory is the thesis directory. Plots are saved to files (use plt.savefig), not displayed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default: 120.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_script",
        "description": "Execute an existing Python script file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the Python script (relative to thesis directory or absolute).",
                },
                "args": {
                    "type": "string",
                    "description": "Command-line arguments to pass to the script.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default: 300.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_shell",
        "description": "Execute a shell command. Use for simple operations like checking disk space, listing processes, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default: 30.",
                },
            },
            "required": ["command"],
        },
    },
]


async def handle_script_tool(name: str, input_data: dict) -> str:
    """Handle script execution tools."""

    if name == "run_python":
        code = input_data["code"]
        timeout = input_data.get("timeout", 120)

        # Write code to a temp file and execute it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=THESIS_DIR) as f:
            # Add common imports preamble
            preamble = "import os; os.chdir(os.environ.get('THESIS_DIR', '.'))\n"
            f.write(preamble + code)
            script_path = f.name

        try:
            env = os.environ.copy()
            env["THESIS_DIR"] = THESIS_DIR
            process = await asyncio.create_subprocess_exec(
                "python3", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=THESIS_DIR,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return f"⏱️ Script timed out after {timeout}s"

            result_parts = []
            if stdout:
                out = stdout.decode(errors="replace")
                result_parts.append(f"STDOUT:\n{out}")
            if stderr:
                err = stderr.decode(errors="replace")
                result_parts.append(f"STDERR:\n{err}")
            if process.returncode != 0:
                result_parts.append(f"Exit code: {process.returncode}")

            return "\n".join(result_parts) if result_parts else "Script completed successfully (no output)."
        finally:
            os.unlink(script_path)

    elif name == "run_script":
        path = input_data["path"]
        if not os.path.isabs(path):
            path = os.path.join(THESIS_DIR, path)
        if not os.path.exists(path):
            return f"Script not found: {path}"

        args_str = input_data.get("args", "")
        timeout = input_data.get("timeout", 300)

        cmd = ["python3", path]
        if args_str:
            cmd.extend(args_str.split())

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=THESIS_DIR,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return f"⏱️ Script timed out after {timeout}s"

        result_parts = []
        if stdout:
            result_parts.append(f"STDOUT:\n{stdout.decode(errors='replace')}")
        if stderr:
            result_parts.append(f"STDERR:\n{stderr.decode(errors='replace')}")
        if process.returncode != 0:
            result_parts.append(f"Exit code: {process.returncode}")

        return "\n".join(result_parts) if result_parts else "Script completed (no output)."

    elif name == "run_shell":
        command = input_data["command"]
        timeout = input_data.get("timeout", 30)

        # Block dangerous commands
        dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/", ":(){ :|:& };:"]
        if any(d in command for d in dangerous):
            return "❌ Blocked: potentially dangerous command."

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=THESIS_DIR,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return f"⏱️ Command timed out after {timeout}s"

        result_parts = []
        if stdout:
            result_parts.append(stdout.decode(errors="replace"))
        if stderr:
            result_parts.append(f"STDERR: {stderr.decode(errors='replace')}")

        return "\n".join(result_parts) if result_parts else "Command completed (no output)."

    return f"Unknown script tool: {name}"
