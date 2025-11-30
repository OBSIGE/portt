import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

class Config:
    """Конфигурация бота"""

    # Токен бота от BotFather
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8382782689:AAEkm6ZNncJWwvSPbdXwGuiYRYfWqY9bXkA")

    # ID администратора (ваш ID в Telegram)
    ADMIN_ID = int(os.getenv("ADMIN_ID", 7760075871))
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@selbx")

    # Канал для обязательной подписки
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@JennNWD_official")

    # API ID и Hash от my.telegram.org
    API_ID = int(os.getenv("API_ID", 0))
    API_HASH = os.getenv("API_HASH", "")

    # Настройки базы данных
    DATABASE_NAME = os.getenv("DATABASE_NAME", "bot.db")

    # Настройки WebApp
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://portt-alpha-lake.vercel.app/")
    WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", 8080))

    # Настройки для платежей
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

    # Цены на функции (в рублях)
    PRICES = {
        "premium_subscription": 500,
        "global_mailing": 300,
        "target_chat_mailing": 200,
        "report_spam": 150
    }

    # Лимиты для пользователей
    LIMITS = {
        "max_attempts_per_mailing": 50,
        "min_interval_seconds": 30,
        "max_chats_per_user": 1000
    }

    # Настройки безопасности
    SESSION_TIMEOUT = 300  # 5 минут
    MAX_SESSIONS_PER_USER = 3

    # Пути
    SESSIONS_DIR = "sessions"
    LOGS_DIR = "logs"

    @classmethod
    def validate(cls):
        """Проверка корректности конфигурации"""
        required_vars = {
            "BOT_TOKEN": cls.BOT_TOKEN,
            "ADMIN_ID": cls.ADMIN_ID,
            "API_ID": cls.API_ID,
            "API_HASH": cls.API_HASH
        }

        missing = [var for var, value in required_vars.items() if not value]
        if missing:
            raise ValueError(f"Отсутствуют обязательные переменные: {', '.join(missing)}")

        # Создание необходимых директорий
        os.makedirs(cls.SESSIONS_DIR, exist_ok=True)
        os.makedirs(cls.LOGS_DIR, exist_ok=True)

# Создаем экземпляр конфигурации
config = Config()

# Пытаемся валидировать конфигурацию при импорте
try:
    config.validate()
except ValueError as e:
    print(f"Ошибка конфигурации: {e}")