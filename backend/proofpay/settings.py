"""Application settings via pydantic-settings."""

from decimal import Decimal
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROOFPAY_",
        env_file=".env",
        extra="ignore",
    )

    # -- database -----------------------------------------------------
    database_url: str = "postgresql+psycopg://proofpay:proofpay@localhost:5433/proofpay"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # -- application --------------------------------------------------
    debug: bool = False
    api_prefix: str = "/api/v1"
    public_url: str = "http://localhost:5273"

    # -- PayPal -------------------------------------------------------
    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_env: Literal["sandbox", "live"] = "sandbox"
    allow_live: bool = False

    # -- GitHub -------------------------------------------------------
    github_token: SecretStr = SecretStr("")

    # -- language models ----------------------------------------------
    gemini_api_key: SecretStr = SecretStr("")
    llm_model: str = "gemini-3-flash-preview"
    fallback_base_url: str = ""
    fallback_model: str = ""
    fallback_api_key: SecretStr = SecretStr("")

    # -- limits -------------------------------------------------------
    max_bounty_usd: Decimal = Decimal("500")
    mcp_port: int = 8001
