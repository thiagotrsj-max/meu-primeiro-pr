"""Camada de gestão de risco: decide SE um sinal pode virar ordem e QUANTO operar.

Esta camada roda antes do pedido de aprovação — sinais que não passam aqui
nem chegam a te incomodar no Telegram, já são rejeitados e logados.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import Config
from signal_parser import Signal


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    notional_usdt: float = 0.0
    quantity: float = 0.0
    leverage: int = 0
    margin_required_usdt: float = 0.0
    risk_amount_usdt: float = 0.0
    rr_used: float | None = None


def evaluate(
    signal: Signal,
    *,
    config: Config,
    account_balance_usdt: float,
    open_positions_count: int,
) -> RiskDecision:
    # 1. Whitelist de moedas
    if config.coin_whitelist and signal.coin.upper() not in config.coin_whitelist:
        return RiskDecision(False, f"Moeda {signal.coin} fora da whitelist configurada.")

    # 2. Limite de posições simultâneas
    if open_positions_count >= config.max_concurrent_positions:
        return RiskDecision(
            False,
            f"Limite de posições simultâneas atingido "
            f"({open_positions_count}/{config.max_concurrent_positions}).",
        )

    # 3. R/R mínimo (usa o R/R calculado localmente com base no alvo 1, não confia
    #    cegamente no valor que o bot do canal mandou)
    rr = signal.computed_rr(target_index=0)
    if rr is None:
        return RiskDecision(False, "Não foi possível calcular R/R (falta alvo T1 ou stop).")
    if rr < config.min_rr_ratio:
        return RiskDecision(
            False,
            f"R/R do alvo 1 ({rr:.2f}) abaixo do mínimo configurado "
            f"({config.min_rr_ratio:.2f}).",
            rr_used=rr,
        )

    # 4. Alavancagem: nunca excede o teto configurado, mesmo que o sinal peça mais
    leverage = min(signal.leverage, config.max_leverage)

    # 5. Distância até o stop
    stop_dist_pct = signal.stop_distance_pct
    if stop_dist_pct <= 0:
        return RiskDecision(False, "Distância até o stop loss é zero ou inválida.")

    # 6. Tamanho de posição: risk_amount é quanto você está disposto a perder em USDT
    #    se o stop for atingido. notional = risk_amount / stop_dist_pct (independe
    #    da alavancagem — alavancagem só afeta a margem necessária, não o $ de risco).
    risk_amount = account_balance_usdt * (config.max_risk_per_trade_pct / 100.0)
    notional = risk_amount / stop_dist_pct
    margin_required = notional / leverage
    quantity = notional / signal.entry_mid

    if margin_required > account_balance_usdt:
        return RiskDecision(
            False,
            f"Margem necessária (${margin_required:.2f}) excede o saldo disponível "
            f"(${account_balance_usdt:.2f}).",
            rr_used=rr,
        )

    return RiskDecision(
        approved=True,
        reason="OK",
        notional_usdt=notional,
        quantity=quantity,
        leverage=leverage,
        margin_required_usdt=margin_required,
        risk_amount_usdt=risk_amount,
        rr_used=rr,
    )
