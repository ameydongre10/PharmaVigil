"""
Centralized application settings with environment variable validation.
Uses pydantic-settings for type-safe configuration management.
"""

import os
import secrets
from typing import List, Optional
from pathlib import Path


class Settings:
    """Application configuration loaded from environment variables."""
    
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    RELOAD: bool = os.getenv("UVICORN_RELOAD", "false").lower() in ("true", "1", "yes") if ENVIRONMENT == "development" else False
    
    # Security
    SIGNING_KEY: Optional[str] = os.getenv("PHARMAVIGIL_SIGNING_KEY")
    SESSION_EXPIRY_DAYS: int = int(os.getenv("SESSION_EXPIRY_DAYS", "7"))
    
    # CORS
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "https://ameydongre10.github.io,http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if origin.strip()
    ]
    
    # Rate limiting
    UPLOAD_MAX_SIZE_MB: int = int(os.getenv("UPLOAD_MAX_SIZE_MB", "25"))
    REQUEST_MAX_SIZE_MB: int = int(os.getenv("REQUEST_MAX_SIZE_MB", "26"))
    
    # Database
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    
    # LLM Provider Allowlist (security: prevent SSRF)
    ALLOWED_LLM_HOSTS: List[str] = [
        "api.openai.com",
        "generativelanguage.googleapis.com",
        "api.anthropic.com",
        "api.groq.com",
        "openrouter.ai",
        "localhost",
        "127.0.0.1"
    ]
    
    # Demo/Test Configuration
    SEED_DEMO_USERS: bool = os.getenv("PHARMAVIGIL_SEED_DEMO_USERS", "false").lower() in ("true", "1", "yes")
    
    # File storage
    OUTPUTS_DIR: Path = Path(__file__).resolve().parent.parent / "outputs"
    SAMPLE_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "sample_data"
    
    @classmethod
    def validate_production_config(cls) -> None:
        """Validate required configuration for production mode."""
        if cls.ENVIRONMENT == "production":
            if not cls.SIGNING_KEY:
                raise ValueError(
                    "PHARMAVIGIL_SIGNING_KEY must be set in production mode. "
                    "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
                )
            if cls.SEED_DEMO_USERS:
                raise ValueError(
                    "PHARMAVIGIL_SEED_DEMO_USERS must not be enabled in production. "
                    "Demo credentials are a security risk on public deployments."
                )
            if "*" in cls.CORS_ORIGINS or "http://localhost" in str(cls.CORS_ORIGINS):
                raise ValueError(
                    "CORS_ORIGINS must not include wildcards or localhost in production."
                )


settings = Settings()

# Fail fast in production mode with invalid configuration
if settings.ENVIRONMENT == "production":
    settings.validate_production_config()
