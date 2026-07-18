from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

_FORBIDDEN_SHELL_CHARS = set(";&|><`$\n\r")
_ALLOWED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "pytest"),
    ("pytest",),
    ("python", "-m", "compileall"),
    ("ruff", "check"),
    ("ruff", "format", "--check"),
)
_FILE_PATH_KEYS = ("file_path", "path")


def is_allowed_test_command(command: str) -> bool:
    if not command.strip() or any(char in command for char in _FORBIDDEN_SHELL_CHARS):
        return False
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    for token in tokens:
        if token == ".." or token.startswith("../") or token.startswith("/"):
            return False
        if "=/" in token or "=../" in token:
            return False
    return any(tuple(tokens[: len(prefix)]) == prefix for prefix in _ALLOWED_COMMAND_PREFIXES)


def _path_is_inside_workspace(raw_path: str, workspace: Path) -> bool:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        candidate.resolve().relative_to(workspace.resolve())
    except ValueError:
        return False
    return True


def build_pre_tool_hook(workspace: Path):
    async def pre_tool_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        del tool_use_id, context
        tool_name = str(input_data.get("tool_name", ""))
        tool_input = dict(input_data.get("tool_input") or {})

        if tool_name == "Bash":
            if tool_input.get("dangerouslyDisableSandbox"):
                return _deny("不允许执行未经过沙箱保护的命令。")
            command = str(tool_input.get("command", ""))
            if not is_allowed_test_command(command):
                return _deny(
                    "仅允许执行 pytest、compileall 和 ruff 验证命令。"
                )

        if tool_name in {"Read", "Edit", "Write", "Glob", "Grep"}:
            for key in _FILE_PATH_KEYS:
                raw_path = tool_input.get(key)
                if raw_path and not _path_is_inside_workspace(str(raw_path), workspace):
                    return _deny("禁止访问隔离工作区之外的文件。")

        return {}

    return pre_tool_hook


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
