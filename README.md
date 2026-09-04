# seed-hunter-unique

**Unique-words only** BIP39 seed hunt (Mac / Adaptive).

This repo is the Mac-oriented **unique-words** stack: phrases with any repeated BIP39 word are skipped for RPC (progress still advances). Default everywhere is `UNIQUE_WORDS=1` / `--unique-words` (`True`).

## Sister repo — do not merge blindly

| Repo | Role |
|------|------|
| **SirCharan/seed-hunter-unique** (this) | Unique-words only — Mac primary |
| **SirCharan/seed-hunter** | **All-words** checks — separate agent / Linux |

Do **not** merge these repos blindly. Progress files, worker striping, and search semantics differ.

## Capital hits → this repo only

On `balance > 0`, hunters append:

- `found_wallets_capital.jsonl`
- `capital_seeds.jsonl`
- `capital_hits.md`

Then `git_push_capital.py` best-effort `git add` + `commit` + `push` to **`origin/main` of this repo** (`seed-hunter-unique`). It **refuses** if `origin` points at the sister all-words `seed-hunter` repo. Local files are kept if git fails.

## Quick start

```bash
git clone https://github.com/SirCharan/seed-hunter-unique.git
cd seed-hunter-unique
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### Mac (primary)

```bash
./start_mac_primary.sh
# or force restart:
FORCE_RESTART=1 ./start_mac_primary.sh
```

- Uses `caffeinate` to reduce idle sleep
- Default `WORKERS_PER_SHARD=2`
- **`EXPECT_SHARD_PROCS=8`** on Mac (2 workers × 4 shards)

### Linux

```bash
./start_linux_primary.sh
```

Default `WORKERS_PER_SHARD=4` (16 processes). Still `UNIQUE_WORDS=1` by default.

### Status / stop

```bash
./status_shards.sh
./kill_shards.sh
```

## Unique-words filter (default ON)

- `UNIQUE_WORDS=1` or `--unique-words` (Python default `True`): skip RPC for phrases with repeated BIP39 words
- Disable: `UNIQUE_WORDS=0` or `--no-unique-words` (not recommended for this repo’s purpose)

## Defaults (Mac)

| Env | Default | Notes |
|-----|---------|--------|
| `UNIQUE_WORDS` | `1` | Unique-words only |
| `WORKERS_PER_SHARD` | `2` | Mac-safe |
| `EXPECT_SHARD_PROCS` | `8` | 2 × 4 shards |
| `BACKEND` | `rpc` | Preset A |
| `ENRICH_ETHERSCAN` | `1` | Preset F when keys present |

## Full Mac setup helper

```bash
./_setup_mac_full.sh
```

Clones **this** repo to `~/seed-hunter-mac` (not `seed-hunter`), installs venv, starts Mac primary.

## License / honesty

Brute-forcing BIP39 space is astronomically unlikely to succeed. This is an experimental adaptive hunt, not a get-rich scheme.
