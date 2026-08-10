"""Parser dos sinais postados pelo 'Signal Tracker Bot' (ou similar) no formato:

🎯 #115013 - Ordem Limite
📡 Canal: STC-54
💰 Moeda: TAO
📊 Tipo: SHORT (Futures)
📈 Alavancagem: 10x
🎯 Zona de Entrada: 0.02250491 - 0.02273109
🛑 Stop Loss: 0.02397500 (5.9996%)
🎯 Alvos:
T1: 0.02248200 (0.60%)
T2: 0.02227900 (1.50%)
...
🔀 R/R ratio: 0.1
📶 Status: Sinal aberto

O parser é tolerante a emojis diferentes na frente de cada rótulo e a pequenas
variações de espaçamento — casa pelo texto do rótulo (ex. "Moeda:"), não pelo emoji.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class ParseError(ValueError):
    pass


@dataclass
class Target:
    price: float
    pct: float


@dataclass
class Signal:
    signal_id: str
    canal: str
    coin: str
    side: str  # "LONG" ou "SHORT"
    market: str  # "Futures" / "Spot"
    leverage: int
    entry_low: float
    entry_high: float
    stop_loss: float
    stop_loss_pct: float
    targets: list[Target] = field(default_factory=list)
    rr_ratio: float | None = None
    status: str = ""
    raw_text: str = ""

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2

    @property
    def stop_distance_pct(self) -> float:
        """Distância % entre entrada média e stop, sempre positiva."""
        return abs(self.entry_mid - self.stop_loss) / self.entry_mid

    def reward_pct_for_target(self, index: int = 0) -> float | None:
        if index >= len(self.targets):
            return None
        return self.targets[index].pct / 100.0

    def computed_rr(self, target_index: int = 0) -> float | None:
        """R/R calculado localmente (independe do valor que o bot mandou)."""
        reward = self.reward_pct_for_target(target_index)
        risk = self.stop_distance_pct
        if reward is None or risk == 0:
            return None
        return reward / risk


_LABEL_PATTERNS = {
    "signal_id": re.compile(r"#(\d+)\s*-\s*Ordem", re.IGNORECASE),
    "canal": re.compile(r"Canal:\s*([^\n]+)", re.IGNORECASE),
    "coin": re.compile(r"Moeda:\s*([^\n]+)", re.IGNORECASE),
    "tipo": re.compile(r"Tipo:\s*(LONG|SHORT)\s*\(([^)]+)\)", re.IGNORECASE),
    "leverage": re.compile(r"Alavancagem:\s*(\d+)\s*x", re.IGNORECASE),
    "entry": re.compile(
        r"Zona de Entrada:\s*([\d.,]+)\s*-\s*([\d.,]+)", re.IGNORECASE
    ),
    "stop": re.compile(
        r"Stop Loss:\s*([\d.,]+)\s*\(([\d.,]+)%\)", re.IGNORECASE
    ),
    "rr": re.compile(r"R/R ratio:\s*([\d.,]+)", re.IGNORECASE),
    "status": re.compile(r"Status:\s*([^\n]+)", re.IGNORECASE),
}
_TARGET_PATTERN = re.compile(
    r"T(\d):\s*([\d.,]+)\s*\(([\d.,]+)%\)", re.IGNORECASE
)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def looks_like_signal(text: str) -> bool:
    """Filtro rápido antes de tentar o parse completo."""
    return bool(text) and "Ordem Limite" in text and "Moeda:" in text


def parse_signal(text: str) -> Signal:
    if not looks_like_signal(text):
        raise ParseError("Texto não parece um sinal de Ordem Limite reconhecível.")

    m_id = _LABEL_PATTERNS["signal_id"].search(text)
    m_canal = _LABEL_PATTERNS["canal"].search(text)
    m_coin = _LABEL_PATTERNS["coin"].search(text)
    m_tipo = _LABEL_PATTERNS["tipo"].search(text)
    m_lev = _LABEL_PATTERNS["leverage"].search(text)
    m_entry = _LABEL_PATTERNS["entry"].search(text)
    m_stop = _LABEL_PATTERNS["stop"].search(text)
    m_rr = _LABEL_PATTERNS["rr"].search(text)
    m_status = _LABEL_PATTERNS["status"].search(text)

    required = {
        "id": m_id, "canal": m_canal, "moeda": m_coin, "tipo": m_tipo,
        "alavancagem": m_lev, "entrada": m_entry, "stop": m_stop,
    }
    faltando = [k for k, v in required.items() if not v]
    if faltando:
        raise ParseError(f"Campos obrigatórios ausentes no sinal: {', '.join(faltando)}")

    targets = [
        Target(price=_num(price), pct=_num(pct))
        for _, price, pct in sorted(
            (int(n), p, pc) for n, p, pc in _TARGET_PATTERN.findall(text)
        )
    ]

    return Signal(
        signal_id=m_id.group(1),
        canal=m_canal.group(1).strip(),
        coin=m_coin.group(1).strip(),
        side=m_tipo.group(1).upper(),
        market=m_tipo.group(2).strip(),
        leverage=int(m_lev.group(1)),
        entry_low=_num(m_entry.group(1)),
        entry_high=_num(m_entry.group(2)),
        stop_loss=_num(m_stop.group(1)),
        stop_loss_pct=_num(m_stop.group(2)),
        targets=targets,
        rr_ratio=_num(m_rr.group(1)) if m_rr else None,
        status=m_status.group(1).strip() if m_status else "",
        raw_text=text,
    )
