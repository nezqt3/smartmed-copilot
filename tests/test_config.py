from pathlib import Path

import pytest

from smartmed.config import Settings, load_settings


def test_defaults_point_at_repo_conventions():
    settings = Settings()
    assert settings.model_backend == "mlx"
    assert settings.max_sequence_tokens == 4096
    assert settings.rules_budget_ms == 300
    assert settings.path(settings.rules_dir) == settings.root / "configs/rules"


def test_absolute_paths_survive():
    settings = Settings(data_dir=Path("/tmp/smartmed-data"))
    assert settings.path(settings.data_dir) == Path("/tmp/smartmed-data")


def test_env_overrides_are_typed(monkeypatch):
    monkeypatch.setenv("SMARTMED_MODEL_BACKEND", "openai_compatible")
    monkeypatch.setenv("SMARTMED_FIELD_CONFIDENCE_FLOOR", "0.7")
    monkeypatch.setenv("SMARTMED_RULES_BUDGET_MS", "150")
    monkeypatch.setenv("SMARTMED_API_BASE_URL", "http://127.0.0.1:8000/v1")
    settings = load_settings()
    assert settings.model_backend == "openai_compatible"
    assert settings.field_confidence_floor == pytest.approx(0.7)
    assert settings.rules_budget_ms == 150
    assert settings.api_base_url == "http://127.0.0.1:8000/v1"


def test_empty_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("SMARTMED_MAX_NEW_TOKENS", "")
    assert load_settings().max_new_tokens == Settings().max_new_tokens


def test_api_key_comes_from_indirection(monkeypatch):
    monkeypatch.setenv("SMARTMED_LLM_API_KEY", "secret")
    assert Settings().api_key == "secret"
    assert Settings().model_dump(exclude={"api_key"}).get("api_key") is None
