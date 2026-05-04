"""Tests for runtime_config persistence and masking."""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_agent import runtime_config


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch):
    """Redirect CONFIG_PATH to a tmp file and clear env so tests are hermetic."""
    monkeypatch.setattr(runtime_config, "CONFIG_PATH", tmp_path / "config.json")
    for k in (
        "PAPER_AGENT_API_KEY",
        "PAPER_AGENT_BASE_URL",
        "PAPER_AGENT_FAST_MODEL",
        "PAPER_AGENT_SMART_MODEL",
        "PAPER_AGENT_DEEP_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_load_when_missing_returns_blank():
    cfg = runtime_config.load()
    assert cfg.api_key == "" and cfg.base_url == ""


def test_merged_falls_back_to_hardcoded_endpoint_only():
    """Endpoint/key have hardcoded fallbacks; models do NOT."""
    m = runtime_config.merged()
    assert m.api_key.startswith("sk-")
    assert m.base_url.startswith("http")
    # Models intentionally blank: must be picked from /v1/models in Settings.
    assert m.fast_model == ""
    assert m.smart_model == ""
    assert m.deep_model == ""


def test_env_can_override_models(monkeypatch):
    monkeypatch.setenv("PAPER_AGENT_FAST_MODEL", "test-fast")
    monkeypatch.setenv("PAPER_AGENT_SMART_MODEL", "test-smart")
    monkeypatch.setenv("PAPER_AGENT_DEEP_MODEL", "test-deep")
    m = runtime_config.merged()
    assert (m.fast_model, m.smart_model, m.deep_model) == (
        "test-fast",
        "test-smart",
        "test-deep",
    )


def test_update_persists_only_changed_fields():
    runtime_config.update({"base_url": "https://example.test/"})
    on_disk = runtime_config.load()
    assert on_disk.base_url == "https://example.test/"
    assert on_disk.api_key == ""  # not touched
    # Empty patch leaves things alone
    runtime_config.update({"base_url": ""})
    assert runtime_config.load().base_url == "https://example.test/"


def test_update_clear_sentinel_resets_field():
    runtime_config.update({"base_url": "https://example.test/"})
    runtime_config.update({"base_url": "__clear__"})
    assert runtime_config.load().base_url == ""


def test_to_public_dict_masks_key():
    runtime_config.update({"api_key": "sk-abcdef1234567890"})
    pub = runtime_config.merged().to_public_dict()
    assert pub["api_key_set"] is True
    assert "abcdef" not in pub["api_key_masked"]
    assert pub["api_key_masked"].startswith("sk-a")
    assert pub["api_key_masked"].endswith("90")
    # base_url and model fields are not masked
    assert pub["base_url"]
