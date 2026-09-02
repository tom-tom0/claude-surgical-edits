#!/usr/bin/env python3
"""PreToolUse hook: block full-file rewrites via Write when Edit would be cheaper.

Denies a Write to an existing file when most of its lines would be retyped
unchanged, steering the model to targeted Edit calls instead. Fails open on
any error so it never blocks legitimate writes.
"""
import difflib
import json
import sys
from collections import Counter

# A rewrite is only "wasteful" when a meaningful amount of unchanged text
# would be retyped, and when most of the file is staying the same.
MIN_UNCHANGED_LINES = 20
MIN_UNCHANGED_FRACTION = 0.5
# Above this size, even reading/counting lines is not worth it; fail open
# instantly rather than risk burning CPU until the hook timeout.
MAX_LINES = 50000
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
    if len(old_lines) > MAX_LINES or len(new_lines) > MAX_LINES:
        return
    # O(n) prescreen: the multiset intersection is an upper bound on the
    # ordered unchanged-line count. If even the upper bound is under the
    # thresholds, no exact diff could deny — allow without diffing. This
    # fast-paths genuine rewrites at any size.
    upper_bound = sum((Counter(old_lines) & Counter(new_lines)).values())
    if upper_bound < MIN_UNCHANGED_LINES:
        return
    if upper_bound / len(old_lines) < MIN_UNCHANGED_FRACTION:
        return  # most of the file is actually changing: a rewrite is fine
    if len(old_lines) <= EXACT_DIFF_MAX_LINES and len(new_lines) <= EXACT_DIFF_MAX_LINES:
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        unchanged = sum(block.size for block in matcher.get_matching_blocks())
        if unchanged < MIN_UNCHANGED_LINES:
            return
        if unchanged / len(old_lines) < MIN_UNCHANGED_FRACTION:
            return
    else:
        # Too large for the exact diff's quadratic worst case. Use the
        # multiset bound: it over-counts only when lines are reordered, and
        # retyping thousands of identical lines in a new order is still a
        # wasteful rewrite — Edit handles moves too.
        unchanged = upper_bound
    changed = max(len(old_lines), len(new_lines)) - unchanged
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked wasteful full-file rewrite: this Write retypes {unchanged} of "
                f"{len(old_lines)} existing lines unchanged (only ~{changed} lines differ). "
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
