from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # OANDA
    oanda_env: str = "practice"
    oanda_token: str = ""
    oanda_account_id: str = ""
    oanda_instrument: str = "DE30_EUR"

    # Estrategia
    capital: float = 5000.0
    risk_pct: float = 1.0
    max_daily_loss_pct: float = 2.0
    max_ops_session: int = 15
    max_simultaneous: int = 3
    timeframe: str = "M1"

    # Telegram
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Seguridad
    dashboard_password: str = "changeme"
    secret_key: str = "changeme-secret"

    # Servidor
    port: int = 8000
    debug: bool = False

    @property
    def oanda_url(self) -> str:
        if self.oanda_env == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    @property
    def oanda_stream_url(self) -> str:
        if self.oanda_env == "live":
            return "https://stream-fxtrade.oanda.com"
        return "https://stream-fxpractice.oanda.com"

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()