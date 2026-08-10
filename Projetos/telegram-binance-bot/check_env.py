"""Confere se o .env está completo, sem nunca imprimir valores sensíveis.

Uso:
    python check_env.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

# Windows costuma abrir o console em cp1252, que não tem emoji -> força UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Campos sensíveis: só dizemos se estão preenchidos ou não, nunca o valor.
SENSITIVE = {
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "APPROVAL_BOT_TOKEN",
    "APPROVAL_CHAT_ID",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
}

# Campos não sensíveis: ok mostrar o valor, ajuda a conferir se está certo.
VISIBLE = {
    "TELEGRAM_API_ID",
    "TELEGRAM_SOURCE_CHAT_TITLE",
    "BINANCE_TESTNET",
    "DRY_RUN",
    "MAX_RISK_PER_TRADE_PCT",
    "MAX_LEVERAGE",
    "MIN_RR_RATIO",
    "MAX_CONCURRENT_POSITIONS",
    "COIN_WHITELIST",
    "APPROVAL_TIMEOUT_SECONDS",
}

REQUIRED = {
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "APPROVAL_BOT_TOKEN",
    "APPROVAL_CHAT_ID",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
}


def main():
    if not ENV_PATH.exists():
        print("❌ Não encontrei um arquivo .env em", ENV_PATH)
        print("   Rode: cp .env.example .env")
        return

    values = dotenv_values(ENV_PATH)
    missing = []

    print(f"Lendo {ENV_PATH}\n")
    for key in sorted(SENSITIVE | VISIBLE):
        val = values.get(key, "")
        filled = bool(val and val.strip())
        if not filled and key in REQUIRED:
            missing.append(key)

        if key in SENSITIVE:
            status = "✅ preenchido" if filled else "⬜ vazio"
            print(f"  {key:<28} {status}")
        else:
            shown = val if filled else "(vazio)"
            print(f"  {key:<28} = {shown}")

    print()
    if missing:
        print("❌ Ainda faltam estes campos obrigatórios:")
        for m in missing:
            print(f"   - {m}")
    else:
        print("✅ Todos os campos obrigatórios estão preenchidos.")

    testnet = (values.get("BINANCE_TESTNET", "true") or "true").strip().lower() in ("1", "true", "yes")
    dry_run = (values.get("DRY_RUN", "true") or "true").strip().lower() in ("1", "true", "yes")
    if not testnet or not dry_run:
        print("\n⚠️  Atenção: TESTNET ou DRY_RUN estão desligados — modo com risco real ativo.")
    else:
        print("\n🛡️  Modo seguro: TESTNET=true e DRY_RUN=true.")


if __name__ == "__main__":
    main()
