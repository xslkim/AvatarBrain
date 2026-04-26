from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent

#sk-48d08afe6bd94e8faca8e411dd7e4157
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("llm_provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        text = str(value or "openai").strip().lower()
        if text not in {"openai", "local"}:
            raise ValueError("LLM_PROVIDER must be one of: openai, local")
        return text

    @field_validator("http_host", mode="before")
    @classmethod
    def normalize_listen_host(cls, value: str) -> str:
        host = str(value or "0.0.0.0").strip().lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return "0.0.0.0"
        return host or "0.0.0.0"

    @field_validator("ssl_certfile", "ssl_keyfile", mode="after")
    @classmethod
    def resolve_ssl_path(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        p = Path(text)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return str(p.resolve())

    llm_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(default="", validation_alias="LLM_BASE_URL")
    llm_model: str = Field(default="", validation_alias="LLM_MODEL")
    llm_local_model_path: str = Field(default="", validation_alias="LLM_LOCAL_MODEL_PATH")
    llm_device: str = Field(default="auto", validation_alias="LLM_DEVICE")
    llm_timeout: int = 20
    llm_max_tokens: int = 300
    llm_temperature: float = 0.55
    llm_system_prompt: str = (
        "你是一个自然、友好的中文语音助手。"
        "请像真人当面聊天一样回答，口语化、简洁、自然，通常 1 到 2 句。"
        "不要使用书面公告腔，不要分点，不要长段解释，不要夸张语气词。"
        "不要虚构身份关系，不要自称家人、恋人或其他私人身份。"
        "避免客服套话，比如'随时为你服务'、'很高兴为你服务'、'请问有什么可以帮您'。"
        "优先使用短句和自然停顿，适合直接语音播报。"
    )

    http_host: str = Field(default="0.0.0.0", validation_alias="HTTP_HOST")
    http_port: int = Field(default=8019, validation_alias="HTTP_PORT")
    cors_origins: str = "*"
    ssl_certfile: str = ""
    ssl_keyfile: str = ""


settings = Settings()
