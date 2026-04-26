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
    EMAIL_PROVIDER: str = "smtp"
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "user@example.com"
    SMTP_PASSWORD: str = "password"
    MAIL_FROM: str = "noreply@example.com"
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    
    # API email provider settings
    RESEND_API_KEY: str = ""
    RESEND_API_BASE_URL: str = "https://api.resend.com"
    RESEND_REPLY_TO: str = ""

    # SMS / WhatsApp settings
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_SMS_FROM: str = ""
    TWILIO_WHATSAPP_FROM: str = ""
    TWILIO_API_BASE_URL: str = "https://api.twilio.com"

    # Frontend URL
    FRONTEND_URL: str = "http://localhost:3000"

    # Tracking settings
    TRACKING_BASE_URL: str = "http://localhost:8000" # Same as backend URL
    TRACKING_SIGNING_KEY: str = "ccirp-tracking-signing-key-change-in-prod"
    TRACKING_TOKEN_TTL_SECONDS: int = 2592000 # 30 days


    
    # AI Settings
    GOOGLE_API_KEY: str = ""

    # Celery Settings
    CELERY_BROKER_URL: str = "redis://localhost:6373/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6373/1"
    
    # Kafka Settings
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    
    # Redis Settings
    REDIS_URL: str = "redis://localhost:6373/0"

    # Background scheduler settings
    CAMPAIGN_SCHEDULER_INTERVAL_SECONDS: int = 15
    CAMPAIGN_QUEUE_BATCH_SIZE_CRITICAL: int = 25
    CAMPAIGN_QUEUE_BATCH_SIZE_HIGH: int = 20
    CAMPAIGN_QUEUE_BATCH_SIZE_MEDIUM: int = 15
    CAMPAIGN_QUEUE_BATCH_SIZE_LOW: int = 10
    CAMPAIGN_QUEUE_STALE_SECONDS: int = 300
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
