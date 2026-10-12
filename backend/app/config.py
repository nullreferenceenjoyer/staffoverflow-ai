from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hr:hr@localhost:5432/hr_edu"

    secret_key: str = "dev-only-secret-key-change-it-before-deploy"
    access_token_ttl_min: int = 480
    # Соль для хэширования ФИО при импорте. Меняется один раз при установке:
    # после смены старые идентификаторы сотрудников перестанут совпадать с новыми.
    pii_hash_salt: str = "dev-salt-change-me"

    admin_email: str = "admin@example.ru"
    admin_password: str = "admin"
    seed_demo_data: bool = True
    # Профиль демо-данных: seed/local.json, если он есть, иначе seed/demo.json.
    # SEED_FILE задаёт файл явно.
    seed_dir: str = str(Path(__file__).resolve().parents[2] / "seed")
    seed_file: str = ""

    storage_dir: str = "/data/storage"

    # Локальная LLM (любой OpenAI-совместимый сервер: llama.cpp, LM Studio, Ollama)
    llm_base_url: str = ""
    llm_model: str = "local"
    llm_api_key: str = ""
    llm_timeout_s: int = 300
    llm_max_tokens: int = 900
    llm_temperature: float = 0.2
    # Qwen3 и похожие модели по умолчанию «думают» вслух; на CPU это дорого
    llm_disable_thinking: bool = True

    # Облачная модель — только для запросов без персональных данных, по умолчанию выключена
    cloud_llm_enabled: bool = False
    cloud_llm_base_url: str = ""
    cloud_llm_model: str = ""
    cloud_llm_api_key: str = ""

    # hashing — встроенный офлайн-эмбеддер; openai — внешний /v1/embeddings
    embedding_backend: str = "hashing"
    embedding_base_url: str = ""
    embedding_model: str = ""

    telegram_bot_token: str = ""
    max_bot_token: str = ""
    max_api_url: str = "https://platform-api.max.ru"
    deadline_check_interval_min: int = 60
    deadline_warn_days: int = 2

    # Начисления на ФОТ (страховые взносы), используются при оценке экономии
    payroll_tax_rate: float = 0.302
    # Отклонение меньше этого значения (в ставках) не считается проблемой
    deviation_tolerance: float = 0.25


@lru_cache
def get_settings() -> Settings:
    return Settings()
