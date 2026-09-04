#!/usr/bin/env python3
"""
Optimized multi-shard BIP39 stream hunter (no phrase storage).

Four non-overlapping shards cover the full 2^128 entropy space exactly once:

  low_fwd  — [0, mid)   ascending,  even indices only
  low_rev  — [0, mid)   descending, odd indices only
  high_fwd — [mid, end) ascending,  even indices only
  high_rev — [mid, end) descending, odd indices only

Hot path (default): JSON-RPC eth_getBalance + eth_getTransactionCount (batched).
Etherscan is optional and only used to enrich confirmed hits.

Usage:
  # RPC mode (no Etherscan keys required)
  python seed_shard.py --shard low_fwd --workers 4 --worker-id 0 --backend rpc

  # Preset A+F (default): RPC balance+nonce, Etherscan enrich capital hits when keys set
  export ETHERSCAN_API_KEY=key1,key2
  python seed_shard.py --shard low_fwd --workers 4 --worker-id 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

try:
    import aiohttp
except ImportError:
    print("ERROR: pip install aiohttp")
    sys.exit(1)

from seed_hunter_async import (
    DEFAULT_PATH,
    derive_address_sync,
    entropy_index_to_phrase,
    valid_mnemonic_space,
)
from seed_checker_multichain import (
    FREE_TIER_CHAINS,
    PAID_TIER_CHAINS,
    append_activity_hit,
    append_capital_hit,
    check_address_all_chains,
    EtherscanClient,
)
from rpc_checker import (
    DEFAULT_CHAINS_RPC,
    build_rpc_client,
    enrich_hit_etherscan,
    signals_to_hits,
)

RESULTS_FILE = "found_wallets_capital.jsonl"
ACTIVITY_FILE = "found_wallets_activity.jsonl"

# Etherscan free-tier safe default (only used in etherscan backend / enrich)
DEFAULT_RATE_PER_KEY = 2.5
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_CONCURRENT = 8
DEFAULT_RPC_RPS = 20.0


@dataclass(frozen=True)
class ShardSpec:
    name: str
    lo: int
    hi: int
    direction: int  # +1 forward, -1 reverse
    parity: int


@dataclass(frozen=True)
class Config:
    shard: ShardSpec
    worker_id: int
    num_workers: int
    chains: List[str]
    api_keys: List[str]
    rate_limit: float
    results_file: str
    activity_file: str
    progress_file: str
    length: int
    path: str
    max_concurrent: int
    capital_only: bool
    min_balance: float
    backend: str  # rpc | etherscan
    check_mode: str  # balance | nonce | both
    batch_size: int
    save_activity: bool
    enrich_etherscan: bool
    rpc_rps: float
    rpc_urls_eth: Optional[str]
    unique_words: bool


def shard_specs(space: int) -> Dict[str, ShardSpec]:
    mid = space // 2
    return {
        "low_fwd": ShardSpec("low_fwd", 0, mid, +1, 0),
        "low_rev": ShardSpec("low_rev", 0, mid, -1, 1),
        "high_fwd": ShardSpec("high_fwd", mid, space, +1, 0),
        "high_rev": ShardSpec("high_rev", mid, space, -1, 1),
    }


def words_all_unique(phrase: str) -> bool:
    """True if every whitespace-separated word in phrase appears once."""
    words = phrase.split()
    return len(words) == len(set(words))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optimized multi-shard seed stream hunter")
    p.add_argument(
        "--shard",
        required=True,
        choices=["low_fwd", "low_rev", "high_fwd", "high_rev"],
    )
    p.add_argument("--worker-id", type=int, default=0)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument(
        "--chains",
        default=DEFAULT_CHAINS_RPC,
        help="Comma-separated chains (RPC default: ethereum). "
        "RPC supports: ethereum,polygon,arbitrum,base,bsc,optimism,avalanche",
    )
    p.add_argument("--etherscan-key", default=None)
    p.add_argument("--results-file", default=RESULTS_FILE)
    p.add_argument("--activity-file", default=ACTIVITY_FILE)
    p.add_argument("--progress-file", default=None)
    p.add_argument("--length", type=int, default=12)
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    p.add_argument(
        "--rate-limit",
        type=float,
        default=None,
        help=f"Etherscan req/s per key (default {DEFAULT_RATE_PER_KEY})",
    )
    p.add_argument(
        "--backend",
        choices=["rpc", "etherscan"],
        default="rpc",
        help="Hot-path checker: rpc (default) or etherscan",
    )
    p.add_argument(
        "--check-mode",
        choices=["balance", "nonce", "both"],
        default="both",
        help="RPC checks: balance, nonce (activity), or both (default)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Addresses per JSON-RPC batch (default 20)",
    )
    p.add_argument(
        "--save-activity",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Save nonce>0 empty wallets to activity file (default: on)",
    )
    p.add_argument(
        "--enrich-etherscan",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preset F: on capital hits, confirm balance via Etherscan (default on; needs keys)",
    )
    p.add_argument(
        "--rpc-rps",
        type=float,
        default=DEFAULT_RPC_RPS,
        help="Soft max RPC requests/sec per process per chain (default 20)",
    )
    p.add_argument(
        "--rpc-url",
        default=None,
        help="Override ethereum RPC URL(s), comma-separated",
    )
    p.add_argument(
        "--capital-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Capital mode (default on). Activity still saved if --save-activity.",
    )
    p.add_argument(
        "--min-balance",
        type=float,
        default=0.0,
        help="Minimum native balance to count as capital hit",
    )
    p.add_argument(
        "--unique-words",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only RPC-check phrases where all BIP39 words are unique "
        "(default: on). Use --no-unique-words to include repeats.",
    )
    return p.parse_args()


def resolve_config(args: argparse.Namespace) -> Config:
    if args.worker_id < 0 or args.worker_id >= args.workers:
        raise ValueError(f"--worker-id must be 0..{args.workers - 1}")

    space = valid_mnemonic_space(args.length, test_mode=False)
    shard = shard_specs(space)[args.shard]

    chains = [c.strip().lower() for c in args.chains.split(",") if c.strip()]
    if not chains:
        raise SystemExit("ERROR: no chains specified")

    raw = args.etherscan_key or os.getenv("ETHERSCAN_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]

    if args.backend == "etherscan" and not keys:
        raise SystemExit("ERROR: etherscan backend needs ETHERSCAN_API_KEY or --etherscan-key")
    # Preset F: enrich when keys present; auto-off if no keys (RPC-only still works)
    enrich = bool(args.enrich_etherscan)
    if enrich and not keys:
        print(
            "WARN: no ETHERSCAN_API_KEY — enrichment off (preset A RPC still runs). "
            "Add keys to ~/.seed_hunter_keys for preset F.",
            file=sys.stderr,
        )
        enrich = False

    # One key for enrich path if multiple present (rotation inside client if all passed)
    rate = args.rate_limit if args.rate_limit is not None else DEFAULT_RATE_PER_KEY
    pf = args.progress_file or f"shard_{args.shard}_w{args.worker_id}.txt"

    return Config(
        shard=shard,
        worker_id=args.worker_id,
        num_workers=args.workers,
        chains=chains,
        api_keys=keys,
        rate_limit=rate,
        results_file=args.results_file,
        activity_file=args.activity_file,
        progress_file=pf,
        length=args.length,
        path=args.path,
        max_concurrent=max(1, args.max_concurrent),
        capital_only=bool(args.capital_only),
        min_balance=float(args.min_balance),
        backend=args.backend,
        check_mode=args.check_mode,
        batch_size=max(1, args.batch_size),
        save_activity=bool(args.save_activity),
        enrich_etherscan=enrich,
        rpc_rps=float(args.rpc_rps),
        rpc_urls_eth=args.rpc_url,
        unique_words=bool(args.unique_words),
    )


def load_int(path: str) -> Optional[int]:
    if not os.path.exists(path):
        return None
    try:
        return int(open(path, encoding="utf-8").read().strip())
    except Exception:
        return None


def save_int(path: str, val: int) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(val))
    os.replace(tmp, path)


def _parity_base(lo: int, parity: int) -> Optional[int]:
    if lo % 2 == parity:
        return lo
    return lo + 1 if (lo + 1) % 2 == parity else None


def _parity_count(lo: int, hi: int, parity: int) -> int:
    base = _parity_base(lo, parity)
    if base is None or base >= hi:
        return 0
    return ((hi - 1 - base) // 2) + 1


def initial_index(cfg: Config) -> Optional[int]:
    s = cfg.shard
    saved = load_int(cfg.progress_file)
    if saved is not None:
        if s.lo <= saved < s.hi and saved % 2 == s.parity:
            return saved

    base = _parity_base(s.lo, s.parity)
    if base is None or base >= s.hi:
        return None
    n = _parity_count(s.lo, s.hi, s.parity)
    if n <= 0:
        return None
    first_rank = cfg.worker_id
    if first_rank >= n:
        return None
    last_rank = first_rank + cfg.num_workers * ((n - 1 - first_rank) // cfg.num_workers)

    if s.direction > 0:
        return base + 2 * first_rank
    return base + 2 * last_rank


def next_index(cfg: Config, idx: int) -> Optional[int]:
    s = cfg.shard
    step = 2 * cfg.num_workers
    nxt = idx + s.direction * step
    if s.direction > 0:
        if nxt >= s.hi or nxt % 2 != s.parity:
            return None
    else:
        if nxt < s.lo or nxt % 2 != s.parity:
            return None
    return nxt


def _print_capital(hit: dict, shard: str, idx: int) -> None:
    bal = float(hit.get("balance_eth") or 0)
    nonce = hit.get("nonce", "?")
    print(f"\n{'=' * 80}")
    print(f"CAPITAL HIT [{hit.get('chain')}] {hit.get('address')} bal={bal} nonce={nonce}")
    print(f"shard={shard} idx={idx}")
    print(f"Phrase: {hit.get('phrase')}")
    print(f"{'=' * 80}\n")


def _print_activity(hit: dict, shard: str, idx: int) -> None:
    print(
        f"\n[ACTIVITY] [{hit.get('chain')}] {hit.get('address')} "
        f"nonce={hit.get('nonce')} bal={hit.get('balance_eth')} "
        f"shard={shard} idx={idx}"
    )
    print(f"Phrase: {hit.get('phrase')}")


def _status_path(progress_file: str) -> str:
    # shard_low_fwd_w0.txt → shard_low_fwd_w0.status.json
    if progress_file.endswith(".txt"):
        return progress_file[: -len(".txt")] + ".status.json"
    return progress_file + ".status.json"


def write_worker_status(
    cfg: Config,
    *,
    idx: int,
    phrase: str,
    walked: int,
    rpc_checked: int,
    skipped_unique: int,
    walk_rate: float,
    rpc_rate: float,
    capital_total: int,
    activity_total: int,
) -> None:
    """Atomic-ish status snapshot for status_shards.sh (best-effort)."""
    path = _status_path(cfg.progress_file)
    tmp = path + ".tmp"
    payload = {
        "shard": cfg.shard.name,
        "worker_id": cfg.worker_id,
        "workers": cfg.num_workers,
        "idx": idx,
        "phrase": phrase,
        "unique": words_all_unique(phrase) if phrase else None,
        "walked": walked,
        "rpc_checked": rpc_checked,
        "skipped_unique": skipped_unique,
        "walk_rate": round(walk_rate, 2),
        "rpc_rate": round(rpc_rate, 2),
        "capital": capital_total,
        "activity": activity_total,
        "ts": time.time(),
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


def _progress_line(
    cfg: Config,
    *,
    walked: int,
    rpc_checked: int,
    skipped_unique: int,
    walk_rate: float,
    rpc_rate: float,
    capital_total: int,
    activity_total: int,
    idx: int,
    phrase: str,
) -> None:
    # Keep phrase on same \r line (truncate) so status_shards can tail logs too.
    short = phrase if len(phrase) <= 80 else phrase[:77] + "..."
    sys.stdout.write(
        f"\r[{cfg.shard.name} w{cfg.worker_id}] walked={walked:,} "
        f"rpc={rpc_checked:,} skipped_unique={skipped_unique:,} "
        f"walk_rate={walk_rate:.2f}/s rpc_rate={rpc_rate:.2f}/s "
        f"capital={capital_total} activity={activity_total} "
        f"idx={idx} phrase={short}   "
    )
    sys.stdout.flush()
    write_worker_status(
        cfg,
        idx=idx,
        phrase=phrase,
        walked=walked,
        rpc_checked=rpc_checked,
        skipped_unique=skipped_unique,
        walk_rate=walk_rate,
        rpc_rate=rpc_rate,
        capital_total=capital_total,
        activity_total=activity_total,
    )


async def process_batch_rpc(
    cfg: Config,
    rpc,
    session: aiohttp.ClientSession,
    indices: Sequence[int],
) -> tuple[int, int, int]:
    """Derive + RPC-check a batch. Returns (capital_hits, activity_hits, skipped_unique)."""
    loop = asyncio.get_running_loop()
    entries = []
    addrs = []
    skipped = 0
    for idx in indices:
        phrase = entropy_index_to_phrase(idx, cfg.length)
        if cfg.unique_words and not words_all_unique(phrase):
            # Skip RPC; progress still advances via caller (index walk continues).
            skipped += 1
            continue
        addr = await loop.run_in_executor(None, derive_address_sync, phrase, cfg.path)
        if not addr:
            continue
        entry = {
            "phrase": phrase,
            "address": addr,
            "path": cfg.path,
            "index": idx,
            "timestamp": time.time(),
            "source": f"shard:{cfg.shard.name}",
        }
        entries.append(entry)
        addrs.append(addr)

    if not entries:
        return 0, 0, skipped

    by_addr = await rpc.check_addresses_batch(session, addrs, mode=cfg.check_mode)
    cap_n = 0
    act_n = 0

    for entry in entries:
        sigs = by_addr.get(entry["address"], [])
        capital, activity = signals_to_hits(
            entry,
            sigs,
            min_balance=cfg.min_balance,
            save_nonce_activity=cfg.save_activity,
            capital_only=cfg.capital_only,
        )
        for hit in capital:
            if cfg.enrich_etherscan and cfg.api_keys:
                hit = await enrich_hit_etherscan(hit, session, cfg.api_keys)
            # Dual-write: found_wallets_capital.jsonl + capital_seeds.jsonl
            append_capital_hit(cfg.results_file, hit)
            _print_capital(hit, cfg.shard.name, entry["index"])
            cap_n += 1
        if cfg.save_activity:
            for hit in activity:
                # Dual-write: found_wallets_activity.jsonl + activity_seeds.jsonl
                # Always includes phrase + address + nonce for GitHub archive
                append_activity_hit(cfg.activity_file, hit)
                _print_activity(hit, cfg.shard.name, entry["index"])
                act_n += 1
    return cap_n, act_n, skipped


async def process_one_etherscan(
    cfg: Config,
    client: EtherscanClient,
    session: aiohttp.ClientSession,
    idx: int,
) -> tuple[int, int]:
    """Returns (capital_hits, skipped_unique). Progress always advanced by caller."""
    phrase = entropy_index_to_phrase(idx, cfg.length)
    if cfg.unique_words and not words_all_unique(phrase):
        return 0, 1

    loop = asyncio.get_running_loop()
    addr = await loop.run_in_executor(None, derive_address_sync, phrase, cfg.path)
    if not addr:
        return 0, 0

    entry = {
        "phrase": phrase,
        "address": addr,
        "path": cfg.path,
        "index": idx,
        "timestamp": time.time(),
        "source": f"shard:{cfg.shard.name}",
    }
    all_chains = {**FREE_TIER_CHAINS, **PAID_TIER_CHAINS}
    chains = {n: all_chains[n] for n in cfg.chains if n in all_chains}
    if not chains:
        return 0, 0

    hits = await check_address_all_chains(
        client,
        session,
        entry,
        chains,
        tx_only=not cfg.capital_only,
        capital_only=cfg.capital_only,
        min_balance=cfg.min_balance,
    )
    n = 0
    for hit in hits:
        bal = float(hit.get("balance_eth") or 0)
        if cfg.capital_only and bal <= cfg.min_balance:
            continue
        hit = {**hit, "hit_type": "capital"}
        append_capital_hit(cfg.results_file, hit)
        _print_capital(hit, cfg.shard.name, idx)
        n += 1
    return n, 0


async def run(cfg: Config) -> int:
    s = cfg.shard
    print("=== SEED SHARD (RPC-first capital + nonce) ===")
    print(f"Shard: {s.name}  range=[{s.lo:,}, {s.hi:,})  dir={s.direction:+d}  parity={s.parity}")
    print(f"Worker: {cfg.worker_id}/{cfg.num_workers}")
    print(f"Backend: {cfg.backend}  check_mode={cfg.check_mode}  batch={cfg.batch_size}")
    print(f"Chains: {', '.join(cfg.chains)}")
    print(f"Unique words only: {cfg.unique_words}  (--unique-words / --no-unique-words)")
    print(f"Capital file: {cfg.results_file}  (+ capital_seeds.jsonl)")
    if cfg.save_activity:
        print(f"Activity file (nonce>0): {cfg.activity_file}  (+ activity_seeds.jsonl)")
    print(f"Enrich Etherscan on hits: {cfg.enrich_etherscan}  keys={len(cfg.api_keys)}")
    print(f"Progress: {cfg.progress_file}")
    print("-" * 72)

    idx = initial_index(cfg)
    if idx is None:
        print("No indices for this worker/shard — exiting.")
        return 0

    walked = 0  # entropy indices visited (includes unique-word skips)
    rpc_checked = 0  # phrases actually sent to RPC / Etherscan
    skipped_unique = 0
    capital_total = 0
    activity_total = 0
    t0 = time.time()

    connector_limit = max(16, cfg.max_concurrent * 2 + cfg.batch_size)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        connector=aiohttp.TCPConnector(limit=connector_limit, ttl_dns_cache=300),
    ) as session:
        if cfg.backend == "rpc":
            overrides = {}
            if cfg.rpc_urls_eth:
                overrides["ethereum"] = cfg.rpc_urls_eth
            rpc = build_rpc_client(cfg.chains, rpc_overrides=overrides, max_rps=cfg.rpc_rps)
            print(f"RPC chains ready: {', '.join(rpc.chains)}")

            batch_idx: List[int] = []
            while idx is not None or batch_idx:
                while idx is not None and len(batch_idx) < cfg.batch_size:
                    batch_idx.append(idx)
                    idx = next_index(cfg, idx)

                if not batch_idx:
                    break

                cap, act, skip = await process_batch_rpc(cfg, rpc, session, batch_idx)
                capital_total += cap
                activity_total += act
                skipped_unique += skip
                walked += len(batch_idx)
                rpc_checked += max(0, len(batch_idx) - skip)

                # Progress = next index after this batch (or last if done)
                cur_idx = idx if idx is not None else batch_idx[-1]
                save_int(cfg.progress_file, cur_idx)
                batch_idx = []

                if walked % (cfg.batch_size * 2) == 0 or walked <= cfg.batch_size:
                    elapsed = time.time() - t0
                    walk_rate = walked / elapsed if elapsed > 0 else 0.0
                    rpc_rate = rpc_checked / elapsed if elapsed > 0 else 0.0
                    try:
                        phrase = entropy_index_to_phrase(cur_idx, cfg.length)
                    except Exception:
                        phrase = "?"
                    _progress_line(
                        cfg,
                        walked=walked,
                        rpc_checked=rpc_checked,
                        skipped_unique=skipped_unique,
                        walk_rate=walk_rate,
                        rpc_rate=rpc_rate,
                        capital_total=capital_total,
                        activity_total=activity_total,
                        idx=cur_idx,
                        phrase=phrase,
                    )
        else:
            client = EtherscanClient(cfg.api_keys, cfg.rate_limit)
            while idx is not None:
                hits, skip = await process_one_etherscan(cfg, client, session, idx)
                capital_total += hits
                skipped_unique += skip
                walked += 1
                if skip == 0:
                    rpc_checked += 1
                cur_idx = idx
                try:
                    phrase = entropy_index_to_phrase(cur_idx, cfg.length)
                except Exception:
                    phrase = "?"
                nxt = next_index(cfg, idx)
                if nxt is not None:
                    save_int(cfg.progress_file, nxt)
                else:
                    save_int(cfg.progress_file, idx)
                idx = nxt
                if walked % 10 == 0:
                    elapsed = time.time() - t0
                    walk_rate = walked / elapsed if elapsed > 0 else 0.0
                    rpc_rate = rpc_checked / elapsed if elapsed > 0 else 0.0
                    show_idx = load_int(cfg.progress_file) or cur_idx
                    try:
                        phrase = entropy_index_to_phrase(show_idx, cfg.length)
                    except Exception:
                        phrase = "?"
                    _progress_line(
                        cfg,
                        walked=walked,
                        rpc_checked=rpc_checked,
                        skipped_unique=skipped_unique,
                        walk_rate=walk_rate,
                        rpc_rate=rpc_rate,
                        capital_total=capital_total,
                        activity_total=activity_total,
                        idx=show_idx,
                        phrase=phrase,
                    )

    print(
        f"\n[{s.name} w{cfg.worker_id}] done. walked={walked:,} "
        f"rpc={rpc_checked:,} skipped_unique={skipped_unique:,} "
        f"capital={capital_total} activity={activity_total}"
    )
    return 0


def main() -> int:
    args = parse_args()
    cfg = resolve_config(args)
    try:
        return asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
