from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # CORS Settings
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # MongoDB Settings
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "ccirp_db"
    
    # JWT Auth Settings
    SECRET_KEY: str = "ccirp-super-secret-development-key-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # SMTP Email Settings
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "user@example.com"
    SMTP_PASSWORD: str = "password"
    MAIL_FROM: str = "noreply@example.com"
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    
    FRONTEND_URL: str = "http://localhost:3000"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
