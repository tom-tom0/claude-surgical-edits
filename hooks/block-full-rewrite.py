#!/usr/bin/env python3
"""PreToolUse hook: block full-file rewrites via Write when Edit would be cheaper.

Denies a Write to an existing file when most of its lines would be retyped
unchanged, steering the model to targeted Edit calls instead. Fails open on
any error so it never blocks legitimate writes.
"""
import difflib
import json
import os
import sys
from collections import Counter

# A rewrite is only "wasteful" when a meaningful amount of unchanged text
# would be retyped, and when most of the file is staying the same.
MIN_UNCHANGED_LINES = 20
MIN_UNCHANGED_FRACTION = 0.5
# Read guard only (checked via stat before opening): don't slurp truly huge
# files into memory. No source file approaches this; a denial needs the new
# content to contain >=50% of the old lines anyway, and tool output caps
# keep new content under ~1MB, so nothing this large can ever be denied.
MAX_BYTES = 32 * 1024 * 1024
# difflib's worst case (heavily interleaved changes) is quadratic: ~1.6s at
# 5k lines but ~26s at 20k — past the hook timeout. Up to this size the
# exact diff runs; above it, an O(n) multiset estimate decides instead.
EXACT_DIFF_MAX_LINES = 5000


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Write":
        return
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path")
    new_content = tool_input.get("content")
    if not path or new_content is None:
        return
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return  # don't slurp truly huge files; nothing this big can be denied
        # newline="" preserves CRLF/LF so line-ending changes are compared
        # faithfully instead of being translated away on read.
        with open(path, "r", encoding="utf-8", newline="") as f:
            old_content = f.read()
    except (OSError, UnicodeDecodeError):
        return  # new file, unreadable, or binary: allow
    # keepends=True so a pure line-ending conversion (CRLF -> LF) counts as
    # changing every line and is allowed through.
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    if len(old_lines) < MIN_UNCHANGED_LINES:
        return  # short file: rewriting it is cheap
    # Only substantive lines count as wasteful retyping. Blank lines and
    # lone braces/brackets (<= 3 chars stripped) cost ~1 token each and
    # survive genuine rewrites (a CSS/JS overhaul keeps every "}" and blank
    # separator) — counting them causes false blocks on real rewrites.
    def substantive(line):
        return len(line.strip()) > 3
    old_meaningful = sum(1 for l in old_lines if substantive(l))
    if old_meaningful < MIN_UNCHANGED_LINES:
        return  # mostly-trivial file: nothing meaningful to waste
    # Unchanged lines can never exceed the new content's line count, so if
    # the new content is under half the old file, the fraction test can
    # never pass — allow instantly, whatever the file's size.
    if len(new_lines) < MIN_UNCHANGED_FRACTION * len(old_lines):
        return
    # O(n) prescreen: the multiset intersection of substantive lines is an
    # upper bound on the ordered unchanged count. If even the upper bound is
    # under the thresholds, no exact diff could deny — allow without
    # diffing. This fast-paths genuine rewrites at any size.
    old_counts = Counter(l for l in old_lines if substantive(l))
    new_counts = Counter(l for l in new_lines if substantive(l))
    upper_bound = sum((old_counts & new_counts).values())
    if upper_bound < MIN_UNCHANGED_LINES:
        return
    if upper_bound / old_meaningful < MIN_UNCHANGED_FRACTION:
        return  # most of the file is actually changing: a rewrite is fine
    if len(old_lines) <= EXACT_DIFF_MAX_LINES and len(new_lines) <= EXACT_DIFF_MAX_LINES:
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        unchanged = sum(
            1
            for block in matcher.get_matching_blocks()
            for line in old_lines[block.a:block.a + block.size]
            if substantive(line)
        )
        if unchanged < MIN_UNCHANGED_LINES:
            return
        if unchanged / old_meaningful < MIN_UNCHANGED_FRACTION:
            return
    else:
        # Too large for the exact diff's quadratic worst case. Use the
        # multiset bound: it over-counts only when lines are reordered, and
        # retyping thousands of identical lines in a new order is still a
        # wasteful rewrite — Edit handles moves too.
        unchanged = upper_bound
    changed = max(1, old_meaningful - unchanged)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked wasteful full-file rewrite: this Write retypes {unchanged} of "
                f"{old_meaningful} substantive lines unchanged (only ~{changed} lines differ). "
                "Rewriting the whole file wastes output tokens and time. Use the Edit tool "
                "instead, with targeted old_string/new_string replacements covering only the "
                "parts that change (multiple Edit calls are fine). Do not retry this Write."
            ),
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: never block a write because the hook itself broke
