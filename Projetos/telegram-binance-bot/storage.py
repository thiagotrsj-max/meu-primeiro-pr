"""Log local (SQLite) de todo sinal visto e toda decisão tomada.

Serve tanto de auditoria (o que o bot fez e por quê) quanto de fonte para
calcular quantas posições estão abertas no momento.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "signals.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    decision TEXT NOT NULL,        -- rejected_risk | pending_approval | approved | rejected_user | expired | executed | error
    decision_reason TEXT,
    order_ids_json TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_signal_seen(signal, decision: str, reason: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO signals (signal_id, coin, side, raw_text, parsed_json, "
            "decision, decision_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal.signal_id,
                signal.coin,
                signal.side,
                signal.raw_text,
                json.dumps(asdict(signal), default=str),
                decision,
                reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def update_decision(row_id: int, decision: str, reason: str = "", order_ids: list | None = None):
    with _conn() as conn:
        conn.execute(
            "UPDATE signals SET decision = ?, decision_reason = ?, order_ids_json = ?, "
            "decided_at = ? WHERE id = ?",
            (
                decision,
                reason,
                json.dumps(order_ids or []),
                datetime.now(timezone.utc).isoformat(),
                row_id,
            ),
        )


def count_open_positions() -> int:
    """Aproximação simples: sinais marcados como 'executed' que ainda não foram
    fechados manualmente no registro (ver README - fechamento é responsabilidade
    do operador registrar, ou trocar por consulta direta à API da Binance)."""
    with _conn() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM signals WHERE decision = 'executed'")
        return cur.fetchone()[0]
