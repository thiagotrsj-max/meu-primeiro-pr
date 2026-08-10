"""Escuta o canal/grupo de sinais usando SUA conta pessoal do Telegram (Telethon).

Primeiro uso: pede o código de login que chega no seu Telegram (interativo, uma
única vez). Depois disso, a sessão fica salva em telegram_user.session (local,
gitignored) e os próximos runs não pedem login de novo.

Lê o chat pelo TÍTULO configurado em TELEGRAM_SOURCE_CHAT_TITLE (mais robusto
que hardcodar um ID de canal), então funciona igual para grupos com tópicos
(como "STC-54", "STC-258" etc. dentro do mesmo grupo) — qualquer mensagem que
"parecer" um sinal, em qualquer tópico, é capturada.
"""
from __future__ import annotations

import logging

from telethon import TelegramClient, events

from config import Config
from signal_parser import ParseError, looks_like_signal, parse_signal

log = logging.getLogger("telegram_listener")


async def find_source_chat(client: TelegramClient, title: str):
    async for dialog in client.iter_dialogs():
        if dialog.name == title:
            return dialog.entity
    raise RuntimeError(
        f"Não encontrei nenhum chat com o título exato '{title}'. "
        "Confira TELEGRAM_SOURCE_CHAT_TITLE no .env (precisa ser sua conta "
        "logada já ser membro do grupo/canal)."
    )


def build_client(config: Config) -> TelegramClient:
    return TelegramClient(config.session_path, config.telegram_api_id, config.telegram_api_hash)


async def run_listener(client: TelegramClient, config: Config, on_signal):
    """on_signal(raw_text: str) é chamado (async) pra cada mensagem que parece sinal."""
    chat = await find_source_chat(client, config.telegram_source_chat_title)
    log.info("Monitorando chat: %s (id=%s)", config.telegram_source_chat_title, chat.id)

    @client.on(events.NewMessage(chats=chat))
    async def _handler(event):
        text = event.raw_text or ""
        if not looks_like_signal(text):
            return
        try:
            signal = parse_signal(text)
        except ParseError as exc:
            log.warning("Mensagem parecia sinal mas falhou no parse: %s", exc)
            return
        await on_signal(signal)

    log.info("Listener ativo. Aguardando sinais...")
    await client.run_until_disconnected()
