"""
Thesis Bot — Discord Interface
Handles all Discord communication, routes messages to the orchestrator,
and manages heartbeats and status updates.
"""
import os
import asyncio
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

import db
from config import (
    DISCORD_TOKEN,
    CHANNEL_COMMANDS,
    CHANNEL_STATUS,
    CHANNEL_OUTPUT,
    CHANNEL_ERRORS,
    HEARTBEAT_INTERVAL_SECONDS,
)
from orchestrator import process_task, get_status, recover_stale_tasks

# === Bot Setup ===

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Channel cache (populated on_ready)
channels = {}


def _get_channel(name: str) -> discord.TextChannel | None:
    return channels.get(name)


async def _send_to_channel(channel_name: str, content: str):
    """Send a message to a named channel, splitting if too long."""
    ch = _get_channel(channel_name)
    if not ch:
        print(f"Warning: channel #{channel_name} not found")
        return
    # Discord has 2000 char limit
    while content:
        chunk = content[:1990]
        content = content[1990:]
        await ch.send(chunk)


# === Events ===

@bot.event
async def on_ready():
    """Called when bot connects to Discord."""
    print(f"✅ {bot.user} is online")

    # Initialize database
    await db.init_db()

    # Cache channel references
    for guild in bot.guilds:
        for channel in guild.text_channels:
            channels[channel.name] = channel
            
    print(f"Found channels: {list(channels.keys())}")
    # Crash recovery
    recovered = await recover_stale_tasks()
    if recovered:
        for msg in recovered:
            await _send_to_channel(CHANNEL_ERRORS, msg)
        await _send_to_channel(CHANNEL_STATUS, f"🔄 Bot restarted. Recovered {len(recovered)} stale task(s).")
    else:
        await _send_to_channel(CHANNEL_STATUS, "🟢 Bot online. No stale tasks found.")

    # Start heartbeat
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore own messages
    if message.author == bot.user:
        return

    # Process commands first (like !status, !cost)
    await bot.process_commands(message)

    # Only respond to messages in #commands or DMs that aren't commands
    is_command_channel = message.channel.name == CHANNEL_COMMANDS if hasattr(message.channel, "name") else False
    is_dm = isinstance(message.channel, discord.DMChannel)

    if not (is_command_channel or is_dm):
        return

    # Skip if it was a bot command (starts with !)
    if message.content.startswith("!"):
        return

    # This is a task — process it
    task_description = message.content.strip()
    if not task_description:
        return

    # Acknowledge
    await message.add_reaction("🔄")

    # Process the task
    result = await process_task(task_description)

    # Remove processing reaction
    try:
        await message.remove_reaction("🔄", bot.user)
    except discord.errors.NotFound:
        pass

    # Handle result
    if result.status == "completed":
        await message.add_reaction("✅")
        # Send response in the same channel
        await _send_long_message(message.channel, result.response)

    elif result.status == "checkpoint":
        await message.add_reaction("⏸️")
        checkpoint_msg = f"🔔 **Checkpoint** ({result.checkpoint_reason})\n\n{result.response}\n\n→ Reply to continue, or react ❌ to cancel."
        await message.reply(checkpoint_msg)

    elif result.status == "failed":
        await message.add_reaction("❌")
        await message.reply(result.response)
        await _send_to_channel(CHANNEL_ERRORS, f"Task `{result.task_id}` failed:\n{result.response}")

    elif result.status == "stalled":
        await message.add_reaction("⚠️")
        await message.reply(result.response)


async def _send_long_message(channel, content: str):
    """Send a message, splitting into chunks if needed. Uses embeds for long content."""
    if not content:
        await channel.send("✅ Task completed (no text output).")
        return

    if len(content) <= 1990:
        await channel.send(content)
    elif len(content) <= 4000:
        # Use an embed for medium-length content
        embed = discord.Embed(description=content[:4096], color=0x2ECC71)
        await channel.send(embed=embed)
    else:
        # Split into multiple messages
        chunks = [content[i:i+1990] for i in range(0, len(content), 1990)]
        for i, chunk in enumerate(chunks):
            prefix = f"**[{i+1}/{len(chunks)}]**\n" if len(chunks) > 1 else ""
            await channel.send(prefix + chunk)


# === Commands ===

@bot.command(name="status")
async def cmd_status(ctx):
    """Show bot status, task queue, and budget."""
    status = await get_status()
    await ctx.send(status)


@bot.command(name="cost")
async def cmd_cost(ctx):
    """Show cost breakdown."""
    daily = await db.get_daily_cost()
    monthly = await db.get_monthly_cost()
    await ctx.send(
        f"💰 **Cost Report**\n"
        f"Today: ${daily:.4f}\n"
        f"This month: ${monthly:.4f}"
    )


@bot.command(name="tasks")
async def cmd_tasks(ctx):
    """Show active tasks."""
    active = await db.get_active_tasks()
    if not active:
        await ctx.send("No active tasks.")
        return
    lines = []
    for t in active:
        lines.append(f"`{t['id']}` [{t['status']}] {t['description'][:60]}")
    await ctx.send("📋 **Active Tasks**\n" + "\n".join(lines))


@bot.command(name="ping")
async def cmd_ping(ctx):
    """Check bot latency."""
    await ctx.send(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")


@bot.command(name="help_bot")
async def cmd_help_bot(ctx):
    """Show help."""
    help_text = """**Thesis Bot — Commands**

**Just type naturally** in #commands or DMs to give tasks:
> "Summarize chapter 3"
> "Run FFT analysis on data/signal.csv"
> "Write the methodology section"

**Prefix commands:**
`!status` — Bot status and budget
`!cost` — Cost breakdown
`!tasks` — Active task queue
`!ping` — Check latency
`!help_bot` — This message

**Modifiers:**
`!sonnet <task>` — Force Sonnet model
`!haiku <task>` — Force Haiku model
`!auto <task>` — Run without checkpoints
"""
    embed = discord.Embed(description=help_text, color=0x3498DB)
    await ctx.send(embed=embed)


# === Heartbeat ===

@tasks.loop(seconds=HEARTBEAT_INTERVAL_SECONDS)
async def heartbeat_loop():
    """Periodic heartbeat to #status."""
    try:
        active = await db.get_active_tasks()
        daily = await db.get_daily_cost()
        queued = sum(1 for t in active if t["status"] == "queued")
        in_progress = sum(1 for t in active if t["status"] == "in_progress")

        await db.log_heartbeat(queued, in_progress, daily)

        status_ch = _get_channel(CHANNEL_STATUS)
        if status_ch:
            await status_ch.send(
                f"🫀 Alive | Queue: {queued} | Active: {in_progress} | Today: ${daily:.4f}"
            )
    except Exception as e:
        print(f"Heartbeat error: {e}")


@heartbeat_loop.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()


# === Entry Point ===

def main():
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN not set in .env")
        return
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
