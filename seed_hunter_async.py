#!/usr/bin/env python3
"""
Minimal BIP39 helpers used by seed_shard.py (unique-words hunt).

Full historical async hunter lives in sister all-words repo; this file ships the
derive / entropy-index helpers the shard runner imports.

If you need the full async scanner CLI, copy from SirCharan/seed-hunter or re-run
Documents/_bootstrap_seed_hunter_unique.sh which overwrites this from the working tree.
"""

from __future__ import annotations

import sys
from typing import Optional

try:
    from eth_account import Account
    from mnemonic import Mnemonic
except ImportError as e:
    missing = str(e).split()[-1] if "No module named" in str(e) else "required package"
    print("ERROR: Missing dependency:", missing)
    print("  pip install eth-account mnemonic")
    sys.exit(1)

Account.enable_unaudited_hdwallet_features()

MNEMO = Mnemonic("english")
DEFAULT_PATH = "m/44'/60'/0'/0/0"
ENTROPY_BITS_BY_LENGTH = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}
TEST_MNEMONIC_LIMIT = 100_000


def derive_address_sync(phrase: str, path: str) -> Optional[str]:
    """Returns checksummed address or None."""
    try:
        Account.enable_unaudited_hdwallet_features()
        acct = Account.from_mnemonic(phrase, account_path=path)
        return acct.address
    except Exception:
        return None


def entropy_bits_for_length(length: int) -> int:
    try:
        return ENTROPY_BITS_BY_LENGTH[length]
    except KeyError as exc:
        supported = ", ".join(str(n) for n in sorted(ENTROPY_BITS_BY_LENGTH))
        raise ValueError(f"Unsupported mnemonic length {length}. Supported: {supported}") from exc


def valid_mnemonic_space(length: int, test_mode: bool) -> int:
    """Total number of valid BIP39 mnemonics to scan."""
    if test_mode:
        return TEST_MNEMONIC_LIMIT
    return 2 ** entropy_bits_for_length(length)


def entropy_index_to_phrase(idx: int, length: int) -> str:
    """Map entropy index 0..2^bits-1 to a checksum-valid BIP39 mnemonic."""
    bits = entropy_bits_for_length(length)
    if idx < 0 or idx >= (1 << bits):
        raise ValueError(f"Entropy index {idx} out of range for {length}-word mnemonics")
    entropy = idx.to_bytes(bits // 8, byteorder="big")
    return MNEMO.to_mnemonic(entropy)
