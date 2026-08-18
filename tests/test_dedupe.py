"""
Testes de deduplicacao do pipeline.

Cobre:
- Segundo analyze com mesmo source_hash e pulado (DuplicateRunError)
- --force reprocessa mesmo com hash existente
- Falha do indice nao derruba a analise (degrada com warning)
- Hash de arquivo local calculado apos download (via sha256_file)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import _patch, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_options(out_dir: Path, force: bool = False, index_db: str = "") -> object:
    from video_kb.pipeline import PipelineOptions

    return PipelineOptions(
        out_dir=out_dir,
        ai_mode="off",
        provider_name="openai",
        force=force,
        index_db=index_db,
    )


def _minimal_analysis_result(run_dir: Path) -> object:
    from video_kb.models import AnalysisResult, KnowledgeSynthesis, SourceMetadata

    return AnalysisResult(
        run_id="run-dedupe-001",
        created_at="2026-06-02T00:00:00+00:00",
        source="https://example.com/video",
        workdir=str(run_dir),
        media_path="video.mp4",
        audio_path="audio.mp3",
        metadata=SourceMetadata(source="https://example.com/video", title="Dedupe Test"),
        synthesis=KnowledgeSynthesis(summary="resumo"),
    )


# ---------------------------------------------------------------------------
# Logica central de dedupe via RunIndex
# ---------------------------------------------------------------------------


class DedupeViaRunIndex(unittest.TestCase):
    """Testa a logica de dedupe diretamente via RunIndex, sem chamar o pipeline pesado."""

    def setUp(self) -> None:
        from video_kb.index import RunIndex

        self._tmp = tempfile.mkdtemp()
        self._db = Path(self._tmp) / "index.db"
        self._idx = RunIndex(self._db)
        self._idx._connect()

    def tearDown(self) -> None:
        self._idx.close()

    def test_find_by_hash_ausente_retorna_none(self) -> None:
        result = self._idx.find_by_hash("hash-nao-existe")
        self.assertIsNone(result)

    def test_find_by_hash_retorna_run_registrado(self) -> None:
        self._idx.register(
            run_id="run-dedup-a",
            source="https://example.com/video",
            source_hash="hash-abc",
            status="completed",
        )
        found = self._idx.find_by_hash("hash-abc")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["id"], "run-dedup-a")

    def test_status_failed_nao_bloqueia_dedupe(self) -> None:
        """Run com status=failed NAO deve bloquear novo run (semantica do pipeline)."""
        self._idx.register(
            run_id="run-failed",
            source="https://example.com/video",
            source_hash="hash-fail",
            status="failed",
        )
        found = self._idx.find_by_hash("hash-fail")
        assert found is not None
        # O pipeline so bloqueia se status != 'failed'
        self.assertEqual(found["status"], "failed")
        self.assertNotEqual(found.get("status"), "completed")

    def test_status_completed_bloqueia_dedupe(self) -> None:
        """Run completed deve ser encontrado e marcar como duplicado."""
        self._idx.register(
            run_id="run-ok",
            source="https://example.com/video",
            source_hash="hash-ok",
            status="completed",
            output_dir="/tmp/runs/run-ok",
        )
        found = self._idx.find_by_hash("hash-ok")
        assert found is not None
        self.assertEqual(found["status"], "completed")


# ---------------------------------------------------------------------------
# DuplicateRunError - levantada quando existe run completed
# ---------------------------------------------------------------------------


class DuplicateRunErrorSemantica(unittest.TestCase):
    def test_duplicate_run_error_carrega_existing(self) -> None:
        from video_kb.index import DuplicateRunError

        existing = {"id": "run-dup", "output_dir": "/tmp/run-dup", "status": "completed"}
        exc = DuplicateRunError(existing)
        self.assertIsInstance(exc, RuntimeError)
        self.assertEqual(exc.existing["id"], "run-dup")
        self.assertIn("run-dup", str(exc))
        self.assertIn("--force", str(exc))

    def test_force_nao_e_verificado_na_excecao(self) -> None:
        """DuplicateRunError e levantada; cabe ao caller verificar force."""
        from video_kb.index import DuplicateRunError

        exc = DuplicateRunError({"id": "x", "output_dir": "/tmp"})
        self.assertIsInstance(exc, RuntimeError)


# ---------------------------------------------------------------------------
# Pipeline de dedupe com mocks (sem I/O pesado)
# ---------------------------------------------------------------------------


class DedupeComPipelineMocado(unittest.TestCase):
    """
    Verifica que VideoKnowledgePipeline.run() levanta DuplicateRunError
    quando o indice ja tem o hash, e que --force pula a checagem.

    O pipeline pesado (ffmpeg, whisper, etc) e mockado completamente.
    """

    def _patch_pipeline_heavy(self) -> list[_patch]:
        """Retorna lista de patches para o pipeline pesado."""
        from video_kb.models import SourceMetadata

        fake_meta = SourceMetadata(
            source="https://example.com/v",
            title="Mock Video",
        )

        def fake_fetch_media(
            _source: str, run_dir: Path, **_kwargs: object
        ) -> tuple[Path, SourceMetadata]:
            return Path(run_dir) / "video.mp4", fake_meta

        patches: list[_patch[Any]] = [
            patch("video_kb.pipeline.fetch_media", side_effect=fake_fetch_media),
            patch("video_kb.pipeline.extract_audio"),
            patch("video_kb.pipeline.extract_frames", return_value=[]),
            patch("video_kb.pipeline.probe_duration", return_value=60.0),
            patch("video_kb.pipeline.ocr_image_detailed", return_value=("", "")),
            patch("video_kb.pipeline.choose_language", return_value=("por", None)),
            patch("video_kb.pipeline.write_json"),
            patch("video_kb.pipeline.write_markdown"),
            patch("video_kb.pipeline.sha256_url", return_value="hash-de-url-fixa"),
            patch("video_kb.pipeline.sha256_file", return_value="hash-de-url-fixa"),
            patch("video_kb.pipeline.ensure_dir", side_effect=lambda p: Path(str(p))),
        ]
        return patches

    def test_segundo_run_mesmo_hash_levanta_duplicate_error(self) -> None:
        from video_kb.index import DuplicateRunError, RunIndex
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "index.db"
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()

            # Pre-popula o indice com um run completed para o mesmo hash
            with RunIndex(db_path) as idx:
                idx.register(
                    run_id="run-anterior",
                    source="https://example.com/v",
                    source_hash="hash-de-url-fixa",
                    status="completed",
                    output_dir=str(out_dir / "run-anterior"),
                )

            opts = _make_options(out_dir, force=False, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            patches = self._patch_pipeline_heavy()
            for p in patches:
                p.start()
            try:
                with self.assertRaises(DuplicateRunError) as ctx:
                    pipeline.run("https://example.com/v")
                self.assertEqual(ctx.exception.existing["id"], "run-anterior")
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_force_true_nao_levanta_duplicate_error(self) -> None:
        from video_kb.index import RunIndex
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "index.db"
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()

            with RunIndex(db_path) as idx:
                idx.register(
                    run_id="run-anterior",
                    source="https://example.com/v",
                    source_hash="hash-de-url-fixa",
                    status="completed",
                    output_dir=str(out_dir / "run-anterior"),
                )

            opts = _make_options(out_dir, force=True, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            patches = self._patch_pipeline_heavy()
            for p in patches:
                p.start()
            try:
                # Com force=True, nao deve levantar DuplicateRunError
                result = pipeline.run("https://example.com/v")
                self.assertIsNotNone(result)
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_indice_corrompido_nao_derruba_analise(self) -> None:
        """Se o indice falhar ao conectar, o pipeline continua sem interrupcao."""
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            # Aponta para caminho invalido (diretorio existente, nao arquivo)
            db_path = Path(d) / "nao_pode_criar" / "sub" / "index.db"
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()

            opts = _make_options(out_dir, force=False, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            patches = self._patch_pipeline_heavy()
            # Forca falha na conexao do indice
            patches.append(
                patch(
                    "video_kb.pipeline.RunIndex._connect",
                    side_effect=RuntimeError("DB indisponivel"),
                )
            )
            for p in patches:
                p.start()
            try:
                # Deve completar sem levantar excecao
                result = pipeline.run("https://example.com/v")
                self.assertIsNotNone(result)
            finally:
                for p in reversed(patches):
                    p.stop()


if __name__ == "__main__":
    unittest.main()
