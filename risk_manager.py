"""
Gestor de riesgo
- Calcula tamaño de posición basado en ATR y capital
- Controla pérdida máxima diaria
- Controla número de operaciones por sesión
- Reduce tamaño tras drawdown
"""
import structlog
from datetime import date
from config import get_settings

log = structlog.get_logger()
cfg = get_settings()


class RiskManager:
    def __init__(self):
        self.reset_daily()

    def reset_daily(self):
        self.today = date.today()
        self.daily_pnl = 0.0
        self.daily_ops = 0
        self.daily_winners = 0
        self.daily_losers = 0
        self.peak_equity = cfg.capital
        self.current_equity = cfg.capital
        self._size_reduction = 1.0   # factor de reducción por drawdown

    def _check_date_reset(self):
        if date.today() != self.today:
            log.info("risk.daily_reset")
            self.reset_daily()

    # ── CÁLCULO DE TAMAÑO ────────────────────────────────────────

    def calc_position_size(self, entry_price: float, sl_price: float) -> float:
        """
        Calcula unidades a operar para no arriesgar más de RISK_PCT % del capital.
        risk_amount = capital × risk_pct / 100
        units = risk_amount / |entry - sl|
        Se aplica factor de reducción si hay drawdown
        """
        self._check_date_reset()
        risk_eur = self.current_equity * (cfg.risk_pct / 100) * self._size_reduction
        sl_distance = abs(entry_price - sl_price)

        if sl_distance == 0:
            log.warning("risk.zero_sl_distance")
            return 0.0

        units = round(risk_eur / sl_distance, 2)
        # Mínimo 0.01 unidades
        units = max(0.01, units)

        log.info("risk.position_size",
            capital=self.current_equity,
            risk_eur=risk_eur,
            sl_distance=sl_distance,
            units=units,
            reduction_factor=self._size_reduction
        )
        return units

    # ── CONTROLES DE APERTURA ────────────────────────────────────

    def can_open_trade(self, open_trades_count: int) -> tuple[bool, str]:
        """Retorna (puede_operar, motivo)"""
        self._check_date_reset()

        # Pérdida diaria máxima
        max_loss = self.current_equity * (cfg.max_daily_loss_pct / 100)
        if self.daily_pnl <= -max_loss:
            return False, f"Pérdida diaria máxima alcanzada ({self.daily_pnl:.2f}€)"

        # Máximo de operaciones
        if self.daily_ops >= cfg.max_ops_session:
            return False, f"Máximo de operaciones diarias alcanzado ({cfg.max_ops_session})"

        # Máximo de posiciones simultáneas
        if open_trades_count >= cfg.max_simultaneous:
            return False, f"Máximo de posiciones simultáneas ({cfg.max_simultaneous})"

        return True, "OK"

    # ── REGISTRO DE RESULTADOS ───────────────────────────────────

    def record_trade(self, pnl: float):
        """Registra el resultado de una operación cerrada."""
        self._check_date_reset()
        self.daily_pnl += pnl
        self.daily_ops += 1
        self.current_equity += pnl

        if pnl > 0:
            self.daily_winners += 1
        else:
            self.daily_losers += 1

        # Actualizar peak y calcular drawdown
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
            self._size_reduction = 1.0  # resetear reducción

        drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity * 100

        # Reducir tamaño al 50% si drawdown > 3%
        if drawdown_pct > 3.0:
            self._size_reduction = 0.5
            log.warning("risk.size_reduced", drawdown_pct=drawdown_pct, factor=0.5)
        else:
            self._size_reduction = 1.0

        log.info("risk.trade_recorded",
            pnl=pnl,
            daily_pnl=self.daily_pnl,
            daily_ops=self.daily_ops,
            drawdown_pct=drawdown_pct,
            equity=self.current_equity
        )

    # ── ESTADO ───────────────────────────────────────────────────

    def get_status(self) -> dict:
        self._check_date_reset()
        max_loss = self.current_equity * (cfg.max_daily_loss_pct / 100)
        drawdown = (self.peak_equity - self.current_equity) / self.peak_equity * 100
        win_rate = (self.daily_winners / self.daily_ops * 100) if self.daily_ops > 0 else 0

        return {
            "equity":          round(self.current_equity, 2),
            "daily_pnl":       round(self.daily_pnl, 2),
            "daily_ops":       self.daily_ops,
            "daily_winners":   self.daily_winners,
            "daily_losers":    self.daily_losers,
            "win_rate":        round(win_rate, 1),
            "max_daily_loss":  round(max_loss, 2),
            "drawdown_pct":    round(drawdown, 2),
            "size_reduction":  self._size_reduction,
            "risk_pct":        cfg.risk_pct,
        }