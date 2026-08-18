"""
Testes de retrocompatibilidade.

Cobre:
- Provider default e openai (sem configuracao extra)
- --ai off degrada graciosamente para sintese local (sem chamar rede)
- video_kb.ai reexporta simbolos que pipeline.py usa (compatibilidade pre-refatoracao)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video_kb.pipeline import PipelineOptions
from video_kb.providers.registry import _DEFAULT_PROVIDER, resolve_provider_name


class DefaultProviderEOpenAI(unittest.TestCase):
    """O provider padrao deve ser openai em todas as configuracoes."""

    def test_constante_default_e_openai(self) -> None:
        self.assertEqual(_DEFAULT_PROVIDER, "openai")

    def test_resolve_sem_env_retorna_openai(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "VIDEO_KB_PROVIDER"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(resolve_provider_name(None), "openai")

    def test_resolve_com_cli_vazio_retorna_openai(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "VIDEO_KB_PROVIDER"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(resolve_provider_name(""), "openai")

    def test_resolve_com_cli_none_retorna_openai(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "VIDEO_KB_PROVIDER"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(resolve_provider_name(None), "openai")


class AiOffDegradadaLocal(unittest.TestCase):
    """
    Quando --ai off, o pipeline nao deve chamar nenhuma API.
    A sintese local deve funcionar sem rede.
    """

    def _build_options(self, ai_mode: str = "off") -> PipelineOptions:
        return PipelineOptions(
            out_dir=Path("/tmp"),
            ai_mode=ai_mode,
            provider_name="openai",
        )

    def test_ai_off_nao_chama_load_provider(self) -> None:
        """Com ai_mode='off', load_provider nao deve ser chamado."""
        from video_kb.pipeline import VideoKnowledgePipeline

        opts = self._build_options(ai_mode="off")
        pipeline = VideoKnowledgePipeline(opts)

        # _should_use_ai deve retornar False com ai_mode='off'
        self.assertFalse(pipeline._should_use_ai("openai"))

    def test_ai_full_chama_load_provider(self) -> None:
        """Com ai_mode='full', _should_use_ai deve retornar True."""
        from video_kb.pipeline import VideoKnowledgePipeline

        opts = self._build_options(ai_mode="full")
        pipeline = VideoKnowledgePipeline(opts)
        self.assertTrue(pipeline._should_use_ai("openai"))

    def test_local_synthesis_sem_rede(self) -> None:
        """_local_synthesis nao deve chamar rede; deve retornar KnowledgeSynthesis valido."""
        from video_kb.models import (
            AnalysisResult,
            FrameObservation,
            KnowledgeSynthesis,
            SourceMetadata,
        )
        from video_kb.pipeline import _local_synthesis

        result = AnalysisResult(
            run_id="test-off",
            created_at="2026-06-02T00:00:00Z",
            source="video.mp4",
            workdir="/tmp",
            media_path="video.mp4",
            audio_path="audio.mp3",
            metadata=SourceMetadata(
                source="video.mp4",
                title="Teste ai off",
            ),
            frames=[FrameObservation(timestamp=1.0, image_path="f.jpg", ocr_text="texto ocr")],
        )

        synth = _local_synthesis(result)
        self.assertIsInstance(synth, KnowledgeSynthesis)
        self.assertIsInstance(synth.summary, str)
        self.assertGreater(len(synth.summary), 0)

    def test_local_synthesis_sem_frames(self) -> None:
        """_local_synthesis funciona mesmo sem frames (video sem OCR)."""
        from video_kb.models import AnalysisResult, KnowledgeSynthesis, SourceMetadata
        from video_kb.pipeline import _local_synthesis

        result = AnalysisResult(
            run_id="test-empty",
            created_at="2026-06-02T00:00:00Z",
            source="video.mp4",
            workdir="/tmp",
            media_path="video.mp4",
            audio_path="audio.mp3",
            metadata=SourceMetadata(source="video.mp4"),
        )

        synth = _local_synthesis(result)
        self.assertIsInstance(synth, KnowledgeSynthesis)


class PipelineAiModeDegradacao(unittest.TestCase):
    def _make_options(self, out_dir: Path, ai_mode: str) -> PipelineOptions:
        return PipelineOptions(
            out_dir=out_dir,
            ai_mode=ai_mode,
            provider_name="local",
            index_db=str(out_dir / "index.db"),
        )

    def test_full_nao_faz_fallback_local_na_falha(self) -> None:
        from video_kb.models import SourceMetadata, TranscriptSegment
        from video_kb.pipeline import VideoKnowledgePipeline

        fake_meta = SourceMetadata(source="video.mp4", title="Teste pipeline")

        def fake_fetch_media(
            _source: str, run_dir: Path, **_kwargs: object
        ) -> tuple[Path, SourceMetadata]:
            return Path(run_dir) / "video.mp4", fake_meta

        provider = MagicMock()
        provider.transcribe.return_value = MagicMock(
            text="ok", segments=[TranscriptSegment(0.0, 0.1, "ok")]
        )
        provider.synthesize.side_effect = RuntimeError("sintese falhou")

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            pipeline = VideoKnowledgePipeline(self._make_options(out_dir, ai_mode="full"))

            patches = [
                patch("video_kb.pipeline.fetch_media", side_effect=fake_fetch_media),
                patch("video_kb.pipeline.extract_audio"),
                patch("video_kb.pipeline.extract_frames", return_value=[]),
                patch("video_kb.pipeline.probe_duration", return_value=60.0),
                patch("video_kb.pipeline.ocr_image_detailed", return_value=("", "")),
                patch("video_kb.pipeline.choose_language", return_value=("por", None)),
                patch("video_kb.pipeline.write_json"),
                patch("video_kb.pipeline.write_markdown"),
                patch("video_kb.pipeline.sha256_url", return_value="hash-unico"),
                patch("video_kb.pipeline.sha256_file", return_value="hash-unico"),
                patch("video_kb.pipeline.ensure_dir", side_effect=lambda p: Path(str(p))),
                patch("video_kb.pipeline.load_provider", return_value=provider),
            ]
            for p in patches:
                p.start()
            try:
                with self.assertRaises(RuntimeError):
                    pipeline.run("video.mp4")
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_auto_faz_fallback_local_com_warning(self) -> None:
        from video_kb.models import SourceMetadata, TranscriptSegment
        from video_kb.pipeline import VideoKnowledgePipeline

        fake_meta = SourceMetadata(source="video.mp4", title="Teste pipeline")

        def fake_fetch_media(
            _source: str, run_dir: Path, **_kwargs: object
        ) -> tuple[Path, SourceMetadata]:
            return Path(run_dir) / "video.mp4", fake_meta

        provider = MagicMock()
        provider.transcribe.return_value = MagicMock(
            text="ok", segments=[TranscriptSegment(0.0, 0.1, "ok")]
        )
        provider.synthesize.side_effect = RuntimeError("sintese falhou")

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            pipeline = VideoKnowledgePipeline(self._make_options(out_dir, ai_mode="auto"))

            patches = [
                patch("video_kb.pipeline.fetch_media", side_effect=fake_fetch_media),
                patch("video_kb.pipeline.extract_audio"),
                patch("video_kb.pipeline.extract_frames", return_value=[]),
                patch("video_kb.pipeline.probe_duration", return_value=60.0),
                patch("video_kb.pipeline.ocr_image_detailed", return_value=("", "")),
                patch("video_kb.pipeline.choose_language", return_value=("por", None)),
                patch("video_kb.pipeline.write_json"),
                patch("video_kb.pipeline.write_markdown"),
                patch("video_kb.pipeline.sha256_url", return_value="hash-unico"),
                patch("video_kb.pipeline.sha256_file", return_value="hash-unico"),
                patch("video_kb.pipeline.ensure_dir", side_effect=lambda p: Path(str(p))),
                patch("video_kb.pipeline.load_provider", return_value=provider),
            ]
            for p in patches:
                p.start()
            try:
                result = pipeline.run("video.mp4")
                self.assertEqual(result.synthesis.raw.get("mode"), "local")
                self.assertTrue(
                    any("Camada de IA falhou" in w for w in result.warnings),
                    f"warnings inesperados: {result.warnings}",
                )
            finally:
                for p in reversed(patches):
                    p.stop()


class RunIdSeguro(unittest.TestCase):
    def test_resolve_run_id_gera_id_quando_nao_informado(self) -> None:
        from video_kb.pipeline import _resolve_run_id

        run_id = _resolve_run_id("https://example.com/video legal", "")

        self.assertRegex(run_id, r"^\d{8}T\d{6}Z-example-com-video-legal$")

    def test_resolve_run_id_aceita_id_explicito_simples(self) -> None:
        from video_kb.pipeline import _resolve_run_id

        self.assertEqual(_resolve_run_id("source.mp4", "run_ABC-123"), "run_ABC-123")

    def test_resolve_run_id_rejeita_path_traversal(self) -> None:
        from video_kb.pipeline import _resolve_run_id

        with self.assertRaises(ValueError):
            _resolve_run_id("source.mp4", "../evil")

    def test_resolve_run_id_rejeita_absoluto(self) -> None:
        from video_kb.pipeline import _resolve_run_id

        with self.assertRaises(ValueError):
            _resolve_run_id("source.mp4", "/tmp/evil")

    def test_resolve_run_dir_garante_out_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from video_kb.pipeline import _resolve_run_dir

            out_dir = Path(tmp) / "outputs"
            run_dir = _resolve_run_dir(out_dir, "run-001")

            self.assertTrue(run_dir.is_relative_to(out_dir.resolve()))
            self.assertTrue(run_dir.exists())


class ReexportCompatibilidade(unittest.TestCase):
    """
    video_kb.ai deve reexportar os simbolos que codigo externo
    e pipeline.py usavam antes da refatoracao de providers.
    """

    def test_openai_available_importavel(self) -> None:
        from video_kb.ai import openai_available

        # Deve ser callable
        self.assertTrue(callable(openai_available))

    def test_select_visual_frames_importavel(self) -> None:
        from video_kb.ai import select_visual_frames

        self.assertTrue(callable(select_visual_frames))

    def test_transcript_near_importavel(self) -> None:
        from video_kb.ai import transcript_near

        self.assertTrue(callable(transcript_near))

    def test_default_vision_model_importavel(self) -> None:
        from video_kb.ai import DEFAULT_VISION_MODEL

        self.assertIsInstance(DEFAULT_VISION_MODEL, str)

    def test_default_transcribe_model_importavel(self) -> None:
        from video_kb.ai import DEFAULT_TRANSCRIBE_MODEL

        self.assertIsInstance(DEFAULT_TRANSCRIBE_MODEL, str)

    def test_openai_available_sem_chave_retorna_false(self) -> None:
        from video_kb.ai import openai_available

        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            self.assertFalse(openai_available())

    def test_openai_available_com_chave_retorna_true(self) -> None:
        from video_kb.ai import openai_available

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fake"}, clear=False):
            self.assertTrue(openai_available())

    def test_select_visual_frames_distribui_uniformemente(self) -> None:
        from video_kb.ai import select_visual_frames
        from video_kb.models import FrameObservation

        frames = [FrameObservation(timestamp=float(i), image_path=f"f{i}.jpg") for i in range(10)]
        indices = select_visual_frames(frames, limit=3)
        self.assertEqual(len(indices), 3)
        # Primeiro e ultimo devem ser representados (distribuicao uniforme)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 9)

    def test_transcript_near_filtra_por_janela(self) -> None:
        from video_kb.ai import transcript_near
        from video_kb.models import TranscriptSegment

        segments = [
            TranscriptSegment(start=0.0, end=5.0, text="inicio"),
            TranscriptSegment(start=50.0, end=55.0, text="meio"),
            TranscriptSegment(start=100.0, end=105.0, text="fim"),
        ]
        # Janela de 8s ao redor de t=52: deve pegar "meio" apenas
        resultado = transcript_near(segments, timestamp=52.0, window=8.0)
        self.assertIn("meio", resultado)
        self.assertNotIn("inicio", resultado)
        self.assertNotIn("fim", resultado)


if __name__ == "__main__":
    unittest.main()
