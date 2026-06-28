from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://mocsource:changeme@localhost/mocsource"
    environment: str = "development"
    secret_key: str = "changeme"
    log_level: str = "INFO"
    lego_locale: str = "en-us"

    # BrickLink OAuth1
    bricklink_consumer_key: str = ""
    bricklink_consumer_secret: str = ""
    bricklink_token: str = ""
    bricklink_token_secret: str = ""

    # Rebrickable
    rebrickable_api_key: str = ""

    # Email reporting (for enrichment reports)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@vaultcrest.com"
    report_email: str = "service@vaultcrest.com"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
