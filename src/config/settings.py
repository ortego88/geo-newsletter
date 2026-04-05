import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    """Configuración centralizada para toda la aplicación"""
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")
    OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
    OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
    
    # Telegram Configuration
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Database Configuration
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./geo_newsletter.db")
    
    # Redis Configuration
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Event Collection
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
    GDELT_API_KEY = os.getenv("GDELT_API_KEY", "")
    
    # Geographic Importance Weights (0-10)
    LOCATION_IMPORTANCE = {
        "Strait of Hormuz": 10.0,
        "Suez Canal": 9.8,
        "Panama Canal": 9.5,
        "Strait of Malacca": 9.5,
        "Persian Gulf": 9.8,
        "Middle East": 9.5,
        "Saudi Arabia": 9.0,
        "Iran": 8.8,
        "Russia": 8.5,
        "Ukraine": 8.5,
        "Taiwan": 8.7,
        "South China Sea": 8.6,
        "Eastern Europe": 8.0,
        "China": 8.2,
        "United States": 7.5,
        "Europe": 7.0,
        "India": 6.5,
        "Japan": 6.5,
    }
    
    # Event Severity Thresholds
    SEVERITY_CRITICAL = 75
    SEVERITY_HIGH = 50
    SEVERITY_MEDIUM = 30
    
    # Alert Thresholds
    ALERT_MIN_SCORE = 40
    ALERT_MIN_SOURCES = 2
    
    # Time Windows
    RECENT_NEWS_MINUTES = 180
    EARLY_SIGNAL_LOOKBACK_HOURS = 24
    
    # Source Priorities (1-5, 5 is highest)
    SOURCE_PRIORITIES = {
        "Reuters": 5,
        "Bloomberg": 5,
        "AP News": 5,
        "BBC": 4,
        "Sky News": 4,
        "GDELT": 4,
        "ACLED": 4,
        "LiveUA Map": 4,
        "Crisis24": 3,
        "OSINT": 3,
    }

settings = Settings()