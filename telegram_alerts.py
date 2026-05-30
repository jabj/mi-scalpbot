"""
Alertas por Telegram
Envía notificaciones de señales, órdenes, riesgo y errores
"""
import asyncio
import structlog
from telegram import Bot
from telegram.error import TelegramError
from config import get_settings

log = structlog.get_logger()
cfg = get_settings()

bot: Bot | None = None

def init_telegram():
    global bot
    if cfg.telegram_token and cfg.telegram_chat_id:
        bot = Bot(token=cfg.telegram_token)
        log.info("telegram.initialized")
    else:
        log.warning("telegram.not_configured")

async def _send(text: str):
    if not bot or not cfg.telegram_chat_id:
        return
    try:
        await bot.send_message(
            chat_id=cfg.telegram_chat_id,
            text=text,
            parse_mode="HTML"
        )
    except TelegramError as e:
        log.error("telegram.send_failed", error=str(e))

def send(text: str):
    """Envío síncrono (para llamar desde código normal)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send(text))
        else:
            loop.run_until_complete(_send(text))
    except Exception as e:
        log.error("telegram.send_error", error=str(e))

# ── MENSAJES PREDEFINIDOS ────────────────────────────────────────

def alert_signal(direction: str, price: float, sl: float, tp: float,
                  units: float, atr: float, reason: str):
    emoji = "🟢" if direction == "LONG" else "🔴"
    rr = round(abs(tp - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0
    send(
        f"{emoji} <b>NUEVA OPERACIÓN</b>\n"
        f"{'─' * 28}\n"
        f"📊 <b>{direction}</b> · DE30\n"
        f"💰 Entrada: <b>{price:.1f}</b>\n"
        f"🛑 Stop Loss: {sl:.1f}\n"
        f"🎯 Take Profit: {tp:.1f}\n"
        f"📐 RR: 1:{rr}\n"
        f"📦 Unidades: {units}\n"
        f"📈 ATR: {atr:.1f}\n"
        f"💡 {reason}"
    )

def alert_close(trade_id: str, pl: float, direction: str):
    emoji = "✅" if pl >= 0 else "❌"
    send(
        f"{emoji} <b>TRADE CERRADO</b> #{trade_id}\n"
        f"{'─' * 28}\n"
        f"📊 {direction}\n"
        f"💶 P&L: <b>{'+'if pl>=0 else''}{pl:.2f}€</b>"
    )

def alert_risk_stop(reason: str, daily_pnl: float):
    send(
        f"⛔ <b>BOT PAUSADO POR RIESGO</b>\n"
        f"{'─' * 28}\n"
        f"Motivo: {reason}\n"
        f"P&L del día: {daily_pnl:.2f}€"
    )

def alert_bot_start(env: str, instrument: str):
    send(
        f"🚀 <b>ScalpBot iniciado</b>\n"
        f"{'─' * 28}\n"
        f"🌍 Entorno: <b>{env.upper()}</b>\n"
        f"📊 Instrumento: {instrument}\n"
        f"⚡ Motor de señales activo"
    )

def alert_bot_stop(reason: str = "Manual"):
    send(f"⏹ <b>ScalpBot detenido</b> · {reason}")

def alert_error(error: str):
    send(f"🔥 <b>ERROR</b>\n{error[:500]}")

def alert_daily_summary(ops: int, winners: int, losers: int, pnl: float, win_rate: float):
    emoji = "📈" if pnl >= 0 else "📉"
    send(
        f"{emoji} <b>RESUMEN DEL DÍA</b>\n"
        f"{'─' * 28}\n"
        f"📊 Operaciones: {ops}\n"
        f"✅ Ganadoras: {winners} | ❌ Perdedoras: {losers}\n"
        f"🎯 Win Rate: {win_rate:.1f}%\n"
        f"💶 P&L total: <b>{'+'if pnl>=0 else''}{pnl:.2f}€</b>"
    )