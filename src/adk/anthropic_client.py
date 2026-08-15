"""Anthropic client construction, with a clear setup error if the API key is missing."""

from __future__ import annotations

import os

from anthropic import Anthropic

_SETUP_HINT = (
    "ANTHROPIC_API_KEY is not set. Create a key at https://console.anthropic.com/ "
    "and export it, e.g.:\n\n    export ANTHROPIC_API_KEY=sk-ant-...\n"
)


def get_anthropic_client() -> Anthropic:
    """Return an :class:`~anthropic.Anthropic` client built from ``ANTHROPIC_API_KEY``.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is unset, with setup instructions attached
            (rather than letting the SDK's own, less actionable error surface).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(_SETUP_HINT)
    return Anthropic(api_key=api_key)
