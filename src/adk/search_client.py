"""Tavily search client construction, with a clear setup error if the API key is missing."""

from __future__ import annotations

import os

from tavily import TavilyClient

_SETUP_HINT = (
    "TAVILY_API_KEY is not set. Create a key at https://tavily.com/ "
    "and export it, e.g.:\n\n    export TAVILY_API_KEY=tvly-...\n"
)


def get_search_client() -> TavilyClient:
    """Return a :class:`~tavily.TavilyClient` built from ``TAVILY_API_KEY``.

    Raises:
        RuntimeError: If ``TAVILY_API_KEY`` is unset, with setup instructions attached
            (rather than letting the SDK's own, less actionable error surface).
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(_SETUP_HINT)
    return TavilyClient(api_key=api_key)
