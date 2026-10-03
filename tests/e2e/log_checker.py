"""Server log checker.

Library use (pytest): snapshot the log offset, run a test, then ask for new
problem blocks.  Standalone use::

    python -m tests.e2e.log_checker --follow            # live tail of logs/app.log
    python -m tests.e2e.log_checker --scan              # scan the whole file once

A "problem" is any line at ERROR/CRITICAL level, any Traceback, or any request
line with a 5xx status.  WARNING lines (4xx, failed syncs) are shown in follow
mode but do not count as failures.
"""
import argparse
import os
import re
import sys
import time
from typing import Iterable, List, Optional

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "app.log")

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
PROBLEM_RE = re.compile(r"\| (ERROR|CRITICAL) \||Traceback \(most recent call last\)|\bstatus=5\d\d\b")
WARNING_RE = re.compile(r"\| WARNING \|")

RED, YELLOW, GREEN, DIM, RESET = "\033[91;1m", "\033[93m", "\033[92m", "\033[2m", "\033[0m"


def extract_problems(text: str) -> List[str]:
    """Return problem blocks (a problem line plus its traceback continuation lines)."""
    blocks: List[str] = []
    current: Optional[List[str]] = None
    for line in text.splitlines():
        if TS_RE.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line] if PROBLEM_RE.search(line) else None
        elif current is not None:
            current.append(line)
        elif PROBLEM_RE.search(line):  # stray traceback line without a header
            current = [line]
    if current:
        blocks.append("\n".join(current))
    return blocks


class LogChecker:
    """Tracks a byte offset into a log file and reports problems written since."""

    def __init__(self, path: str = DEFAULT_LOG) -> None:
        self.path = path
        self.offset = self.size()

    def size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def snapshot(self) -> int:
        self.offset = self.size()
        return self.offset

    def read_since(self, offset: Optional[int] = None) -> str:
        offset = self.offset if offset is None else offset
        size = self.size()
        if size < offset:  # rotated
            offset = 0
        try:
            with open(self.path, "rb") as f:
                f.seek(offset)
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def problems_since(self, offset: Optional[int] = None, allow: Iterable[str] = ()) -> List[str]:
        allowed = [re.compile(a) for a in allow]
        return [b for b in extract_problems(self.read_since(offset)) if not any(a.search(b) for a in allowed)]


def colorize(line: str) -> str:
    if PROBLEM_RE.search(line):
        return f"{RED}{line}{RESET}"
    if WARNING_RE.search(line):
        return f"{YELLOW}{line}{RESET}"
    if "action_result" in line:
        return f"{GREEN}{line}{RESET}"
    if not TS_RE.match(line):
        return f"{RED}{line}{RESET}"  # traceback continuation
    return f"{DIM}{line}{RESET}"


def follow(path: str, show_all: bool = False, from_start: bool = False, stop=lambda: False, out=sys.stdout) -> int:
    """Tail ``path`` and print highlighted problems; returns the number of problem blocks seen."""
    problems = 0
    in_block = False
    print(f"[log-checker] watching {path} (Ctrl+C to stop)", file=out, flush=True)
    while not os.path.exists(path):
        if stop():
            return 0
        time.sleep(0.3)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        if not from_start:
            f.seek(0, os.SEEK_END)
        while not stop():
            line = f.readline()
            if not line:
                time.sleep(0.25)
                if os.path.getsize(path) < f.tell():  # rotated
                    f.seek(0)
                continue
            line = line.rstrip("\n")
            is_ts = bool(TS_RE.match(line))
            if is_ts:
                in_block = bool(PROBLEM_RE.search(line))
                if in_block:
                    problems += 1
            interesting = in_block or (is_ts and WARNING_RE.search(line)) or "action_result" in line
            if show_all or interesting:
                print(colorize(line), file=out, flush=True)
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default=os.environ.get("COACH_LOG_FILE", DEFAULT_LOG))
    ap.add_argument("--follow", action="store_true", help="tail the log live and highlight problems")
    ap.add_argument("--all", action="store_true", help="in follow mode print every line, not only problems")
    ap.add_argument("--from-start", action="store_true", help="in follow mode start at the beginning of the file")
    ap.add_argument("--scan", action="store_true", help="scan the whole file once and exit 1 if problems exist")
    args = ap.parse_args(argv)
    if os.name == "nt":
        os.system("")  # enable ANSI colours
    if args.follow:
        try:
            follow(args.path, show_all=args.all, from_start=args.from_start)
        except KeyboardInterrupt:
            pass
        return 0
    checker = LogChecker(args.path)
    checker.offset = 0
    found = checker.problems_since(0)
    for block in found:
        print(f"{RED}{block}{RESET}")
    print(f"[log-checker] {len(found)} problem block(s) in {args.path}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
