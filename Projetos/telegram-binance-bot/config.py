"""Carrega e valida a configuração a partir do .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass(frozen=True)
class Config:
    # Telegram (conta pessoal)
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telegram_source_chat_title: str

    # Bot de aprovação
    approval_bot_token: str
    approval_chat_id: int
    approval_timeout_seconds: int

    # Binance
    binance_testnet: bool
    binance_api_key: str
    binance_api_secret: str
    dry_run: bool

    # Risco
    max_risk_per_trade_pct: float
    max_leverage: int
    min_rr_ratio: float
    max_concurrent_positions: int
    coin_whitelist: tuple[str, ...] = field(default_factory=tuple)

    @property
    def session_path(self) -> str:
        return str(BASE_DIR / "telegram_user.session")


def load_config() -> Config:
    missing = []
    required = [
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PHONE",
        "APPROVAL_BOT_TOKEN",
        "APPROVAL_CHAT_ID",
    ]
    for name in required:
        if not os.getenv(name):
            missing.append(name)
    if missing:
        raise RuntimeError(
            "Faltam variáveis obrigatórias no .env: " + ", ".join(missing) +
            "\nVeja .env.example para instruções."
        )

    whitelist_raw = os.getenv("COIN_WHITELIST", "").strip()
    whitelist = tuple(c.strip().upper() for c in whitelist_raw.split(",") if c.strip())

    dry_run = _bool("DRY_RUN", True)
    testnet = _bool("BINANCE_TESTNET", True)
    if not dry_run and not testnet:
        # Segurança extra: avisa alto e claro no log quando o modo é "vale tudo".
        print("!" * 70)
        print("ATENÇÃO: DRY_RUN=false e BINANCE_TESTNET=false.")
        print("Este processo pode enviar ordens REAIS com dinheiro REAL.")
        print("!" * 70)

    return Config(
        telegram_api_id=_int("TELEGRAM_API_ID", 0),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
        telegram_phone=os.getenv("TELEGRAM_PHONE", ""),
        telegram_source_chat_title=os.getenv("TELEGRAM_SOURCE_CHAT_TITLE", ""),
        approval_bot_token=os.getenv("APPROVAL_BOT_TOKEN", ""),
        approval_chat_id=_int("APPROVAL_CHAT_ID", 0),
        approval_timeout_seconds=_int("APPROVAL_TIMEOUT_SECONDS", 300),
        binance_testnet=testnet,
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        dry_run=dry_run,
        max_risk_per_trade_pct=_float("MAX_RISK_PER_TRADE_PCT", 1.0),
        max_leverage=_int("MAX_LEVERAGE", 5),
        min_rr_ratio=_float("MIN_RR_RATIO", 1.0),
        max_concurrent_positions=_int("MAX_CONCURRENT_POSITIONS", 3),
        coin_whitelist=whitelist,
    )
