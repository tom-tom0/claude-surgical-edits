# claude-surgical-edits

A small framework for Claude Code that stops the model (notably Claude Fable 5.1)
from rewriting entire files when a targeted edit would do, cutting output-token
usage on typical edits by ~90%.

## The problem

Fable 5.1 is more likely than Fable 5 to rewrite a whole file with the `Write`
tool instead of making a surgical change with the `Edit` tool. The resulting
file is usually identical, but retyping hundreds of unchanged lines costs far
more output tokens and time.

## How it works

Two layers, both user-level (apply to every project and session):

1. **Steering instruction** (`CLAUDE.md`) — tells the model up front to prefer
   targeted `Edit` calls over full `Write` rewrites, so most wasteful rewrites
   are never attempted.
2. **Enforcement hook** (`hooks/block-full-rewrite.py`) — a `PreToolUse` hook
   on the `Write` tool. Before any write executes, it diffs the proposed
   content against the existing file. If the write would retype **20+
   unchanged lines** and **at least 50% of the file stays the same**, it is
   denied with a message telling the model to use `Edit` instead. The model
   sees the message and self-corrects in the same turn.

The hook never blocks legitimate writes: new files, short files (< 20 lines),
binary/non-UTF-8 files, line-ending conversions, and genuine rewrites where
most content changes all pass through. Any internal error fails open — a
broken hook can never block your work.

**Large files — no line cap.** The check protects files of *any* line count
and stays instant doing it: writes of new content under half the file's line
count are allowed without diffing (a denial mathematically requires ≥50%
retyped lines), the exact diff runs up to 5,000 lines, and above that a
conservative O(n) estimate decides. The only opt-out is a 32 MB byte guard
(checked by `stat` before reading) that no real source file approaches — and
a file that large could never be denied anyway, since tool output limits cap
new content far below half of it. Measured worst cases — the adversarial
ones, not the friendly ones: 100,000 lines with 1 changed denies in ~110 ms;
49,000 lines with every other line changed (difflib's quadratic nightmare,
which would otherwise take ~2.5 minutes) answers in ~80 ms; a 10 MB file of
long minified lines in ~115 ms. The registered hook timeout is 15 s; nothing
measured comes within 100x of it.

## Install

```sh
python3 install.py
```

The installer copies the hook to `~/.claude/hooks/`, merges the hook
registration into `~/.claude/settings.json` (preserving existing settings),
and appends the steering instruction to `~/.claude/CLAUDE.md` if not present.
Run `/hooks` once in Claude Code (or restart it) to load the new hook.

Manual install: see `settings-snippet.json` and `claude-md-snippet.md`.

**Windows note:** the registered hook command invokes `python3`, which exists
on Linux/macOS but not on stock Windows (where the launcher is `python` or
`py`). On Windows, after installing, edit the hook entry in
`~/.claude/settings.json` to use `python` instead of `python3`. Hooks fail
open, so a wrong interpreter name never blocks writes — the hook just
silently does nothing until the command is fixed.

## Verify and benchmark

```sh
python3 hooks/test_block_full_rewrite.py    # 56-case test suite
python3 hooks/benchmark_token_savings.py    # token-savings benchmark
```

Benchmark results (output tokens, estimated at 4 chars/token):

| Scenario | Full rewrite | Surgical | Saved |
|---|---:|---:|---:|
| Fix a typo in a 150-line file | 2,343 | 242 | 90% |
| Rewrite one function in a 400-line file | 6,235 | 468 | 92% |
| Update imports in an 800-line file | 12,458 | 211 | 98% |
| Small tweak in a 2,000-line file | 31,235 | 280 | 99% |
| Big refactor, ~60% changed | 4,226 | 4,226 | 0% (rewrite correctly allowed) |

A simulated 20-edit coding session: **~183k output tokens without the
framework vs ~15k with it (92% saved)**. Generation time scales with output
tokens, so that is roughly 92% less waiting on edits.

Caveat: a `PreToolUse` hook fires after the model has generated the tool call,
so an attempted full rewrite is paid for once before being blocked; the deny
message then steers the rest of the session to `Edit`, and the `CLAUDE.md`
instruction prevents most attempts in the first place.

## Tuning

Thresholds at the top of `hooks/block-full-rewrite.py`:

- `MIN_UNCHANGED_LINES` (20) — minimum retyped-unchanged lines before blocking
- `MIN_UNCHANGED_FRACTION` (0.5) — minimum fraction of the file left unchanged
- `MAX_LINES` (50000) — files larger than this are never checked (fail open)
