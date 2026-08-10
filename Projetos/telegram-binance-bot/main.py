"""Orquestra tudo: Telegram (sinais) -> parser -> risco -> aprovação -> Binance.

Uso:
    python main.py

Na primeira vez, o Telethon vai pedir o código de login da sua conta Telegram
no terminal (interativo). Depois disso roda sozinho, escutando o chat configurado.
"""
from __future__ import annotations

import asyncio
import logging

import binance_executor
import risk_manager
import storage
from approval_bot import build_approval_app, request_approval
from config import load_config
from telegram_listener import build_client, run_listener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def handle_signal(signal, *, config, approval_app):
    log.info("Sinal recebido: #%s %s %s", signal.signal_id, signal.coin, signal.side)

    balance = binance_executor.get_account_balance_usdt(config)
    open_positions = binance_executor.get_open_positions_count(config)

    decision = risk_manager.evaluate(
        signal,
        config=config,
        account_balance_usdt=balance,
        open_positions_count=open_positions,
    )

    if not decision.approved:
        log.info("Sinal #%s rejeitado pela gestão de risco: %s", signal.signal_id, decision.reason)
        storage.log_signal_seen(signal, "rejected_risk", decision.reason)
        return

    row_id = storage.log_signal_seen(signal, "pending_approval", decision.reason)

    approved = await request_approval(approval_app, config, signal, decision)
    if approved is None:
        storage.update_decision(row_id, "expired")
        return
    if approved is False:
        storage.update_decision(row_id, "rejected_user")
        return

    result = binance_executor.execute_signal(
        signal, config=config, quantity=decision.quantity, leverage=decision.leverage
    )
    if result.success:
        storage.update_decision(row_id, "executed", result.message, result.order_ids)
        await approval_app.bot.send_message(
            chat_id=config.approval_chat_id,
            text=f"✅ Sinal #{signal.signal_id} executado.\n{result.message}",
        )
    else:
        storage.update_decision(row_id, "error", result.message)
        await approval_app.bot.send_message(
            chat_id=config.approval_chat_id,
            text=f"⚠️ Falha ao executar sinal #{signal.signal_id}: {result.message}",
        )


async def main():
    config = load_config()
    log.info(
        "Config carregada. TESTNET=%s DRY_RUN=%s MAX_RISK=%.2f%% MAX_LEVERAGE=%dx MIN_RR=%.2f",
        config.binance_testnet,
        config.dry_run,
        config.max_risk_per_trade_pct,
        config.max_leverage,
        config.min_rr_ratio,
    )
    if not config.dry_run and not config.binance_testnet:
        log.warning("MODO LIVE REAL ATIVO — ordens serão enviadas com dinheiro de verdade.")

    approval_app = build_approval_app(config)
    await approval_app.initialize()
    await approval_app.start()
    await approval_app.updater.start_polling()

    tg_client = build_client(config)
    await tg_client.start(phone=config.telegram_phone)

    async def on_signal(signal):
        await handle_signal(signal, config=config, approval_app=approval_app)

    try:
        await run_listener(tg_client, config, on_signal)
    finally:
        await approval_app.updater.stop()
        await approval_app.stop()
        await approval_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
