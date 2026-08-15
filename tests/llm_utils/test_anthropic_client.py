from __future__ import annotations

import pytest
from anthropic import Anthropic

from llm_utils.anthropic_client import get_anthropic_client


def test_get_anthropic_client_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_anthropic_client()


def test_get_anthropic_client_returns_client_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    client = get_anthropic_client()

    assert isinstance(client, Anthropic)
    assert client.api_key == "test-key"
