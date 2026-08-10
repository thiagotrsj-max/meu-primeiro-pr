"""Bot separado (DM) que manda o sinal pronto pra você e espera Aprovar/Rejeitar.

Roda via python-telegram-bot. Mantém um dicionário de "pendências" — cada sinal
aguardando decisão vira um asyncio.Future que telegram_listener.py aguarda.
"""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from config import Config
from risk_manager import RiskDecision
from signal_parser import Signal

_pending: dict[str, asyncio.Future] = {}


def format_proposal(signal: Signal, decision: RiskDecision) -> str:
    targets_txt = "\n".join(
        f"  T{i+1}: {t.price} ({t.pct}%)" for i, t in enumerate(signal.targets)
    )
    return (
        f"🔔 Sinal #{signal.signal_id} — {signal.canal}\n\n"
        f"Moeda: {signal.coin}\n"
        f"Lado: {signal.side} ({signal.market})\n"
        f"Entrada: {signal.entry_low} - {signal.entry_high}\n"
        f"Stop: {signal.stop_loss} ({signal.stop_loss_pct}%)\n"
        f"Alvos:\n{targets_txt}\n\n"
        f"--- Proposta calculada pelo bot ---\n"
        f"Alavancagem usada: {decision.leverage}x (teto do seu config)\n"
        f"R/R (alvo 1, calculado): {decision.rr_used:.2f}\n"
        f"Quantidade: {decision.quantity:.4f} {signal.coin}\n"
        f"Notional: ${decision.notional_usdt:.2f}\n"
        f"Margem necessária: ${decision.margin_required_usdt:.2f}\n"
        f"Risco assumido: ${decision.risk_amount_usdt:.2f}\n\n"
        f"Aprovar esta ordem?"
    )


async def request_approval(
    app: Application,
    config: Config,
    signal: Signal,
    decision: RiskDecision,
) -> bool | None:
    """Manda a proposta e espera clique em Aprovar/Rejeitar (ou timeout).

    Retorna True (aprovado), False (rejeitado explicitamente) ou None (expirou
    sem resposta) — os três casos são distintos e devem ser logados de forma
    diferente por quem chama.
    """
    key = signal.signal_id
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending[key] = future

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Aprovar", callback_data=f"approve:{key}"),
                InlineKeyboardButton("❌ Rejeitar", callback_data=f"reject:{key}"),
            ]
        ]
    )
    await app.bot.send_message(
        chat_id=config.approval_chat_id,
        text=format_proposal(signal, decision),
        reply_markup=keyboard,
    )

    try:
        return await asyncio.wait_for(future, timeout=config.approval_timeout_seconds)
    except asyncio.TimeoutError:
        _pending.pop(key, None)
        await app.bot.send_message(
            chat_id=config.approval_chat_id,
            text=f"⌛ Sinal #{key} expirou sem resposta — não executado.",
        )
        return None


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, key = query.data.split(":", 1)
    future = _pending.pop(key, None)
    if future is None or future.done():
        await query.edit_message_text(query.message.text + "\n\n(já resolvido ou expirado)")
        return
    approved = action == "approve"
    future.set_result(approved)
    status = "✅ Aprovado" if approved else "❌ Rejeitado"
    await query.edit_message_text(query.message.text + f"\n\n{status} por você.")


def build_approval_app(config: Config) -> Application:
    app = Application.builder().token(config.approval_bot_token).build()
    app.add_handler(CallbackQueryHandler(_on_callback))
    return app
