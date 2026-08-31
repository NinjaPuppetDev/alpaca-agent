"""Configuration management for the trading agent.

Reads settings from environment variables and provides typed access across modules.
"""

from typing import Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Alpaca credentials
    ALPACA_API_KEY: str = Field(default="", description="Alpaca API Key ID")
    ALPACA_SECRET_KEY: str = Field(default="", description="Alpaca API Secret Key")
    ALPACA_PAPER: Union[bool, str] = Field(default=True, description="Whether to use Alpaca Paper Trading")

    @field_validator("ALPACA_PAPER", mode="before")
    @classmethod
    def parse_alpaca_paper(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("true", "1", "yes", "t"):
                return True
            if v_lower in ("false", "0", "no", "f"):
                return False
            if "paper" in v_lower:
                return True
        return bool(v)

    # Groq LLM credentials and config
    GROQ_API_KEY: str = Field(default="", description="Groq API Key")
    LLM_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Groq/OpenAI compatible LLM model name"
    )
    LLM_REASONING_EFFORT: str = Field(
        default="medium",
        description="Configurable reasoning effort for models like openai/gpt-oss-120b (low/medium/high)"
    )

    # Strategy cadences & risk parameters
    EXPIRATION_THRESHOLD_DAYS: int = Field(
        default=5,
        description="Days to expiration threshold for watchdog to close/roll positions"
    )
    OVERLAY_CADENCE_MINUTES: int = Field(
        default=60,
        description="Derivatives overlay execution interval in minutes"
    )
    THEME_CADENCE_HOURS: int = Field(
        default=24,
        description="Theme & portfolio rebalancing interval in hours"
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./trading_agent.db",
        description="SQLAlchemy database connection URL"
    )


settings = Settings()
