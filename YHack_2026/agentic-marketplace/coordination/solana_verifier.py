"""Solana verification layer — commits signal hashes and debate summaries on-chain."""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field

from utils.logger import Logger

# Solana imports — gracefully degrade if not installed
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction
    from solders.message import Message as SolMessage
    from solana.rpc.api import Client as SolanaClient
    from solders.hash import Hash
    from solders.instruction import Instruction, AccountMeta
    SOLANA_AVAILABLE = True
except ImportError:
    SOLANA_AVAILABLE = False


@dataclass
class VerificationRecord:
    """A record of what was committed on-chain."""
    data_hash: str
    label: str
    tx_signature: str = ""
    verified: bool = False
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "data_hash": self.data_hash,
            "label": self.label,
            "tx_signature": self.tx_signature,
            "verified": self.verified,
            "timestamp": self.timestamp,
        }


@dataclass
class VerificationReport:
    """Full verification report for a pipeline cycle."""
    chain: str = "solana"
    network: str = "devnet"
    signals_committed: list[VerificationRecord] = field(default_factory=list)
    summary_committed: VerificationRecord | None = None
    all_verified: bool = False

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "network": self.network,
            "signals_on_chain": len(self.signals_committed) > 0,
            "signal_count": len(self.signals_committed),
            "signals": [s.to_dict() for s in self.signals_committed],
            "summary_on_chain": self.summary_committed is not None,
            "summary": self.summary_committed.to_dict() if self.summary_committed else None,
            "all_verified": self.all_verified,
        }


class SolanaVerifier:
    """Commits data hashes to Solana for transparent verification."""

    # Memo program ID (SPL Memo v2)
    MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

    def __init__(self, rpc_url: str = "https://api.devnet.solana.com", private_key: str | None = None):
        self.rpc_url = rpc_url
        self.report = VerificationReport()

        if not SOLANA_AVAILABLE:
            Logger.warning("Solana libraries not installed — running in hash-only mode (no on-chain commits)")
            self.client = None
            self.keypair = None
            return

        self.client = SolanaClient(rpc_url)

        if private_key:
            self.keypair = Keypair.from_base58_string(private_key)
        else:
            self.keypair = Keypair()
            Logger.info(f"Generated ephemeral Solana keypair: {self.keypair.pubkey()}")

    @staticmethod
    def hash_data(data: str | dict | list) -> str:
        """SHA-256 hash of JSON-serialized data."""
        if not isinstance(data, str):
            data = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def commit_signals(self, signals_data: list[dict], store_id: str) -> VerificationRecord:
        """Hash and commit a store's signals on-chain."""
        data_hash = self.hash_data(signals_data)
        label = f"signals:{store_id}"
        record = VerificationRecord(
            data_hash=data_hash,
            label=label,
            timestamp=time.time(),
        )

        if self.client and self.keypair:
            tx_sig = self._send_memo(f"{label}|{data_hash}")
            if tx_sig:
                record.tx_signature = tx_sig
                record.verified = True

        self.report.signals_committed.append(record)
        return record

    def commit_summary(self, summary_data: dict) -> VerificationRecord:
        """Hash and commit the debate summary on-chain."""
        data_hash = self.hash_data(summary_data)
        label = "debate_summary"
        record = VerificationRecord(
            data_hash=data_hash,
            label=label,
            timestamp=time.time(),
        )

        if self.client and self.keypair:
            tx_sig = self._send_memo(f"{label}|{data_hash}")
            if tx_sig:
                record.tx_signature = tx_sig
                record.verified = True

        self.report.summary_committed = record
        self.report.all_verified = all(
            r.verified for r in self.report.signals_committed
        ) and record.verified

        return record

    def _send_memo(self, memo_text: str) -> str:
        """Send a memo transaction to Solana with the given text."""
        try:
            memo_program = Pubkey.from_string(self.MEMO_PROGRAM_ID)
            memo_data = memo_text.encode("utf-8")

            ix = Instruction(
                program_id=memo_program,
                accounts=[AccountMeta(pubkey=self.keypair.pubkey(), is_signer=True, is_writable=True)],
                data=memo_data,
            )

            recent_blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = SolMessage.new_with_blockhash(
                [ix],
                self.keypair.pubkey(),
                recent_blockhash,
            )
            tx = Transaction.new_unsigned(msg)
            tx.sign([self.keypair], recent_blockhash)

            result = self.client.send_transaction(tx)
            sig = str(result.value)
            Logger.success(f"On-chain memo committed: {sig[:20]}...")
            return sig

        except Exception as e:
            Logger.warning(f"Solana commit failed (hash still recorded locally): {e}")
            return ""

    def get_report(self) -> VerificationReport:
        return self.report
