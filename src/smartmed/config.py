import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ModelBackend = Literal["mlx", "openai_compatible", "stub"]

_PREFIX = "SMARTMED_"


class Settings(BaseModel):
    root: Path = Path(".")
    data_dir: Path = Path("data")
    rules_dir: Path = Path("configs/rules")

    model_backend: ModelBackend = "mlx"
    mlx_model_path: str = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    api_base_url: str | None = None
    api_key_env: str = "SMARTMED_LLM_API_KEY"

    max_sequence_tokens: int = 4096
    max_new_tokens: int = 1500
    repair_attempts: int = Field(default=1, ge=0, le=3)

    field_confidence_floor: float = Field(default=0.55, ge=0.0, le=1.0)
    code_confidence_floor: float = Field(default=0.60, ge=0.0, le=1.0)

    draft_budget_s: float = 60.0
    rules_budget_ms: int = 300

    def path(self, relative: Path) -> Path:
        return relative if relative.is_absolute() else self.root / relative

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


_ENV_KEYS = {
    "root": Path,
    "data_dir": Path,
    "rules_dir": Path,
    "model_backend": str,
    "mlx_model_path": str,
    "api_base_url": str,
    "api_key_env": str,
    "max_sequence_tokens": int,
    "max_new_tokens": int,
    "repair_attempts": int,
    "field_confidence_floor": float,
    "code_confidence_floor": float,
    "draft_budget_s": float,
    "rules_budget_ms": int,
}


def load_settings() -> Settings:
    values = {}
    for name, caster in _ENV_KEYS.items():
        raw = os.environ.get(_PREFIX + name.upper())
        if raw is not None and raw != "":
            values[name] = caster(raw)
    return Settings(**values)
