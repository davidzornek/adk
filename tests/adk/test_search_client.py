from __future__ import annotations

import pytest
from tavily import TavilyClient

from adk.search_client import get_search_client


def test_get_search_client_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        get_search_client()


def test_get_search_client_returns_client_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    client = get_search_client()

    assert isinstance(client, TavilyClient)
    assert client.api_key == "test-key"
