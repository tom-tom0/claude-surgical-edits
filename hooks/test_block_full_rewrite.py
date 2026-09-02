#!/usr/bin/env python3
"""Test suite for block-full-rewrite.py.

Runs the hook exactly as Claude Code does: as a subprocess with a JSON
payload on stdin. Every fixture file is created inside a temporary sandbox
that is deleted afterwards. Run with: python3 test_block_full_rewrite.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-full-rewrite.py")
SANDBOX = tempfile.mkdtemp(prefix="hook-test-")

PASS, FAIL = 0, []


def run_hook(stdin_bytes, timeout=30):
    proc = subprocess.run(
        [sys.executable, HOOK], input=stdin_bytes,
        capture_output=True, timeout=timeout,
    )
    return proc


def payload(file_path, content, tool_name="Write"):
    return json.dumps({
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, "content": content},
    }).encode()


def fixture(name, data):
    path = os.path.join(SANDBOX, name)
    if isinstance(data, bytes):
        with open(path, "wb") as f:
            f.write(data)
    else:
        with open(path, "w", newline="") as f:
            f.write(data)
    return path


def lines(n, prefix="line", ending="\n"):
    return ending.join(f"{prefix} {i}" for i in range(1, n + 1)) + ending


def check(name, stdin_bytes, expect, max_seconds=None):
    """expect: 'allow', 'deny', or 'any' (only checks it doesn't crash)."""
    global PASS
    t0 = time.monotonic()
    try:
        proc = run_hook(stdin_bytes)
    except subprocess.TimeoutExpired:
        FAIL.append(f"{name}: TIMED OUT")
        print(f"  FAIL {name}: timed out")
        return
    elapsed = time.monotonic() - t0
    out = proc.stdout.decode(errors="replace").strip()
    denied = '"deny"' in out
    problems = []
    if proc.returncode != 0:
        problems.append(f"exit code {proc.returncode} (must always be 0)")
    if expect == "allow" and out:
        problems.append(f"expected silence, got output: {out[:120]}")
    if expect == "deny" and not denied:
        problems.append(f"expected deny, got: {out[:120] or '(silence)'}")
    if expect == "deny" and denied:
        try:
            parsed = json.loads(out)
            hso = parsed["hookSpecificOutput"]
            assert hso["hookEventName"] == "PreToolUse"
            assert hso["permissionDecision"] == "deny"
            assert "Edit" in hso["permissionDecisionReason"]
        except Exception as e:
            problems.append(f"malformed deny JSON: {e}")
    if max_seconds is not None and elapsed > max_seconds:
        problems.append(f"took {elapsed:.2f}s (limit {max_seconds}s)")
    if problems:
        FAIL.append(f"{name}: " + "; ".join(problems))
        print(f"  FAIL {name}: " + "; ".join(problems))
    else:
        PASS += 1
        verdict = "deny" if denied else "allow"
        print(f"  ok   {name}  [{verdict}, {elapsed:.2f}s]")


def main():
    print(f"Hook under test: {HOOK}")
    print(f"Sandbox: {SANDBOX}\n")

    print("== Group 1: core allow/deny behavior ==")
    f40 = fixture("f40.txt", lines(40))
    changed2 = lines(40).replace("line 5\n", "line 5 CHANGED\n").replace("line 21\n", "line 21 CHANGED\n")
    check("tiny change in 40-line file", payload(f40, changed2), "deny")
    check("identical rewrite (pure waste)", payload(f40, lines(40)), "deny")
    check("completely new content", payload(f40, lines(40, prefix="other")), "allow")
    check("new file (does not exist)", payload(os.path.join(SANDBOX, "nope.txt"), "hello\n"), "allow")
    f19 = fixture("f19.txt", lines(19))
    check("19-line file below size floor", payload(f19, lines(19).replace("line 3\n", "x\n")), "allow")
    f20 = fixture("f20.txt", lines(20))
    # 1 change in 20 lines leaves only 19 unchanged -> below floor -> allow by design
    check("20-line file, 1 change (19 unchanged)", payload(f20, lines(20).replace("line 3\n", "x\n")), "allow")
    check("20-line file, identical rewrite", payload(f20, lines(20)), "deny")
    f21 = fixture("f21.txt", lines(21))
    check("21-line file, 1 change (20 unchanged)", payload(f21, lines(21).replace("line 3\n", "x\n")), "deny")

    print("\n== Group 2: threshold boundaries ==")
    # 40 lines, exactly 20 unchanged (fraction exactly 0.50) -> deny
    half = "".join(
        (f"line {i}\n" if i <= 20 else f"DIFF {i}\n") for i in range(1, 41)
    )
    check("exactly 50% unchanged (boundary)", payload(f40, half), "deny")
    # 40 lines, 19 unchanged -> below MIN_UNCHANGED_LINES -> allow
    nineteen = "".join(
        (f"line {i}\n" if i <= 19 else f"DIFF {i}\n") for i in range(1, 41)
    )
    check("19 unchanged lines (below floor)", payload(f40, nineteen), "allow")
    # 100 lines, 45 unchanged -> fraction 0.45 < 0.5 -> allow
    f100 = fixture("f100.txt", lines(100))
    fortyfive = "".join(
        (f"line {i}\n" if i <= 45 else f"DIFF {i}\n") for i in range(1, 101)
    )
    check("45% unchanged (below fraction)", payload(f100, fortyfive), "allow")
    # 100 lines, 55 unchanged -> deny
    fiftyfive = "".join(
        (f"line {i}\n" if i <= 55 else f"DIFF {i}\n") for i in range(1, 101)
    )
    check("55% unchanged (above fraction)", payload(f100, fiftyfive), "deny")

    print("\n== Group 3: growth, shrink, structure ==")
    check("append 100 lines to 40-line file", payload(f40, lines(40) + lines(100, prefix="new")), "deny")
    check("prepend 30 lines", payload(f40, lines(30, prefix="top") + lines(40)), "deny")
    check("truncate file to empty", payload(f40, ""), "allow")
    check("delete most lines (keep 5)", payload(f40, lines(5)), "allow")
    shuffled = "".join(f"line {i}\n" for i in [*range(21, 41), *range(1, 21)])
    check("reorder halves (big block move)", payload(f40, shuffled), "any")
    f_dup = fixture("dup.txt", "same\n" * 1000)
    check("1000 duplicate lines, 1 changed", payload(f_dup, "same\n" * 500 + "different\n" + "same\n" * 499), "deny")

    print("\n== Group 4: encodings and line endings ==")
    crlf = fixture("crlf.txt", lines(40, ending="\r\n"))
    check("CRLF->LF conversion only", payload(crlf, lines(40)), "allow")
    check("CRLF file, 2 CRLF lines changed", payload(crlf, lines(40, ending="\r\n").replace("line 5\r\n", "X\r\n")), "deny")
    uni = fixture("uni.txt", "".join(f"café \U0001f600 {i}\n" for i in range(40)))
    uni_new = "".join((f"café \U0001f600 {i}\n" if i != 7 else "changed\n") for i in range(40))
    check("unicode/emoji content, 1 change", payload(uni, uni_new), "deny")
    binf = fixture("bin.dat", bytes(range(256)) * 40)
    check("binary file (undecodable)", payload(binf, lines(40)), "allow")
    latin = fixture("latin.txt", "caf\xe9\n".encode("latin-1") * 40)
    check("non-UTF8 (latin-1) file", payload(latin, "café\n" * 40), "allow")
    no_trail = fixture("notrail.txt", lines(40).rstrip("\n"))
    check("only adds trailing newline", payload(no_trail, lines(40)), "deny")
    empty = fixture("empty.txt", "")
    check("existing empty file", payload(empty, lines(40)), "allow")
    one_long = fixture("oneline.txt", "x" * 500000)
    check("single 500KB line", payload(one_long, "y" * 500000), "allow")

    print("\n== Group 5: malformed / hostile input (must fail open, exit 0) ==")
    check("garbage stdin", b"not json at all", "allow")
    check("empty stdin", b"", "allow")
    check("JSON array instead of object", b"[1,2,3]", "allow")
    check("null tool_input", json.dumps({"tool_name": "Write", "tool_input": None}).encode(), "allow")
    check("missing tool_input", json.dumps({"tool_name": "Write"}).encode(), "allow")
    check("missing file_path", json.dumps({"tool_name": "Write", "tool_input": {"content": "x"}}).encode(), "allow")
    check("missing content", json.dumps({"tool_name": "Write", "tool_input": {"file_path": f40}}).encode(), "allow")
    check("null content", json.dumps({"tool_name": "Write", "tool_input": {"file_path": f40, "content": None}}).encode(), "allow")
    check("content is a number", json.dumps({"tool_name": "Write", "tool_input": {"file_path": f40, "content": 42}}).encode(), "allow")
    check("file_path is a number", json.dumps({"tool_name": "Write", "tool_input": {"file_path": 42, "content": "x"}}).encode(), "allow")
    check("different tool (Edit) passes through", payload(f40, lines(40), tool_name="Edit"), "allow")
    check("file_path is a directory", payload(SANDBOX, lines(40)), "allow")
    check("relative path that does not exist", payload("no/such/rel/path.txt", "x\n"), "allow")
    if os.name == "posix" and os.geteuid() != 0:
        noperm = fixture("noperm.txt", lines(40))
        os.chmod(noperm, 0o000)
        check("unreadable file (chmod 000)", payload(noperm, lines(40)), "allow")
        os.chmod(noperm, 0o644)

    print("\n== Group 6: symlinks ==")
    target = fixture("target.txt", lines(40))
    link = os.path.join(SANDBOX, "link.txt")
    os.symlink(target, link)
    check("symlink to real file, tiny change", payload(link, lines(40).replace("line 9\n", "X\n")), "deny")
    broken = os.path.join(SANDBOX, "broken-link.txt")
    os.symlink(os.path.join(SANDBOX, "gone.txt"), broken)
    check("broken symlink", payload(broken, lines(40)), "allow")

    print("\n== Group 7: performance and size guard ==")
    f10k = fixture("f10k.txt", lines(10000))
    check("10k lines, 3 changed", payload(f10k, lines(10000).replace("line 5000\n", "X\n")), "deny", max_seconds=5)
    check("10k lines, all different", payload(f10k, lines(10000, prefix="zzz")), "allow", max_seconds=10)
    f60k = fixture("f60k.txt", lines(60000))
    check("60k lines, 1 changed (no line cap anymore)", payload(f60k, lines(60000).replace("line 5\n", "X\n")), "deny", max_seconds=3)
    f100k = fixture("f100k.txt", lines(100000))
    check("100k lines, 1 changed", payload(f100k, lines(100000).replace("line 5\n", "X\n")), "deny", max_seconds=3)
    check("100k-line file, small new content (early allow)", payload(f100k, lines(100)), "allow", max_seconds=3)
    # Retyping all 40 old lines then appending 60k more is still a retype +
    # append — same semantics as the small append case in Group 3: deny.
    check("40-line file, 60k-line new content (append)", payload(f40, lines(60000)), "deny", max_seconds=3)
    fhuge = os.path.join(SANDBOX, "huge.txt")
    with open(fhuge, "w") as f:
        chunk = "padding line for the byte guard\n" * 100000
        while f.tell() < 33 * 1024 * 1024:
            f.write(chunk)
    check("33MB file (over byte guard) -> fail open", payload(fhuge, lines(40)), "allow", max_seconds=3)
    f49k = fixture("f49k.txt", lines(49000))
    check("49k lines similar (under cap)", payload(f49k, lines(49000).replace("line 7\n", "X\n")), "deny", max_seconds=3)

    print("\n== Group 8: adversarial scale (difflib worst cases) ==")
    # Alternating changed/unchanged lines is SequenceMatcher's quadratic
    # worst case (~26s at 20k lines) — the estimate path must answer fast.
    def alternating(n):
        return "".join(
            (f"line {i}\n" if i % 2 == 0 else f"rewritten {i}\n") for i in range(1, n + 1)
        )
    f6k = fixture("f6k.txt", lines(6000))
    check("6k lines, 3 changed (estimate path)", payload(f6k, lines(6000).replace("line 3000\n", "X\n")), "deny", max_seconds=3)
    f20k = fixture("f20k.txt", lines(20000))
    check("20k lines, alternating 50% changed (worst case)", payload(f20k, alternating(20000)), "deny", max_seconds=3)
    check("49k lines, alternating 50% changed (worst case)", payload(f49k, alternating(49000)), "deny", max_seconds=3)
    check("49k lines, all different (prescreen fast-path)", payload(f49k, lines(49000, prefix="zzz")), "allow", max_seconds=3)
    # Reordering a huge file still retypes every line: estimate path denies.
    halves = lines(30000).splitlines(keepends=True)
    reordered = "".join(halves[15000:] + halves[:15000])
    f30k = fixture("f30k.txt", lines(30000))
    check("30k lines reordered (still a full retype)", payload(f30k, reordered), "deny", max_seconds=3)
    # At exact-diff scale, a 5k alternating file must still be exact and fast.
    f5k = fixture("f5k.txt", lines(5000))
    check("5k lines, alternating (exact path worst case)", payload(f5k, alternating(5000)), "deny", max_seconds=6)

    print("\n== Group 9: substantive-line weighting (from 48-scenario edit-pattern study) ==")
    # A genuine CSS/JS rewrite keeps every lone brace and blank separator.
    # Those trivial lines (<=3 chars stripped) must not count as "retyped".
    css_old = "".join(
        f".rule-{i} {{\n  color: #a{i%10}b{i%10}c{i%10};\n  margin: {i}px;\n}}\n\n" for i in range(20)
    )
    css_new = ":root {\n  --brand: #336699;\n}\n" + "".join(
        f".rule-{i} {{\n  color: var(--brand);\n  padding: {i*2}px {i}px;\n  display: flex;\n}}\n\n" for i in range(20)
    )
    f_css = fixture("rewrite.css", css_old)
    check("brace-heavy CSS rewrite (only braces/blanks survive)", payload(f_css, css_new), "allow")
    # Doc reflow: blank separator lines survive, every paragraph changes.
    doc_old = "".join(f"Question {i}: " + "words " * 30 + "\n\n" for i in range(20))
    doc_new = "".join(
        f"## Q{i}\n" + "".join("words " * 8 + "\n" for _ in range(4)) + "\n" for i in range(20)
    )
    f_doc = fixture("faq.md", doc_old)
    check("doc reflow (only blank separators survive)", payload(f_doc, doc_new), "allow")
    # A file that is mostly trivial lines has nothing meaningful to waste.
    f_triv = fixture("trivial.txt", ("}\n" * 30 + "real content line here\n" * 10))
    check("mostly-trivial file, 1 real change", payload(f_triv, "}\n" * 30 + "real content line here\n" * 9 + "changed content line\n"), "allow")
    # But substantive retyping still denies even with braces around it.
    js_old = "".join(f"function f{i}() {{\n  return compute({i}) + offset_{i};\n}}\n" for i in range(30))
    js_new = js_old.replace("offset_7", "OFFSET_7")
    f_js = fixture("braces.js", js_old)
    check("brace-heavy file, 1 substantive change", payload(f_js, js_new), "deny")
    # Intended behavior, documented: normalizing mixed line endings while
    # changing one value is allowed — Edit cannot practically convert
    # endings, so blocking would break a legitimate whole-file operation.
    mixed = "".join((f"key{i} = value{i}\r\n" if i % 3 else f"key{i} = value{i}\n") for i in range(40))
    f_mixed = fixture("mixed.ini", mixed)
    normalized = "".join(f"key{i} = value{i}\n" for i in range(40)).replace("key7 = value7", "key7 = enabled")
    check("mixed CRLF/LF normalize + 1 change (intended allow)", payload(f_mixed, normalized), "allow")

    print("\n== Summary ==")
    total = PASS + len(FAIL)
    print(f"{PASS}/{total} passed")
    if FAIL:
        print("Failures:")
        for f in FAIL:
            print(f"  - {f}")
    shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
