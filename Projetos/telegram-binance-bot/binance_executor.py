"""Execução de ordens na Binance Futures (USDT-M).

Dois níveis de segurança independentes, controlados via .env:
- BINANCE_TESTNET: usa a rede de testes da Binance (dinheiro fake) em vez da real.
- DRY_RUN: se true, NENHUMA chamada de ordem é enviada — só loga o que seria feito.
    DRY_RUN funciona mesmo sem chaves de API válidas, então é seguro pra testar
    o pipeline inteiro (parser + risco + aprovação) antes de plugar a Binance de fato.

IMPORTANTE: crie a API key na Binance com permissão apenas de "Futures Trading",
SEM permissão de saque ("Enable Withdrawals" desligado), e restrinja por IP sempre
que possível.
"""
from __future__ import annotations

from dataclasses import dataclass

from binance.client import Client

from config import Config
from signal_parser import Signal


@dataclass
class ExecutionResult:
    success: bool
    message: str
    order_ids: list[str]


def _make_client(config: Config) -> Client:
    client = Client(config.binance_api_key, config.binance_api_secret)
    if config.binance_testnet:
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    return client


def get_account_balance_usdt(config: Config) -> float:
    if config.dry_run:
        # Sem chamada real de API em dry-run; usa um valor fictício plausível
        # só para a gestão de risco ter algo pra calcular. Ajuste se quiser.
        return 1000.0
    client = _make_client(config)
    balances = client.futures_account_balance()
    for b in balances:
        if b["asset"] == "USDT":
            return float(b["balance"])
    return 0.0


def get_open_positions_count(config: Config) -> int:
    if config.dry_run:
        return 0
    client = _make_client(config)
    positions = client.futures_position_information()
    return sum(1 for p in positions if float(p["positionAmt"]) != 0)


def execute_signal(
    signal: Signal,
    *,
    config: Config,
    quantity: float,
    leverage: int,
) -> ExecutionResult:
    symbol = f"{signal.coin.upper()}USDT"
    side = "BUY" if signal.side == "LONG" else "SELL"
    close_side = "SELL" if signal.side == "LONG" else "BUY"
    qty = round(quantity, 3)  # ajuste conforme stepSize do par; ver README

    if config.dry_run:
        plan = (
            f"[DRY_RUN] Entraria {side} {qty} {symbol} @ ~{signal.entry_mid} "
            f"(alavancagem {leverage}x), stop {signal.stop_loss}, "
            f"{len(signal.targets)} alvo(s)."
        )
        print(plan)
        return ExecutionResult(True, plan, [])

    client = _make_client(config)
    order_ids: list[str] = []
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        entry_order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=str(signal.entry_mid),
        )
        order_ids.append(str(entry_order["orderId"]))

        stop_order = client.futures_create_order(
            symbol=symbol,
            side=close_side,
            type="STOP_MARKET",
            stopPrice=str(signal.stop_loss),
            closePosition=True,
        )
        order_ids.append(str(stop_order["orderId"]))

        # Take-profit escalonado: divide a quantidade igualmente entre os alvos.
        if signal.targets:
            qty_per_target = round(qty / len(signal.targets), 3)
            for target in signal.targets:
                tp_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=str(target.price),
                    quantity=qty_per_target,
                    reduceOnly=True,
                )
                order_ids.append(str(tp_order["orderId"]))

        return ExecutionResult(True, "Ordens enviadas com sucesso.", order_ids)
    except Exception as exc:  # noqa: BLE001 - queremos capturar e logar qualquer falha da API
        return ExecutionResult(False, f"Erro ao enviar ordens: {exc}", order_ids)
