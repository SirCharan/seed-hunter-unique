#!/usr/bin/env python3
"""
Best-effort git add/commit/push when a capital hit is found.

Pushes to origin of THIS repo only (SirCharan/seed-hunter-unique).
Refuses if origin points at the sister all-words repo SirCharan/seed-hunter.

Only touches capital-related tracked files. Concurrent workers may race;
flock + try/except keeps local hit files safe if git fails.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Sequence

CAPITAL_GIT_FILES: Sequence[str] = (
    "capital_seeds.jsonl",
    "found_wallets_capital.jsonl",
    "capital_hits.md",
)

LOCK_FILE = ".capital_git_push.lock"


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _run(
    args: Sequence[str],
    *,
    cwd: str,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _commit_message(hit: Dict[str, Any]) -> str:
    address = hit.get("address") or "?"
    bal = hit.get("balance_eth")
    if bal is None:
        bal = "?"
    chain = hit.get("chain") or "?"
    return f"capital: {address} bal={bal} on {chain}"


def push_capital_to_git(hit: Optional[Dict[str, Any]] = None) -> bool:
    """
    git add capital files + commit + push origin main.

    Returns True on success. On any failure logs a warning and returns False
    so callers keep local archives intact.
    """
    hit = hit or {}
    root = _repo_root()
    lock_path = os.path.join(root, LOCK_FILE)
    try:
        with open(lock_path, "a+", encoding="utf-8") as lockf:
            try:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(
                    "WARN: capital git push skipped (another worker holds lock)",
                    file=sys.stderr,
                )
                return False

            try:
                return _push_locked(root, hit)
            finally:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        print(f"WARN: capital git push failed (local files kept): {exc}", file=sys.stderr)
        return False


def _push_locked(root: str, hit: Dict[str, Any]) -> bool:
    # Safety: only push to THIS repo (seed-hunter-unique), never sister all-words seed-hunter
    remote = _run(["git", "remote", "get-url", "origin"], cwd=root)
    url = (remote.stdout or "").strip()
    if "seed-hunter" in url and "seed-hunter-unique" not in url:
        print(
            f"WARN: capital git push refused — origin is not seed-hunter-unique: {url[:200]}",
            file=sys.stderr,
        )
        return False

    existing = [f for f in CAPITAL_GIT_FILES if os.path.exists(os.path.join(root, f))]
    if not existing:
        print("WARN: capital git push: no capital files present", file=sys.stderr)
        return False

    # Refresh remote tip so push is less likely to reject
    pull = _run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=root)
    if pull.returncode != 0:
        # Non-fatal: still try add/commit/push; pull noise logged
        err = (pull.stderr or pull.stdout or "").strip()
        if err:
            print(f"WARN: git pull before capital push: {err[:400]}", file=sys.stderr)

    add = _run(["git", "add", "--"] + list(existing), cwd=root)
    if add.returncode != 0:
        print(
            f"WARN: git add failed: {(add.stderr or add.stdout or '').strip()[:400]}",
            file=sys.stderr,
        )
        return False

    # Nothing staged?
    diff = _run(["git", "diff", "--cached", "--quiet"], cwd=root)
    if diff.returncode == 0:
        # Clean index for these files — already committed
        return True

    msg = _commit_message(hit)
    commit = _run(["git", "commit", "-m", msg], cwd=root)
    if commit.returncode != 0:
        print(
            f"WARN: git commit failed: {(commit.stderr or commit.stdout or '').strip()[:400]}",
            file=sys.stderr,
        )
        return False

    # Small backoff before push under contention
    time.sleep(0.2)
    push = _run(["git", "push", "origin", "main"], cwd=root, timeout=180.0)
    if push.returncode != 0:
        print(
            f"WARN: git push failed (local commit kept): "
            f"{(push.stderr or push.stdout or '').strip()[:400]}",
            file=sys.stderr,
        )
        return False

    print(f"Pushed capital hit to origin/main: {msg}")
    return True


if __name__ == "__main__":
    # Manual test: push whatever capital files are currently dirty
    ok = push_capital_to_git({"address": "manual", "balance_eth": 0, "chain": "ethereum"})
    sys.exit(0 if ok else 1)
