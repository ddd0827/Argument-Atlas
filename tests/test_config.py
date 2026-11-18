from __future__ import annotations

from app.config import has_credentials, resolve_mode


def test_explicit_mock_wins(monkeypatch):
    monkeypatch.setenv("ATLAS_MODE", "mock")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert resolve_mode() == "mock"


def test_explicit_live_wins(monkeypatch):
    monkeypatch.setenv("ATLAS_MODE", "live")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert resolve_mode() == "live"


def test_auto_mode_uses_credentials(monkeypatch):
    monkeypatch.setenv("ATLAS_MODE", "auto")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert has_credentials() is False
    assert resolve_mode() == "mock"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert has_credentials() is True
    assert resolve_mode() == "live"
