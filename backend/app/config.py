from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Ordered pools of free models (first = preferred). A model that hits its free limit is skipped for a while.
    trinetra_models_smart: str = (
        "gemini/gemini-3.5-flash,groq/openai/gpt-oss-120b,gemini/gemini-2.5-flash,groq/qwen/qwen3.8-27b"
    )
    trinetra_models_fast: str = (
        "groq/openai/gpt-oss-20b,gemini/gemini-3.5-flash-lite,gemini/gemini-flash-lite-latest,groq/qwen/qwen3.8-27b"
    )
    # Visitors on the portfolio: Groq's big model first (fast, ~1,000 free requests a day) so strangers don't use up the
    # few daily Gemini requests that Tarun's own conversations need. Then the smart pool.
    trinetra_models_guest: str = "groq/openai/gpt-oss-120b,gemini/gemini-2.5-flash"
    database_url: str = f"sqlite:///{ROOT / 'trinetra.db'}"
    trinetra_timezone: str = "Asia/Kolkata"
    trinetra_user_name: str = "Tarun"
    trinetra_strictness: int = 3  # 1 = gentle, 5 = drill sergeant
    trinetra_voice: str = "en-US-ChristopherNeural"
    trinetra_reminder_lead_min: int = 5  # remind this many minutes before a block starts
    trinetra_scheduler: bool = True  # the heartbeat; off in tests
    groq_stt_model: str = "whisper-large-v3-turbo"
    trinetra_passcode: str = ""  # empty = no lock (only acceptable for tests / localhost dev)
    trinetra_secret: str = "dev-secret-change-me"
    trinetra_contact_email: str = "https://trinetra.app"  # web push (VAPID) subject; Apple rejects fake mailto: hosts
    data_dir: Path = ROOT / "data"
    trinetra_shortcut_key: str = ""  # lets iOS Shortcuts call /wake, /now and /report audio (nothing else)
    trinetra_cron_secret: str = ""  # the Cloudflare cron proves itself with this; empty = /cron disabled
    vapid_private_pem: str = ""  # in the cloud the push keys come from env vars (no disk)
    vapid_public_key: str = ""
    agents_dir: Path = ROOT / "agents"

    @property
    def llm_available(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
