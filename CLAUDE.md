# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autonomous Discord bot that assists with thesis research tasks. Users submit natural language tasks in a `#commands` channel; the bot classifies them, selects an appropriate Claude model, and runs an agentic loop where Claude can read/write thesis files, execute scripts, and search a knowledge base — all with cost tracking and user checkpoints.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot directly
python bot.py

# macOS service management
./service.sh install    # install LaunchAgent (auto-start on login)
./service.sh start|stop|restart|status
./service.sh logs       # view logs
./service.sh follow     # tail -f logs
```

Requires a `.env` file with `DISCORD_TOKEN`, `ANTHROPIC_API_KEY`, and optionally `THESIS_DIR`, `HPC_HOST`, `HPC_USER`, `HPC_KEY_PATH`.

## Architecture

**Request flow:** Discord message → `bot.py` → `orchestrator.process_task()` → router classifies → context builds system prompt with memories → agentic loop (up to 10 steps) with tool calls → result posted back to Discord.

**Key modules:**

- **`bot.py`** — Discord event handlers, message formatting, emoji reactions for status, heartbeat task
- **`orchestrator.py`** — Core agentic loop: sends messages to Claude, processes tool calls, enforces step/cost limits, checkpoint logic (triggers at 70% steps or on uncertainty markers)
- **`router.py`** — Classifies tasks via Haiku to select model tier (Haiku for simple, Sonnet for complex). Users can override with `!haiku`/`!sonnet` prefix. Calculates per-call costs.
- **`config.py`** — All constants: model IDs, token budgets per tier, pricing, cost limits (per-task $0.75, daily $2.00, monthly $30.00), Discord channel names, system prompt template
- **`context.py`** — Three-tier memory system (session + long-term + keyword search). Builds system prompt with dynamic tool injection and memory context.
- **`db.py`** — Async SQLite via aiosqlite. Auto-creates schema on init. Tables: tasks, cost_log, session_memory, long_term_memory. Task IDs are timestamp-based (`t_YYYYMMDD_HHMMSS`).
- **`tools/__init__.py`** — Tool registry and dispatcher. Maps tool names to handlers, provides JSON schema definitions for Anthropic tool format.
- **`tools/file_ops.py`** — File read/write/edit/list/search, paths resolved relative to `THESIS_DIR`
- **`tools/scripts.py`** — Python/shell execution with timeouts, output capture, dangerous command blocking

**Patterns:**
- Fully async (`asyncio`/`aiosqlite`/`AsyncAnthropic`) — no blocking calls in the event loop
- Tool outputs truncated at 8000 chars
- Discord messages split at 2000-char limit; long content uses embeds
- Cost logged per API call with daily/monthly aggregation via ISO timestamp prefix matching
