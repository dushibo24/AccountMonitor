#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code PreToolUse hook：禁止 AI 访问 auth.json（内含密钥）。

从 stdin 读取 hook 输入 JSON，命中 auth.json 时以退出码 2 阻止工具调用。
auth.example.json 不受影响。
"""
import json
import shlex
import sys

BLOCKED = "auth.json"
ALLOWED = "auth.example.json"


def deny(target):
    print(f"已阻止：{BLOCKED} 内含密钥，禁止访问（{target}）", file=sys.stderr)
    sys.exit(2)


def is_auth_json(path):
    p = (path or "").rstrip("/")
    return p.endswith(BLOCKED) and not p.endswith(ALLOWED)


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {})

    if tool in ("Read", "Edit", "Write", "MultiEdit"):
        if is_auth_json(ti.get("file_path")):
            deny(ti.get("file_path"))
    elif tool == "NotebookEdit":
        if is_auth_json(ti.get("notebook_path")):
            deny(ti.get("notebook_path"))
    elif tool == "Bash":
        cmd = ti.get("command", "")
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()
        for tok in tokens:
            if is_auth_json(tok):
                deny(cmd)


if __name__ == "__main__":
    main()
