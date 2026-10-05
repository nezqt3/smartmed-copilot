import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BackendSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:4b"
    database: Path = Path("data/smartmed.sqlite3")
    timeout_s: float = Field(default=90, gt=0, le=300)
    repair_attempts: int = Field(default=1, ge=0, le=2)
    context_tokens: int = Field(default=8192, ge=4096, le=16384)
    output_tokens: int = Field(default=1600, ge=512, le=4096)

    @field_validator("ollama_url")
    @classmethod
    def local_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("此原型只允许本机Ollama地址，不允许外部模型API")
        return value.rstrip("/")


def load_backend_settings() -> BackendSettings:
    names = BackendSettings.model_fields
    values = {
        name: os.environ[f"SMARTMED_BACKEND_{name.upper()}"]
        for name in names
        if os.environ.get(f"SMARTMED_BACKEND_{name.upper()}")
    }
    return BackendSettings(**values)
