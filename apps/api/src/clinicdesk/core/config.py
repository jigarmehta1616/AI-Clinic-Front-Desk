"""Typed settings from environment. Production refuses unsafe defaults (dev fakes, short secrets)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str
    redis_url: str = "redis://localhost:6380/0"

    jwt_secret: str = Field(min_length=32)
    jwt_kid: str = "k1"
    otp_pepper: str = Field(min_length=32)
    otp_provider: Literal["console", "whatsapp", "sms"] = "console"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_max_sends_per_window: int = 3
    otp_send_window_seconds: int = 600

    cors_origins: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:5173"  # patient-facing links (token tracking, inbox)
    privacy_notice_url: str = "https://example.invalid/privacy"  # DP-1: must be the clinic's real notice

    whatsapp_provider: Literal["log", "cloud"] = "log"
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_shared_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    exotel_webhook_secret: str = ""  # FR-3.1: secret path segment of the Exotel callback URL

    llm_provider: Literal["none", "openai", "gemini"] = "none"

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env == "production":
            if self.otp_provider == "console":
                raise ValueError("OTP_PROVIDER=console is forbidden in production")
            if self.whatsapp_provider != "cloud" or not (self.whatsapp_app_secret and self.whatsapp_access_token):
                raise ValueError("production requires WHATSAPP_PROVIDER=cloud with app secret and access token")
            if "example.invalid" in self.privacy_notice_url:
                raise ValueError("PRIVACY_NOTICE_URL must be set in production (DP-1)")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
