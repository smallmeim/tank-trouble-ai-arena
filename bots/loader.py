"""Auto-discovery and fault-tolerant execution for AI-written bots in `bots/*.py`."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

BOTS_DIR = Path(__file__).resolve().parent


def _clamp_sign(val: Any) -> int:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0
    if v > 0.25:
        return 1
    if v < -0.25:
        return -1
    return 0


class _FunctionBot:
    def __init__(self, name: str, fn: Callable[[dict[str, Any]], Any]) -> None:
        self.name = name
        self._fn = fn

    def act(self, state: dict[str, Any]) -> Any:
        return self._fn(state)


@dataclass
class BotEntry:
    bot_id: str
    name: str
    file_name: str
    cls_name: str
    author: str
    description: str
    builder: Callable[[], Any]


def _load_module(path: Path) -> Any:
    mod_name = f"gh_tank_bot_{path.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_entry(path: Path) -> BotEntry | None:
    mod = _load_module(path)

    candidates: list[type[Any]] = []
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj.__module__ != mod.__name__:
            continue
        if callable(getattr(obj, "act", None)):
            candidates.append(obj)

    if candidates:
        candidates.sort(key=lambda c: hasattr(c, "name"), reverse=True)
        cls = candidates[0]
        probe = cls()
        display_name = str(getattr(probe, "name", getattr(cls, "name", cls.__name__)))
        author = str(getattr(probe, "author", getattr(mod, "AUTHOR", "AI Coder")))
        doc = inspect.getdoc(cls) or inspect.getdoc(mod) or ""
        desc = doc.splitlines()[0] if doc else ""

        return BotEntry(
            bot_id=f"py:{path.stem}",
            name=display_name,
            file_name=path.name,
            cls_name=cls.__name__,
            author=author,
            description=desc,
            builder=lambda c=cls: c(),
        )

    mod_act = getattr(mod, "act", None)
    if callable(mod_act):
        display_name = str(getattr(mod, "BOT_NAME", getattr(mod, "NAME", path.stem)))
        author = str(getattr(mod, "AUTHOR", "AI Coder"))
        doc = inspect.getdoc(mod) or ""
        desc = doc.splitlines()[0] if doc else ""
        return BotEntry(
            bot_id=f"py:{path.stem}",
            name=display_name,
            file_name=path.name,
            cls_name="act()",
            author=author,
            description=desc,
            builder=lambda fn=mod_act, nm=display_name: _FunctionBot(nm, fn),
        )

    return None


def discover_bots(bots_dir: str | Path | None = None) -> tuple[list[BotEntry], list[tuple[str, str]]]:
    """Return (valid_bot_entries, load_errors) for `bots/*.py`."""
    root = Path(bots_dir) if bots_dir is not None else BOTS_DIR
    if not root.exists():
        return [], []

    entries: list[BotEntry] = []
    errors: list[tuple[str, str]] = []
    seen: set[str] = set()

    for path in sorted(root.glob("*.py")):
        if path.name.startswith("_") or path.name == "loader.py":
            continue
        try:
            entry = _extract_entry(path)
            if entry is None:
                continue
            if entry.name in seen:
                entry.name = f"{entry.name} ({path.stem})"
            seen.add(entry.name)
            entries.append(entry)
        except Exception as exc:
            errors.append((path.name, f"{type(exc).__name__}: {exc}"))

    return entries, errors


def safe_run_bot(bot: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Execute bot.act(state) safely and normalize into {move, turn, fire, special, mode}."""
    try:
        raw = bot.act(state)
        mode = str(getattr(bot, "mode", "Active"))
        move, turn, fire, special = 0, 0, False, False
        if isinstance(raw, (tuple, list)):
            if len(raw) >= 1:
                move = _clamp_sign(raw[0])
            if len(raw) >= 2:
                turn = _clamp_sign(raw[1])
            if len(raw) >= 3:
                fire = bool(raw[2])
            if len(raw) >= 4:
                special = bool(raw[3])
        elif isinstance(raw, dict):
            move = _clamp_sign(raw.get("move", 0))
            turn = _clamp_sign(raw.get("turn", 0))
            fire = bool(raw.get("fire", False))
            special = bool(raw.get("special", False))
        return {
            "move": move,
            "turn": turn,
            "fire": fire,
            "special": special,
            "mode": mode[:24],
            "error": "",
        }
    except Exception as exc:
        return {
            "move": 0,
            "turn": 0,
            "fire": False,
            "special": False,
            "mode": f"Err:{type(exc).__name__}",
            "error": f"{type(exc).__name__}: {exc}",
        }
