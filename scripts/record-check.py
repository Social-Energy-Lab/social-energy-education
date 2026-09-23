#!/usr/bin/env python3
# Generic checks for a system-of-record repo.
#
# Errors (exit 1): malformed uncertainty markers, and a missing anchor in the
# agents file. Unresolved markers are NOT errors - they are the worklist.
#
# What it does not cover, so nobody reads a pass as more than it is:
#   - Only *.md is scanned unless --glob says otherwise. A record kept in a
#     ledger, a registry or a notebook declares its own globs; a marker in a
#     format nobody declared is invisible here.
#   - Fenced blocks and `code spans` are Markdown notions. They are honoured in
#     every swept file, so a stray backtick in a non-Markdown source can hide a
#     *malformed* marker. It can never hide a real question.
#   - Files named like the agents file are read for their anchors and then
#     skipped by the marker sweep, at any depth, because that is where the
#     markers are defined. A marker written in one is never listed.
#   - Dot-directories are skipped. Tooling, transcripts and agent scratch live
#     there; a record layer does not.
#   - A prose mention of the bare marker inside backticks is counted, because
#     nothing distinguishes it from a use. Quote the convention in a fenced
#     block if you want it out of the worklist.
#   - Nothing here reads content for sensitivity, and nothing here can check the
#     evidence rule. A pass is not evidence that a document is honest.
import argparse, os, pathlib, re, sys

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__"}
FENCE = re.compile(r"\s*(```|~~~)")
SPAN = re.compile(r"`[^`\n]*`")
# The shape the template and every skill doc writes. Never a real question.
PLACEHOLDER = re.compile(r"\A<[^<>]*>\Z")
# A question may wrap, but a blank line ends a paragraph and so ends a marker.
# Without this an unclosed bracket swallows the rest of the document.
QUESTION = r"(?:[^\]\n]|\n(?![ \t]*(?:\n|\Z)))*"
MASK = "\x00"


def _views(body):
    """Two views of a document at identical offsets: fenced blocks blanked, and
    a second copy with the contents of `code spans` blanked as well.

    Backticks are typography, not quotation: a question written inside them is
    an open question, and erasing it silences a repo whose house style is to
    backtick its markers. But a marker with no question in it cannot be a real
    one, so in a code span that form is prose *about* markers. The masked view
    is what decides that, and only that.
    """
    plain, masked, fenced = [], [], False
    for line in body.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            line = ""
        elif fenced:
            line = ""
        plain.append(line)
        masked.append(SPAN.sub(lambda m: MASK * len(m.group(0)), line))
    return "\n".join(plain), "\n".join(masked)


def check(root, inferred="inferred", unknown="unknown", agents_file="AGENTS.md",
          globs=("*.md",)):
    errors, worklist = [], []

    agents = root / agents_file
    if not agents.is_file():
        errors.append(f"{agents_file}: missing")
    else:
        text = agents.read_text(encoding="utf-8", errors="replace")
        for anchor in ("record:perimeter", "record:routing"):
            if f"<!-- {anchor} -->" not in text:
                errors.append(f"{agents_file}: missing the <!-- {anchor} --> anchor")

    good = re.compile(r"\[" + re.escape(unknown) + r": *(" + QUESTION + r")\]")
    opener = re.compile(r"\[" + re.escape(unknown) + r":")
    bare = re.compile(r"\[" + re.escape(unknown) + r"\]")
    inf = re.compile(r"\[" + re.escape(inferred) + r"\]")
    # One word declared twice says the repo runs a single marker in two forms:
    # bare means unverified, with a question means here is the question. The
    # bare form is then a worklist item rather than a malformed marker.
    fused = inferred == unknown

    # A set, so a file matching two declared globs is swept once.
    for path in sorted({p for g in globs for p in root.rglob(g)}):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if SKIP & set(parts):
            continue
        if any(p.startswith(".") for p in parts[:-1]):
            continue
        # Any agents file defines the markers for its subtree, so it matches
        # them. The root one is read above for its anchors; none is swept.
        if path.name == agents.name:
            continue
        rel = path.relative_to(root)
        # A received .md need not be UTF-8. An undecodable byte is not a marker
        # defect and must never be a traceback in somebody else's repo.
        plain, masked = _views(path.read_text(encoding="utf-8", errors="replace"))

        def at(offset):
            return plain.count("\n", 0, offset) + 1

        def quoted(m):
            return MASK in masked[m.start():m.end()]

        def line_of(offset):
            start = plain.rfind("\n", 0, offset) + 1
            end = plain.find("\n", offset)
            return plain[start:end if end != -1 else len(plain)].strip()[:90]

        closed = set()
        for m in good.finditer(plain):
            closed.add(m.start())
            question = " ".join(m.group(1).split())
            if not question:
                if not quoted(m):
                    errors.append(f"{rel}:{at(m.start())}: [{unknown}:] has an empty question")
                continue
            if PLACEHOLDER.match(question):
                continue
            worklist.append(f"{rel}:{at(m.start())}: {question}")

        for m in opener.finditer(plain):
            if m.start() not in closed and not quoted(m):
                errors.append(f"{rel}:{at(m.start())}: [{unknown}: is unterminated")

        if not fused:
            for m in bare.finditer(plain):
                if not quoted(m):
                    errors.append(f"{rel}:{at(m.start())}: [{unknown}] carries no question")

        for m in inf.finditer(plain):
            worklist.append(f"{rel}:{at(m.start())}: [{inferred}] {line_of(m.start())}")

    return errors, worklist


def main():
    ap = argparse.ArgumentParser(description="Check a system-of-record repo.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--agents-file", default="AGENTS.md")
    ap.add_argument("--inferred-marker", default="inferred")
    ap.add_argument("--unknown-marker", default="unknown")
    ap.add_argument("--glob", action="append", dest="globs", metavar="PATTERN",
                    help="file pattern to sweep; repeatable, defaults to *.md")
    ap.add_argument("--list", action="store_true", help="print the worklist and exit 0")
    a = ap.parse_args()

    errors, worklist = check(
        pathlib.Path(a.root).resolve(), a.inferred_marker, a.unknown_marker, a.agents_file,
        tuple(a.globs or ("*.md",)),
    )

    try:
        if a.list or worklist:
            print(f"worklist - {len(worklist)} open marker(s)")
            for w in worklist:
                print(f"  {w}")
        if errors:
            print("FAIL")
            for e in errors:
                print(f"  - {e}")
    except BrokenPipeError:
        # `record-check.py --list | head` is how anyone reads a long worklist.
        # A traceback there reads as a broken tool, and the exit code below is
        # still the honest answer.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
    # --list is the health check the agents-file template installs everywhere,
    # so it never exits non-zero - an open worklist is the normal state. It
    # still has to say when a marker is malformed, or the one mode people run
    # by habit is the one mode that can never report a defect.
    if a.list:
        return 0
    if errors:
        return 1
    try:
        print(f"OK - no malformed markers, anchors present ({len(worklist)} open marker(s))")
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
