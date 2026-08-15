"""Shared generate-evaluate-reflect configuration: retry budget."""

from __future__ import annotations

from pydantic import BaseModel


class GenerateEvaluateReflectConfig(BaseModel):
    """Centralized generate-evaluate-reflect configuration: retry budget."""

    max_attempts: int = 3
