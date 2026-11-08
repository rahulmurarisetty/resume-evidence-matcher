from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.llm.client import DEFAULT_PARSE_MODEL, DEFAULT_REWRITE_MODEL
from app.services.network import TrustedProxies, parse_networks
from app.services.ratelimit import Rate
from app.services.semantic import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANK_MODEL,
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
)

AppEnv = Literal["local", "production"]
AuthMode = Literal["required", "disabled"]
ScannerSetting = Literal["off", "clamav"]
SemanticSetting = Literal["off", "on", "auto"]
LLMSetting = Literal["off", "on", "auto"]

# Actions with their own rate limit. See app/services/ratelimit.py.
RATE_LIMITED_ACTIONS = ("auth", "analyses", "suggestions", "exports")
_SECURE_SSLMODES = {"require", "verify-ca", "verify-full"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "production" turns on the checks in production_problems() and HSTS.
    app_env: AppEnv = "local"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/app.db"
    # Run `alembic upgrade head` at startup. Unset means yes locally and no in
    # production, where the app refuses to start while migrations are pending.
    db_auto_migrate: bool | None = None

    # Accounts. "disabled" is for a local single-user demo and is refused in production.
    auth_mode: AuthMode = "required"
    session_ttl_hours: float = Field(default=12, gt=0, le=720)

    max_upload_mb: float = Field(default=5, gt=0, le=50)
    max_pdf_pages: int = Field(default=10, gt=0, le=100)
    max_jd_chars: int = Field(default=20_000, gt=100)
    # DOCX files are zip archives. Cap the unpacked size to stop zip bombs.
    max_docx_uncompressed_mb: float = Field(default=50, gt=0)

    retention_hours: int = Field(default=24, gt=0)
    cors_origins: str = "http://localhost:8501"
    # Proxies whose X-Forwarded-For header is trusted for the client address, as a
    # comma-separated list of addresses and CIDR ranges. Empty trusts none.
    trusted_proxies: str = ""

    # Malware scanning of uploads. "clamav" sends each upload to clamd before it is read.
    scanner: ScannerSetting = "off"
    clamav_host: str = "localhost"
    clamav_port: int = Field(default=3310, gt=0, lt=65536)
    clamav_timeout_seconds: float = Field(default=30, gt=0, le=300)
    # Lets production run with SCANNER=off. The app logs a warning at every start.
    allow_unscanned_uploads: bool = False

    # Rate limits, per account (per email for login and register) and, multiplied
    # by rate_limit_ip_multiplier, per client address. In memory, per process.
    rate_limits_enabled: bool = True
    rate_limit_auth: str = "5/minute"
    rate_limit_analyses: str = "30/hour"
    rate_limit_suggestions: str = "30/hour"
    rate_limit_exports: str = "60/hour"
    rate_limit_ip_multiplier: float = Field(default=5, ge=1, le=1000)

    # Matching by meaning. "auto" turns it on only when sentence-transformers is
    # installed (the ml extra). "on" fails at startup if it isn't.
    semantic_matching: SemanticSetting = "auto"
    semantic_top_k: int = Field(default=DEFAULT_TOP_K, gt=0, le=50)
    semantic_threshold: float = Field(default=DEFAULT_THRESHOLD, ge=0, le=1)
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rerank_model: str = DEFAULT_RERANK_MODEL

    # Claude. "auto" turns it on only when a key is set, "on" fails at startup
    # without one. The key is a SecretStr so it never shows up in a repr or a log.
    llm_enabled: LLMSetting = "auto"
    anthropic_api_key: SecretStr | None = None
    llm_parse_model: str = DEFAULT_PARSE_MODEL
    llm_rewrite_model: str = DEFAULT_REWRITE_MODEL
    # Per attempt. The client retries a failed call up to twice.
    llm_timeout_seconds: float = Field(default=30, gt=0, le=600)
    # Rewrite candidates Claude may be asked for over the life of one analysis.
    llm_max_suggestions: int = Field(default=20, ge=0, le=200)

    @field_validator(
        "app_env", "auth_mode", "scanner", "semantic_matching", "llm_enabled", mode="before"
    )
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_no_key(cls, value: object) -> object:
        # ANTHROPIC_API_KEY= in a .env file means "no key", not an empty key.
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @field_validator("db_auto_migrate", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def _postgres_driver(cls, value: str) -> str:
        # Hosting providers hand out postgres:// URLs. SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator(
        "rate_limit_auth", "rate_limit_analyses", "rate_limit_suggestions", "rate_limit_exports"
    )
    @classmethod
    def _rate(cls, value: str) -> str:
        Rate.parse(value)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _networks(cls, value: str) -> str:
        parse_networks(value)
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def auto_migrate(self) -> bool:
        return self.db_auto_migrate if self.db_auto_migrate is not None else not self.is_production

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def max_docx_uncompressed_bytes(self) -> int:
        return int(self.max_docx_uncompressed_mb * 1024 * 1024)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def rates(self) -> dict[str, Rate]:
        return {
            action: Rate.parse(getattr(self, f"rate_limit_{action}"))
            for action in RATE_LIMITED_ACTIONS
        }

    @property
    def proxies(self) -> TrustedProxies:
        return TrustedProxies(parse_networks(self.trusted_proxies))

    def production_problems(self) -> list[str]:
        """Settings that stop the app from starting with APP_ENV=production."""
        if not self.is_production:
            return []
        problems: list[str] = []
        try:
            url = make_url(self.database_url)
        except ArgumentError:
            problems.append("DATABASE_URL is not a database URL.")
        else:
            backend = url.get_backend_name()
            if backend == "sqlite":
                problems.append(
                    "DATABASE_URL points at SQLite, which is for local use and tests. Use "
                    "Postgres: postgresql+psycopg://user:password@host:5432/dbname?sslmode=require"
                )
            else:
                if not url.password:
                    problems.append("DATABASE_URL has no password.")
                sslmode = url.query.get("sslmode")
                if backend == "postgresql" and sslmode not in _SECURE_SSLMODES:
                    problems.append(
                        "DATABASE_URL must end with ?sslmode=require (or verify-ca or "
                        "verify-full) so the connection to the database is always encrypted."
                    )
        if self.auth_mode == "disabled":
            problems.append(
                "AUTH_MODE=disabled lets anyone see every analysis. It is for a local "
                "single-user demo only."
            )
        if self.scanner == "off" and not self.allow_unscanned_uploads:
            problems.append(
                "SCANNER=off: uploads would not be scanned for malware. Set SCANNER=clamav "
                "with CLAMAV_HOST, or set ALLOW_UNSCANNED_UPLOADS=true to accept the risk."
            )
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS=* lets any website call the API. List the origins.")
        if self.llm_enabled == "on" and self.anthropic_api_key is None:
            problems.append("LLM_ENABLED=on needs ANTHROPIC_API_KEY.")
        return problems

    def startup_warnings(self) -> list[str]:
        """Settings that are allowed but logged as a warning at every start."""
        warnings: list[str] = []
        if self.is_production and self.scanner == "off":
            warnings.append(
                "UPLOADS ARE NOT SCANNED FOR MALWARE: APP_ENV=production with SCANNER=off "
                "and ALLOW_UNSCANNED_UPLOADS=true. Set SCANNER=clamav to scan them."
            )
        if self.is_production and not self.rate_limits_enabled:
            warnings.append(
                "RATE LIMITS ARE OFF: APP_ENV=production with RATE_LIMITS_ENABLED=false."
            )
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
