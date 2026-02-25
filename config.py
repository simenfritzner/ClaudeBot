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

# === Token Budgets (per API call) ===
MAX_INPUT_TOKENS = {
    "route":    500,
    "simple":   2_000,
    "standard": 8_000,
    "complex":  12_000,
}
MAX_OUTPUT_TOKENS = {
    "route":    100,
    "simple":   500,
    "standard": 2_000,
    "complex":  4_000,
}

# === Cost Tracking ===
# Pricing per million tokens (USD)
PRICING = {
    MODEL_HAIKU:  {"input": 0.80, "output": 4.00},
    MODEL_SONNET: {"input": 3.00, "output": 15.00},
}

COST_LIMIT_PER_TASK = 0.75      # USD — halt task if exceeded
COST_LIMIT_DAILY = 2.00         # USD — warn user if exceeded
COST_LIMIT_MONTHLY = 30.00      # USD — hard stop

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

# === System Prompt ===
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
