"""Pluggable external AI bots directory and loader for AbyssWhalen Tank Trouble."""

from bots.loader import BotEntry, discover_bots, safe_run_bot

__all__ = ["BotEntry", "discover_bots", "safe_run_bot"]
