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
from decimal import Decimal

from binance.client import Client

from config import Config
from signal_parser import Signal


@dataclass
class ExecutionResult:
    success: bool
    message: str
    order_ids: list[str]


@dataclass
class SymbolFilters:
    step_size: str  # menor incremento de quantidade aceito pelo par
    tick_size: str  # menor incremento de preço aceito pelo par


_filters_cache: dict[str, SymbolFilters] = {}


def _make_client(config: Config) -> Client:
    client = Client(config.binance_api_key, config.binance_api_secret)
    if config.binance_testnet:
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    return client


def get_symbol_filters(client: Client, symbol: str) -> SymbolFilters:
    """Busca (e cacheia) stepSize/tickSize reais do par na Binance.

    Cada par futuro tem sua própria precisão — mandar uma ordem com mais casas
    decimais do que o permitido é rejeitado pela API. Isto substitui o
    arredondamento genérico fixo que era usado antes.
    """
    if symbol in _filters_cache:
        return _filters_cache[symbol]

    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            step_size = "1"
            tick_size = "1"
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    step_size = f["stepSize"]
                elif f["filterType"] == "PRICE_FILTER":
                    tick_size = f["tickSize"]
            filters = SymbolFilters(step_size=step_size, tick_size=tick_size)
            _filters_cache[symbol] = filters
            return filters

    raise ValueError(f"Símbolo {symbol} não encontrado na Binance Futures.")


def round_to_step(value: float, step: str) -> float:
    """Arredonda 'value' para baixo, para o múltiplo válido mais próximo de 'step'.

    Ex.: round_to_step(7369.1968, "0.001") -> 7369.196
         round_to_step(0.022618, "0.00001") -> 0.02261
    """
    d_value = Decimal(str(value))
    d_step = Decimal(step)
    if d_step == 0:
        return value
    steps = (d_value / d_step).to_integral_value(rounding="ROUND_DOWN")
    return float(steps * d_step)


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

    if config.dry_run:
        # Sem chamada de API mesmo pra pegar filtros do símbolo - arredondamento
        # aqui é só ilustrativo pro log, não precisa ser exato.
        qty = round(quantity, 3)
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
        filters = get_symbol_filters(client, symbol)
        qty = round_to_step(quantity, filters.step_size)
        entry_price = round_to_step(signal.entry_mid, filters.tick_size)
        stop_price = round_to_step(signal.stop_loss, filters.tick_size)

        if qty <= 0:
            return ExecutionResult(
                False,
                f"Quantidade calculada ({quantity}) arredonda para 0 com o "
                f"stepSize de {symbol} ({filters.step_size}) - posição pequena demais.",
                [],
            )

        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        entry_order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=str(entry_price),
        )
        order_ids.append(str(entry_order["orderId"]))

        stop_order = client.futures_create_order(
            symbol=symbol,
            side=close_side,
            type="STOP_MARKET",
            stopPrice=str(stop_price),
            closePosition=True,
        )
        order_ids.append(str(stop_order["orderId"]))

        # Take-profit escalonado: divide a quantidade igualmente entre os alvos.
        if signal.targets:
            qty_per_target = round_to_step(qty / len(signal.targets), filters.step_size)
            if qty_per_target > 0:
                for target in signal.targets:
                    tp_price = round_to_step(target.price, filters.tick_size)
                    tp_order = client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type="TAKE_PROFIT_MARKET",
                        stopPrice=str(tp_price),
                        quantity=qty_per_target,
                        reduceOnly=True,
                    )
                    order_ids.append(str(tp_order["orderId"]))

        return ExecutionResult(True, "Ordens enviadas com sucesso.", order_ids)
    except Exception as exc:  # noqa: BLE001 - queremos capturar e logar qualquer falha da API
        return ExecutionResult(False, f"Erro ao enviar ordens: {exc}", order_ids)
