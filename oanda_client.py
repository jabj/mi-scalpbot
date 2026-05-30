"""
Cliente OANDA API v20
Gestiona autenticación, órdenes, posiciones y streaming de precios
"""
import oandapyV20
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.positions as positions_ep

from oandapyV20.contrib.requests import MarketOrderRequest, TakeProfitDetails, StopLossDetails
from oandapyV20.exceptions import V20Error

import structlog
from config import get_settings
from typing import Optional

log = structlog.get_logger()
cfg = get_settings()


class OandaClient:
    def __init__(self):
        self.api = oandapyV20.API(
            access_token=cfg.oanda_token,
            environment=cfg.oanda_env
        )
        self.account_id = cfg.oanda_account_id
        self.instrument = cfg.oanda_instrument

    # ── CUENTA ──────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Retorna balance, NAV, margen usado y disponible."""
        try:
            r = accounts.AccountSummary(self.account_id)
            self.api.request(r)
            a = r.response["account"]
            return {
                "balance":    float(a["balance"]),
                "nav":        float(a["NAV"]),
                "unrealized_pl": float(a["unrealizedPL"]),
                "margin_used":   float(a["marginUsed"]),
                "margin_avail":  float(a["marginAvailable"]),
                "open_trades":   int(a["openTradeCount"]),
            }
        except V20Error as e:
            log.error("oanda.get_account", error=str(e))
            raise

    # ── PRECIOS ─────────────────────────────────────────────────

    def get_price(self) -> dict:
        """Precio bid/ask actual del instrumento."""
        try:
            params = {"instruments": self.instrument}
            r = pricing.PricingInfo(self.account_id, params=params)
            self.api.request(r)
            p = r.response["prices"][0]
            bid = float(p["bids"][0]["price"])
            ask = float(p["asks"][0]["price"])
            return {
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 1),
                "spread": round(ask - bid, 1),
            }
        except V20Error as e:
            log.error("oanda.get_price", error=str(e))
            raise

    def get_candles(self, count: int = 60, granularity: str = None) -> list:
        """
        Retorna velas OHLCV.
        granularity: M1, M5, S10, S15... (por defecto usa cfg.timeframe)
        """
        gran = granularity or cfg.timeframe
        try:
            params = {"count": count, "granularity": gran, "price": "M"}
            r = instruments.InstrumentsCandles(self.instrument, params=params)
            self.api.request(r)
            candles = []
            for c in r.response["candles"]:
                if c["complete"]:
                    m = c["mid"]
                    candles.append({
                        "time":   c["time"],
                        "open":   float(m["o"]),
                        "high":   float(m["h"]),
                        "low":    float(m["l"]),
                        "close":  float(m["c"]),
                        "volume": int(c["volume"]),
                    })
            return candles
        except V20Error as e:
            log.error("oanda.get_candles", error=str(e))
            raise

    # ── ÓRDENES ─────────────────────────────────────────────────

    def place_order(
        self,
        units: float,
        sl_price: float,
        tp_price: float,
        comment: str = ""
    ) -> dict:
        """
        Abre orden de mercado con SL y TP en una sola llamada.
        units > 0 = LONG, units < 0 = SHORT
        sl_price y tp_price en precio absoluto del instrumento.
        """
        direction = "LONG" if units > 0 else "SHORT"
        try:
            mktOrder = MarketOrderRequest(
                instrument=self.instrument,
                units=units,
                takeProfitOnFill=TakeProfitDetails(price=tp_price).data,
                stopLossOnFill=StopLossDetails(price=sl_price).data,
            )
            r = orders.OrderCreate(self.account_id, data=mktOrder.data)
            self.api.request(r)
            resp = r.response
            fill = resp.get("orderFillTransaction", {})
            trade_id = fill.get("tradeOpened", {}).get("tradeID", "?")
            fill_price = float(fill.get("price", 0))

            log.info("order.placed",
                direction=direction,
                units=units,
                fill_price=fill_price,
                sl=sl_price,
                tp=tp_price,
                trade_id=trade_id,
                comment=comment
            )

            return {
                "trade_id":   trade_id,
                "direction":  direction,
                "units":      units,
                "fill_price": fill_price,
                "sl":         sl_price,
                "tp":         tp_price,
            }

        except V20Error as e:
            log.error("order.failed", direction=direction, error=str(e))
            raise

    def close_trade(self, trade_id: str) -> dict:
        """Cierra un trade por su ID."""
        try:
            r = trades.TradeClose(self.account_id, trade_id)
            self.api.request(r)
            fill = r.response.get("orderFillTransaction", {})
            pl = float(fill.get("pl", 0))
            log.info("trade.closed", trade_id=trade_id, pl=pl)
            return {"trade_id": trade_id, "pl": pl}
        except V20Error as e:
            log.error("trade.close_failed", trade_id=trade_id, error=str(e))
            raise

    def close_all(self) -> list:
        """Cierra todas las posiciones abiertas (emergencia)."""
        try:
            r = positions_ep.OpenPositions(self.account_id)
            self.api.request(r)
            results = []
            for pos in r.response.get("positions", []):
                inst = pos["instrument"]
                long_units  = int(float(pos["long"]["units"]))
                short_units = int(float(pos["short"]["units"]))
                if long_units > 0:
                    data = {"longUnits": "ALL"}
                    rp = positions_ep.PositionClose(self.account_id, inst, data)
                    self.api.request(rp)
                    results.append({"instrument": inst, "side": "LONG", "closed": long_units})
                if short_units < 0:
                    data = {"shortUnits": "ALL"}
                    rp = positions_ep.PositionClose(self.account_id, inst, data)
                    self.api.request(rp)
                    results.append({"instrument": inst, "side": "SHORT", "closed": abs(short_units)})
            log.warning("close_all.executed", positions_closed=len(results))
            return results
        except V20Error as e:
            log.error("close_all.failed", error=str(e))
            raise

    def get_open_trades(self) -> list:
        """Lista de trades abiertos con SL/TP."""
        try:
            r = trades.OpenTrades(self.account_id)
            self.api.request(r)
            result = []
            for t in r.response.get("trades", []):
                sl = t.get("stopLossOrder", {}).get("price", "—")
                tp = t.get("takeProfitOrder", {}).get("price", "—")
                result.append({
                    "id":          t["id"],
                    "instrument":  t["instrument"],
                    "units":       float(t["currentUnits"]),
                    "direction":   "LONG" if float(t["currentUnits"]) > 0 else "SHORT",
                    "open_price":  float(t["price"]),
                    "current_pl":  float(t["unrealizedPL"]),
                    "sl":          float(sl) if sl != "—" else None,
                    "tp":          float(tp) if tp != "—" else None,
                    "open_time":   t["openTime"],
                })
            return result
        except V20Error as e:
            log.error("oanda.get_trades", error=str(e))
            raise