#!/usr/bin/env python3
"""Benchmark: output tokens saved by the block-full-rewrite framework.

Compares, for realistic editing scenarios, the output tokens Fable 5.1 spends:
  - WITHOUT the framework: rewriting the whole file with one Write call
  - WITH the framework:    surgical Edit calls (old_string + new_string,
                           each padded with context lines for uniqueness)

Each scenario's full-rewrite payload is also piped through the real hook to
verify which path the framework would actually enforce.

Token counts are estimated at 4 characters per token (a standard conservative
approximation for code) plus fixed per-tool-call JSON overhead. Run with:
  python3 benchmark_token_savings.py
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-full-rewrite.py")
CHARS_PER_TOKEN = 4.0
TOOL_CALL_OVERHEAD = 30   # tokens: tool name, JSON keys, file path, quoting
CONTEXT_LINES = 3         # lines of context each side of a change in old_string


def tokens(text):
    return int(len(text) / CHARS_PER_TOKEN)


def make_file(n_lines, avg_len=48):
    """Generate a realistic code-like file: varied-length indented lines."""
    out = []
    for i in range(n_lines):
        indent = "    " * (i % 3)
        body = f"value_{i} = compute_result(input_{i}, mode='standard', retries={i % 5})"
        out.append((indent + body)[: avg_len + (i * 7) % 30])
    return "\n".join(out) + "\n"


def apply_changes(content, change_groups):
    """change_groups: list of (start_line, n_lines_replaced, n_new_lines)."""
    lines = content.splitlines()
    for start, n_old, n_new in sorted(change_groups, reverse=True):
        new_block = [f"    updated_line_{start}_{j} = new_implementation(arg_{j})" for j in range(n_new)]
        lines[start : start + n_old] = new_block
    return "\n".join(lines) + "\n"


def edit_call_tokens(content, change_groups):
    """Cost of surgical edits: per group, old_string + new_string + overhead."""
    lines = content.splitlines()
    total = 0
    for start, n_old, n_new in change_groups:
        lo = max(0, start - CONTEXT_LINES)
        hi = min(len(lines), start + n_old + CONTEXT_LINES)
        old_str = "\n".join(lines[lo:hi])
        new_block = [f"    updated_line_{start}_{j} = new_implementation(arg_{j})" for j in range(n_new)]
        new_str = "\n".join(lines[lo:start] + new_block + lines[start + n_old : hi])
        total += tokens(old_str) + tokens(new_str) + TOOL_CALL_OVERHEAD
    return total


def hook_verdict(old_content, new_content):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(old_content)
        path = f.name
    try:
        payload = json.dumps({
            "tool_name": "Write",
            "tool_input": {"file_path": path, "content": new_content},
        }).encode()
        proc = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, timeout=30)
        return "BLOCKS" if b'"deny"' in proc.stdout else "allows"
    finally:
        os.unlink(path)


SCENARIOS = [
    # (name, file_lines, change_groups [(start, old_lines, new_lines)])
    ("Fix a typo (1 line, 150-line file)",          150, [(70, 1, 1)]),
    ("Change a config value (40-line file)",         40, [(12, 1, 1)]),
    ("Rewrite one function (8 lines, 400-line file)",400, [(200, 8, 10)]),
    ("Add 15-line function (400-line file)",        400, [(399, 1, 16)]),
    ("Two scattered tweaks (250-line file)",        250, [(40, 2, 2), (180, 3, 3)]),
    ("Rename in 6 places (500-line file)",          500, [(50, 1, 1), (120, 1, 1), (210, 1, 1), (300, 1, 1), (390, 1, 1), (470, 1, 1)]),
    ("Update imports (3 lines, 800-line file)",     800, [(0, 3, 4)]),
    ("Small tweak in 2000-line file",              2000, [(1500, 2, 2)]),
    ("Big refactor, ~60% changed (300-line file)",  300, [(0, 180, 180)]),
]


def main():
    print(f"Token estimate: {CHARS_PER_TOKEN} chars/token, "
          f"+{TOOL_CALL_OVERHEAD} tokens overhead per tool call, "
          f"{CONTEXT_LINES} context lines per Edit\n")
    header = f"{'Scenario':<48} {'Write':>7} {'Edit':>6} {'Saved':>7} {'%':>5}  Hook"
    print(header)
    print("-" * len(header))
    tot_write = tot_edit = 0
    for name, n_lines, groups in SCENARIOS:
        old = make_file(n_lines)
        new = apply_changes(old, groups)
        write_cost = tokens(new) + TOOL_CALL_OVERHEAD
        edit_cost = edit_call_tokens(old, groups)
        verdict = hook_verdict(old, new)
        # When the hook allows the Write (legit rewrite), the session just
        # writes: no savings, but no penalty either.
        effective = edit_cost if verdict == "BLOCKS" else write_cost
        saved = write_cost - effective
        pct = 100.0 * saved / write_cost if write_cost else 0.0
        tot_write += write_cost
        tot_edit += effective
        print(f"{name:<48} {write_cost:>7} {effective:>6} {saved:>7} {pct:>4.0f}%  {verdict}")
    print("-" * len(header))
    saved = tot_write - tot_edit
    pct = 100.0 * saved / tot_write
    print(f"{'TOTAL (one of each scenario)':<48} {tot_write:>7} {tot_edit:>6} {saved:>7} {pct:>4.0f}%")

    # A realistic working session: many small edits, occasional big ones.
    session = ([SCENARIOS[0]] * 4 + [SCENARIOS[2]] * 5 + [SCENARIOS[4]] * 4 +
               [SCENARIOS[6]] * 2 + [SCENARIOS[7]] * 3 + [SCENARIOS[8]] * 2)
    s_write = s_edit = 0
    for name, n_lines, groups in session:
        old = make_file(n_lines)
        new = apply_changes(old, groups)
        w = tokens(new) + TOOL_CALL_OVERHEAD
        e = edit_call_tokens(old, groups)
        blocked = hook_verdict(old, new) == "BLOCKS"
        s_write += w
        s_edit += e if blocked else w
    print(f"\nSimulated 20-edit coding session:")
    print(f"  Fable 5.1 full-rewrite style (no framework): ~{s_write:,} output tokens")
    print(f"  With framework (surgical edits):             ~{s_edit:,} output tokens")
    print(f"  Saved: ~{s_write - s_edit:,} output tokens ({100.0 * (s_write - s_edit) / s_write:.0f}%)")
    print("\nNote: output tokens are also the slowest tokens — generation time")
    print("scales with them — so the % saved is roughly % less waiting on edits.")
    print("Worst case per file: if the model still attempts one full Write, the")
    print("hook blocks it after generation (that attempt is spent once), and the")
    print("deny message steers all later edits in the session to the cheap path.")


if __name__ == "__main__":
    main()
