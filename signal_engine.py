"""
Motor de señales de scalping
Indicadores: EMA 9/21, RSI 7, ATR 14, VWAP
Timeframes: M1 (señal) + M5 (filtro de tendencia)
"""
import pandas as pd
import pandas_ta as ta
import structlog
from dataclasses import dataclass
from typing import Optional
from config import get_settings

log = structlog.get_logger()
cfg = get_settings()


@dataclass
class Signal:
    direction: str          # "LONG", "SHORT", "NONE"
    entry_price: float
    sl_price: float
    tp_price: float
    atr: float
    rsi: float
    reason: str
    confidence: float       # 0.0 - 1.0


class SignalEngine:
    def __init__(self):
        self.ema_fast  = 9
        self.ema_slow  = 21
        self.rsi_period = 7
        self.atr_period = 14
        self.sl_atr_mult = 1.5
        self.tp_atr_mult = 2.5
        self.min_atr = 8.0       # ATR mínimo para operar (evita mercados muertos)
        self.max_spread = 3.0    # Spread máximo permitido en puntos

    def _df(self, candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles)
        df["open"]   = df["open"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)
        df["close"]  = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema_fast"] = ta.ema(df["close"], length=self.ema_fast)
        df["ema_slow"] = ta.ema(df["close"], length=self.ema_slow)
        df["rsi"]      = ta.rsi(df["close"], length=self.rsi_period)
        df["atr"]      = ta.atr(df["high"], df["low"], df["close"], length=self.atr_period)
        # VWAP (intradía)
        df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
        # Volumen medio (20 velas)
        df["vol_avg"] = df["volume"].rolling(20).mean()
        return df

    def analyze(
        self,
        candles_m1: list,
        candles_m5: list,
        current_price: float,
        spread: float,
    ) -> Signal:
        """
        Genera señal de entrada basada en:
        - Tendencia M5: EMA9 vs EMA21
        - Momentum M1: RSI(7) cruza 50
        - Precio vs VWAP
        - Volumen por encima de la media
        - Spread y ATR dentro de rango aceptable
        """
        no_signal = Signal("NONE", current_price, 0, 0, 0, 0, "Sin señal", 0.0)

        if len(candles_m1) < 30 or len(candles_m5) < 25:
            return Signal("NONE", current_price, 0, 0, 0, 0, "Datos insuficientes", 0.0)

        # ── Filtro de spread ──────────────────────────────────
        if spread > self.max_spread:
            return Signal("NONE", current_price, 0, 0, 0, 0, f"Spread alto: {spread:.1f}", 0.0)

        # ── Indicadores M5 (tendencia) ────────────────────────
        df5 = self._add_indicators(self._df(candles_m5))
        ema_fast_m5 = df5["ema_fast"].iloc[-1]
        ema_slow_m5 = df5["ema_slow"].iloc[-1]
        trend_up   = ema_fast_m5 > ema_slow_m5
        trend_down = ema_fast_m5 < ema_slow_m5

        # ── Indicadores M1 (señal) ────────────────────────────
        df1 = self._add_indicators(self._df(candles_m1))
        last  = df1.iloc[-1]
        prev  = df1.iloc[-2]

        rsi_now  = last["rsi"]
        rsi_prev = prev["rsi"]
        atr      = last["atr"]
        vwap     = last["vwap"]
        vol      = last["volume"]
        vol_avg  = last["vol_avg"]

        if pd.isna(atr) or pd.isna(rsi_now) or pd.isna(vol_avg):
            return no_signal

        # ── Filtro de ATR mínimo ──────────────────────────────
        if atr < self.min_atr:
            return Signal("NONE", current_price, 0, 0, 0, rsi_now, f"ATR bajo: {atr:.1f}", 0.0)

        sl_dist = self.sl_atr_mult * atr
        tp_dist = self.tp_atr_mult * atr
        vol_ok  = vol > vol_avg * 1.2

        # ── LONG ──────────────────────────────────────────────
        # Condiciones: tendencia alcista M5 + RSI cruza 50 al alza en M1
        #              + precio sobre VWAP + volumen confirmado
        if (trend_up and
            rsi_prev < 50 and rsi_now >= 50 and
            current_price > vwap and
            vol_ok):

            sl = round(current_price - sl_dist, 1)
            tp = round(current_price + tp_dist, 1)
            confidence = min(1.0, (rsi_now - 50) / 20 + 0.5)
            reason = f"LONG · EMA✓ · RSI {rsi_now:.0f} cruzó 50↑ · Precio>VWAP · Vol✓"
            log.info("signal.long", price=current_price, sl=sl, tp=tp, atr=atr, rsi=rsi_now)
            return Signal("LONG", current_price, sl, tp, atr, rsi_now, reason, confidence)

        # ── SHORT ─────────────────────────────────────────────
        # Condiciones: tendencia bajista M5 + RSI cruza 50 a la baja en M1
        #              + precio bajo VWAP + volumen confirmado
        if (trend_down and
            rsi_prev > 50 and rsi_now <= 50 and
            current_price < vwap and
            vol_ok):

            sl = round(current_price + sl_dist, 1)
            tp = round(current_price - tp_dist, 1)
            confidence = min(1.0, (50 - rsi_now) / 20 + 0.5)
            reason = f"SHORT · EMA✓ · RSI {rsi_now:.0f} cruzó 50↓ · Precio<VWAP · Vol✓"
            log.info("signal.short", price=current_price, sl=sl, tp=tp, atr=atr, rsi=rsi_now)
            return Signal("SHORT", current_price, sl, tp, atr, rsi_now, reason, confidence)

        return Signal("NONE", current_price, 0, 0, atr, rsi_now, "Sin confluencia", 0.0)