"""PayWall: an embeddable, closed-loop wallet backed by a double-entry ledger."""

from importlib.metadata import version

from paywall.app import PayWall
from paywall.auth import Principal, Scope
from paywall.config import Settings
from paywall.core.results import Transaction, TransactionPage, Wallet, WalletEntry
from paywall.db.models import AccountStatus, EntryType
from paywall.errors import ErrorCode, PayWallError

__version__ = version("paywall")

__all__ = [
    "AccountStatus",
    "EntryType",
    "ErrorCode",
    "PayWall",
    "PayWallError",
    "Principal",
    "Scope",
    "Settings",
    "Transaction",
    "TransactionPage",
    "Wallet",
    "WalletEntry",
]
