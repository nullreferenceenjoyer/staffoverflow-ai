from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hr:hr@localhost:5432/hr_edu"

    secret_key: str = "dev-only-secret-key-change-it-before-deploy"
    access_token_ttl_min: int = 480

    admin_email: str = "admin@example.ru"
    admin_password: str = "admin"
    seed_demo_data: bool = True
    # Профиль демо-данных: seed/local.json, если он есть, иначе seed/demo.json.
    # SEED_FILE задаёт файл явно.
    seed_dir: str = str(Path(__file__).resolve().parents[2] / "seed")
    seed_file: str = ""

    # Локальная модель для темы заявки (OpenAI-совместимый сервер: llama.cpp, LM Studio, Ollama)
    llm_base_url: str = ""
    llm_model: str = "local"
    llm_api_key: str = ""
    llm_timeout_s: int = 300
    llm_max_tokens: int = 900
    llm_temperature: float = 0.2
    # Qwen3 и похожие модели по умолчанию «думают» вслух; на CPU это дорого
    llm_disable_thinking: bool = True

    # Заявки: как часто проверять сроки, за сколько часов до срока напоминать
    # исполнителю и через сколько дней выполненная заявка закрывается сама,
    # если заявитель не ответил
    deadline_check_interval_min: int = 60
    request_warn_hours: int = 24
    request_autoclose_days: int = 3
    # Больше этого числа часов — работа уходит выездной бригаде, а не сотруднику на точке.
    # Больше второго — крупная: руководитель получает предупреждение, её можно разбить на этапы
    effort_brigade_hours: float = 4.0
    effort_major_hours: float = 16.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
