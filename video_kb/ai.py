"""
video_kb.ai - Fachada de compatibilidade.

Toda a logica de IA foi movida para video_kb.providers.openai_provider.
Este modulo reexporta os simbolos que pipeline.py, cli.py e codigo externo
usavam antes da refatoracao, garantindo retrocompatibilidade total.
"""

from __future__ import annotations

from collections.abc import Iterable

# Reexporta tipos e utilitarios que continuam usados externamente
from .models import FrameObservation, TranscriptSegment  # noqa: F401 (reexport)

# Reexporta constantes e classe principal do provider OpenAI
from .providers.openai_provider import (
    DEFAULT_TRANSCRIBE_MODEL,
    DEFAULT_VISION_MODEL,
    openai_api_key,
)
from .providers.openai_provider import (
    OpenAIProvider as OpenAIAnalyzer,
)


def openai_available() -> bool:
    """Retorna True se VIDEO_KB_OPENAI_API_KEY ou OPENAI_API_KEY estiver definida."""
    return bool(openai_api_key())


def select_visual_frames(frames: list[FrameObservation], limit: int) -> list[int]:
    """Seleciona indices de frames distribuidos uniformemente ate `limit`."""
    if limit <= 0 or len(frames) <= limit:
        return list(range(len(frames)))
    if limit == 1:
        return [0]
    step = (len(frames) - 1) / float(limit - 1)
    selected = []
    seen = set()
    for index in range(limit):
        pos = int(round(index * step))
        if pos not in seen:
            selected.append(pos)
            seen.add(pos)
    return selected


def transcript_near(
    segments: Iterable[TranscriptSegment],
    timestamp: float,
    window: float = 8.0,
) -> str:
    """Retorna texto dos segmentos dentro de `window` segundos do timestamp."""
    selected = [
        segment.text.strip()
        for segment in segments
        if segment.text
        and segment.start <= timestamp + window
        and segment.end >= timestamp - window
    ]
    return " ".join(selected)


__all__ = [
    "DEFAULT_TRANSCRIBE_MODEL",
    "DEFAULT_VISION_MODEL",
    "OpenAIAnalyzer",
    "openai_available",
    "select_visual_frames",
    "transcript_near",
]
