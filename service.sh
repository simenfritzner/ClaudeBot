#!/bin/bash
# Thesis Bot — Service Manager
# Usage: ./service.sh [install|start|stop|restart|status|logs|uninstall]

PLIST_NAME="com.simenfritzner.thesisbot"
PLIST_SRC="$(dirname "$0")/com.simenfritzner.thesisbot.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$(dirname "$0")/data/logs"

case "$1" in
    install)
        mkdir -p "$LOG_DIR"
        mkdir -p "$HOME/Library/LaunchAgents"
        cp "$PLIST_SRC" "$PLIST_DST"
        launchctl load "$PLIST_DST"
        echo "✅ Installed and started. Bot will auto-start on login."
        ;;
    start)
        launchctl load "$PLIST_DST" 2>/dev/null
        launchctl start "$PLIST_NAME"
        echo "▶️  Started"
        ;;
    stop)
        launchctl stop "$PLIST_NAME"
        echo "⏹️  Stopped"
        ;;
    restart)
        launchctl stop "$PLIST_NAME"
        sleep 2
        launchctl start "$PLIST_NAME"
        echo "🔄 Restarted"
        ;;
    status)
        if launchctl list | grep -q "$PLIST_NAME"; then
            PID=$(launchctl list | grep "$PLIST_NAME" | awk '{print $1}')
            if [ "$PID" = "-" ]; then
                echo "⚠️  Registered but not running"
            else
                echo "🟢 Running (PID: $PID)"
            fi
        else
            echo "⭕ Not installed"
        fi
        ;;
    logs)
        echo "=== STDOUT (last 30 lines) ==="
        tail -30 "$LOG_DIR/bot-stdout.log" 2>/dev/null || echo "(no logs yet)"
        echo ""
        echo "=== STDERR (last 30 lines) ==="
        tail -30 "$LOG_DIR/bot-stderr.log" 2>/dev/null || echo "(no logs yet)"
        ;;
    follow)
        tail -f "$LOG_DIR/bot-stdout.log" "$LOG_DIR/bot-stderr.log"
        ;;
    uninstall)
        launchctl stop "$PLIST_NAME" 2>/dev/null
        launchctl unload "$PLIST_DST" 2>/dev/null
        rm -f "$PLIST_DST"
        echo "🗑️  Uninstalled. Bot will no longer auto-start."
        ;;
    *)
        echo "Thesis Bot Service Manager"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "  install    Install and start (auto-starts on login)"
        echo "  start      Start the bot"
        echo "  stop       Stop the bot"
        echo "  restart    Restart the bot"
        echo "  status     Check if running"
        echo "  logs       View recent logs"
        echo "  follow     Tail logs in real-time"
        echo "  uninstall  Remove from auto-start"
        ;;
esac
