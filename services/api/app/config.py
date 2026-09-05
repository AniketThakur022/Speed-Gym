"""VMSG API settings — pydantic-settings, env-driven, .env-friendly."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "vmsg-api"
    version: str = "0.1.0"
    debug: bool = False

    database_url: str = "postgresql://vmsg:vmsg@localhost:5432/vmsg"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "vmsg-dev-password"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-change-me"
    access_token_ttl_seconds: int = 900          # 15-min access tokens (SEC-01)
    refresh_token_ttl_days: int = 30
    offline_token_secret: str = "dev-only-change-me-too"

    api_v1_prefix: str = "/api/v1"

    # Internal API (game server ↔ FastAPI). It serves problem ANSWERS, so it is
    # loopback-bound and key-guarded; loosen the loopback check only when the
    # game server runs on a separate host inside the VPC.
    internal_api_key: str = "dev-internal-key"
    internal_api_require_loopback: bool = True

    # The mobile shells are not same-origin with the API: Capacitor serves the
    # bundle from capacitor://localhost (iOS) or http://localhost (Android), so
    # CORS is a production requirement, not just a dev convenience. Traefik
    # fronts both under one host on the web, hence the explicit allow-list.
    cors_allow_origins: str = (
        "http://localhost:3000,http://localhost:3100,"
        "capacitor://localhost,http://localhost,https://examarena.com"
    )

    # ── Billing ────────────────────────────────────────────────────────────
    # Razorpay is PRIMARY (owner decision 2026-09-04), Stripe secondary for
    # international cards. Tier prices are USD-denominated in the RFP; INR is
    # derived at the configured rate, never hardcoded. Every secret below is
    # owner-supplied through .env (gitignored). Empty = provider not
    # configured: checkout answers 503 and webhooks are REJECTED, never
    # accepted unsigned.
    billing_default_provider: str = "razorpay"
    billing_default_currency: str = "INR"
    usd_inr_rate: float = 84.0
    trial_days: int = 7
    billing_grace_days: int = 3          # SUB-10 / PAY-05 offline + dunning grace
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_api_base: str = "https://api.razorpay.com/v1"
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_base: str = "https://api.stripe.com/v1"
    stripe_checkout_success_url: str = (
        "https://examarena.com/billing/success?session_id={CHECKOUT_SESSION_ID}"
    )
    stripe_checkout_cancel_url: str = "https://examarena.com/billing/cancel"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
