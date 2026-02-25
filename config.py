"""
Thesis Bot — Configuration
All tuneable parameters in one place.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# === Secrets ===
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
HPC_HOST = os.getenv("HPC_HOST", "")
HPC_USER = os.getenv("HPC_USER", "")
HPC_KEY_PATH = os.getenv("HPC_KEY_PATH", "~/.ssh/hpc_key")

# === Discord Channel Names ===
# The bot will look for these channels in your server.
# Create them in Discord before running.
CHANNEL_COMMANDS = "commands"
CHANNEL_STATUS = "status"
CHANNEL_OUTPUT = "output"
CHANNEL_ERRORS = "errors"
CHANNEL_EXPERIMENTS = "experiments"
CHANNEL_SLURM = "slurm"

# === Model Configuration ===
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_SONNET_LATEST = "claude-sonnet-4-6"   # for planning/decomposition

# === Token Budgets (per API call) ===
MAX_INPUT_TOKENS = {
    "route":    500,
    "simple":   2_000,
    "standard": 8_000,
    "complex":  12_000,
    "planner":  12_000,
}
MAX_OUTPUT_TOKENS = {
    "route":    100,
    "simple":   500,
    "standard": 2_000,
    "complex":  4_000,
    "planner":  4_000,
}

# === Cost Tracking ===
# Pricing per million tokens (USD)
PRICING = {
    MODEL_HAIKU:          {"input": 0.80, "output": 4.00},
    MODEL_SONNET:         {"input": 3.00, "output": 15.00},
    MODEL_SONNET_LATEST:  {"input": 3.00, "output": 15.00},
}

COST_LIMIT_DAILY = 20.00        # USD — safety net
COST_LIMIT_MONTHLY = 100.00     # USD — hard stop

# === Delegation / Recursion ===
MAX_DELEGATION_DEPTH = 3              # 0=root, max nesting = 3
MAX_SUBTASK_BUDGET = 1.00             # USD — max any single subtask can cost
MIN_SUBTASK_BUDGET = 0.01             # USD — floor for subtask budget
MAX_SUBTASKS_PER_TASK = 15            # prevent explosion
PLANNER_RESERVE_BUDGET = 0.10         # USD — planner reserves this for its own calls
DEFAULT_TASK_BUDGET = 1.00            # USD — default when user doesn't specify $N
MAX_TASK_BUDGET = 20.00               # USD — hard ceiling no user can exceed
CONTEXT_FILE_MAX_LINES = 100          # lines read when injecting context files

# Per-depth step limits
STEPS_BY_DEPTH = {0: 20, 1: 10, 2: 6, 3: 3}

# === Task Limits ===
MAX_STEPS_PER_TASK = 10
CHECKPOINT_STEP_RATIO = 0.7     # checkpoint at 70% of max steps

# === Memory ===
MAX_SESSION_MEMORIES_INJECTED = 2
MAX_LONGTERM_MEMORIES_INJECTED = 3
SUMMARY_MAX_TOKENS = 200

# === Heartbeat ===
HEARTBEAT_INTERVAL_SECONDS = 300  # 5 minutes

# === Paths ===
# Project root = wherever this file lives (i.e. the ClaudeBot repo)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(PROJECT_ROOT, "data", "bot.db")
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

# Thesis data directory — set in .env to point at your actual data
# e.g. THESIS_DIR=/Users/simenfritzner/path/to/your/data
THESIS_DIR = os.environ.get("THESIS_DIR", os.path.join(PROJECT_ROOT, "thesis-data"))

# === System Prompts ===

SYSTEM_PROMPT = """You are a research assistant helping with a master's thesis. You run as an autonomous agent with access to thesis files, data processing tools, and an HPC cluster.

RULES:
- Be concise. You're in an agentic loop — every token costs money.
- When uncertain, say so explicitly. The orchestrator will ask the user.
- Never hallucinate citations. Use search tools to find real papers.
- When writing thesis content, match the existing style and voice.
- Report what you did, not what you could do.
- For data tasks: describe your approach, then execute. Show key results inline.

AVAILABLE TOOLS:
{tools}

CURRENT THESIS STATE:
{thesis_state}

RECENT CONTEXT:
{recent_context}"""

PLANNER_SYSTEM_PROMPT = """You are a task planner for a thesis research assistant. Your job is to decompose a high-level goal into focused, self-contained subtasks using the `delegate_task` tool.

RULES:
- First, briefly outline your plan as text. Then execute it by calling delegate_task for each subtask.
- Each subtask MUST be self-contained: include all file paths, section names, and requirements. The sub-agent knows nothing about this conversation.
- Prefer many small tasks over few large ones — small tasks are cheaper and more reliable.
- Allocate budgets wisely. Reads: $0.03-0.05. Analysis: $0.10-0.20. Writing: $0.30-0.50.
- After all subtasks complete, synthesize results concisely.
- Total budget: ${budget}. Reserve ${reserve} for your own planning calls.
- Do NOT do the work yourself. Delegate everything via delegate_task.

AVAILABLE TOOLS:
{tools}"""

WORKER_SYSTEM_PROMPT = """You are a thesis research assistant. Complete the assigned task directly and concisely. Every token costs money.

RULES:
- Report what you did, not what you could do.
- No user interaction available — proceed with best judgment when uncertain.
- Budget: ${budget}.

AVAILABLE TOOLS:
{tools}"""
