#!/usr/bin/env python3
"""Installer for claude-surgical-edits.

Copies the hook into ~/.claude/hooks/, merges the PreToolUse registration into
~/.claude/settings.json (preserving everything already there), and appends the
steering instruction to ~/.claude/CLAUDE.md if it is not already present.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOK_CMD = "python3 ~/.claude/hooks/block-full-rewrite.py"
HOOK_ENTRY = {
    "matcher": "Write",
    "hooks": [
        {
            "type": "command",
            "command": HOOK_CMD,
            "timeout": 15,
            "statusMessage": "Checking for wasteful full-file rewrite",
        }
    ],
}
INSTRUCTION = (
    "# File editing efficiency\n\n"
    "The number of tokens used to edit files is best minimized, all else being "
    "equal. Therefore, when it will not affect the end result, surgically edit "
    "a file with the Edit tool (targeted old_string/new_string replacements) "
    "rather than rewriting the entire file with Write. Only use Write for new "
    "files, or when most of the file's content is genuinely changing.\n"
)


def main():
    hooks_dir = os.path.join(CLAUDE_DIR, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    for name in ("block-full-rewrite.py", "test_block_full_rewrite.py",
                 "benchmark_token_savings.py"):
        shutil.copy2(os.path.join(HERE, "hooks", name), os.path.join(hooks_dir, name))
        print(f"copied {name} -> {hooks_dir}/")

    settings_path = os.path.join(CLAUDE_DIR, "settings.json")
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            sys.exit(
                f"error: {settings_path} is not valid JSON ({exc}).\n"
                "Fix or remove it, then re-run install.py. Nothing was changed."
            )
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    already = any(
        h.get("command") == HOOK_CMD
        for entry in pre if isinstance(entry, dict)
        for h in entry.get("hooks", [])
    )
    if already:
        print("hook already registered in settings.json")
    else:
        pre.append(HOOK_ENTRY)
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        print(f"registered hook in {settings_path}")

    claude_md = os.path.join(CLAUDE_DIR, "CLAUDE.md")
    existing = ""
    if os.path.exists(claude_md):
        with open(claude_md) as f:
            existing = f.read()
    if "surgically edit" in existing:
        print("steering instruction already in CLAUDE.md")
    else:
        with open(claude_md, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            if existing.strip():
                f.write("\n")
            f.write(INSTRUCTION)
        print(f"appended steering instruction to {claude_md}")

    print("\nDone. Open /hooks once in Claude Code (or restart it) to load the hook.")


if __name__ == "__main__":
    main()
