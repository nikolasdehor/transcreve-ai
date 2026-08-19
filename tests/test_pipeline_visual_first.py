from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from video_kb.models import KnowledgeSynthesis, SourceMetadata, TranscriptSegment
from video_kb.pipeline import PipelineOptions, VideoKnowledgePipeline
from video_kb.providers.base import SynthesisContext, TranscribeResult


class FakeVisualProvider:
    seen_context: SynthesisContext | None = None

    def capabilities(self) -> set[str]:
        return {"transcribe", "vision", "synthesize"}

    def transcribe(self, *_: object, **__: object) -> TranscribeResult:
        return TranscribeResult(
            text="Transcrição e Legendas pela comunidade Amara.org",
            segments=[
                TranscriptSegment(
                    start=0.0,
                    end=3.0,
                    text="Transcrição e Legendas pela comunidade Amara.org",
                )
            ],
        )

    def describe_frame(self, *_: object, **__: object) -> str:
        return "Texto visivel: Playwright, Cypress, Selenium."

    def synthesize(self, ctx: SynthesisContext) -> KnowledgeSynthesis:
        self.seen_context = ctx
        return KnowledgeSynthesis(
            summary="Video visual-first sobre ferramentas de QA.",
            tools_or_products=["Playwright", "Cypress", "Selenium"],
        )


def test_pipeline_discards_low_value_transcript_and_marks_visual_first() -> None:
    provider = FakeVisualProvider()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        out_dir = tmp_path / "out"
        index_db = tmp_path / "index.db"

        def fake_fetch_media(_source: str, run_dir: Path, **_: object):
            source = run_dir / "source.mp4"
            source.write_bytes(b"video")
            return (
                source,
                SourceMetadata(
                    source="https://example.com/reel",
                    title="QA Reel",
                    duration=11.84,
                ),
            )

        def fake_extract_frames(
            _media_path: Path,
            frames_dir: Path,
            **_: object,
        ) -> list[Path]:
            frame = frames_dir / "frame_0001_00000s00.jpg"
            frame.write_bytes(b"frame")
            return [frame]

        options = PipelineOptions(
            out_dir=out_dir,
            ai_mode="full",
            provider_name="openai",
            run_id="visual-first-run",
            index_db=str(index_db),
            force=True,
        )

        with patch("video_kb.pipeline.fetch_media", side_effect=fake_fetch_media):
            with patch("video_kb.pipeline.extract_audio"):
                with patch("video_kb.pipeline.extract_frames", side_effect=fake_extract_frames):
                    with patch(
                        "video_kb.pipeline.ocr_image_detailed",
                        return_value=("Playwright\nCypress", "Playwright\nCypress"),
                    ):
                        with patch("video_kb.pipeline.load_provider", return_value=provider):
                            with patch("video_kb.pipeline.sha256_url", return_value="hash-visual"):
                                result = VideoKnowledgePipeline(options).run(
                                    "https://example.com/reel"
                                )
                                analysis = json.loads(
                                    (Path(result.workdir) / "analysis.json").read_text(
                                        encoding="utf-8"
                                    )
                                )

    assert result.transcript_text == ""
    assert result.transcript_segments == []
    assert result.evidence_profile["primary_signal"] == "vision"
    assert result.evidence_profile["speech"]["status"] == "discarded_low_value"
    assert provider.seen_context is not None
    assert provider.seen_context.transcript_text == ""
    assert provider.seen_context.evidence_profile["primary_signal"] == "vision"
    assert any(item.value == "Playwright" for item in result.evidence_items)
    playwright = next((item for item in result.evidence_items if item.value == "Playwright"), None)
    assert playwright is not None, "Expected Playwright in evidence_items"
    assert playwright.confidence == "high"
    assert any(support.signal == "ocr" for support in playwright.supports)
    assert any(item["value"] == "Playwright" for item in analysis["evidence_items"])
    assert any("baixa utilidade" in warning for warning in result.warnings)
