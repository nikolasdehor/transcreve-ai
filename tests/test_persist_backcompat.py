"""
Testes de retrocompatibilidade da camada de persistencia.

Cobre:
- analyze default usa storage=filesystem e mantem saida em disco
- Falha de indice nao derruba a analise (degrada com warning, nao excecao)
- Falha de storage backend nao derruba a analise (degrada com warning)
- AnalysisResult retornado e sempre valido independente de falhas de persistencia
- PipelineOptions aceita os campos de persistencia (force, storage_backend, index_db)
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_hash() -> str:
    """Gera hash unico para evitar colisao entre testes."""
    return f"hash-{uuid.uuid4().hex}"


def _make_options(out_dir: Path, index_db: str = "", **kwargs: object) -> Any:
    from video_kb.pipeline import PipelineOptions

    defaults: dict[str, object] = {
        "ai_mode": "off",
        "provider_name": "openai",
        "storage_backend": "filesystem",
        "force": False,
        "index_db": index_db or None,
    }
    defaults.update(kwargs)
    return PipelineOptions(out_dir=out_dir, **cast(dict[str, Any], defaults))


def _patch_pipeline_heavy(source_hash: str | None = None) -> list[object]:
    """
    Patches para o pipeline pesado (ffmpeg, whisper, etc).
    Usa hash unico por padrao para evitar colisao de dedupe entre testes.
    """
    from video_kb.models import SourceMetadata

    if source_hash is None:
        source_hash = _unique_hash()

    fake_media = cast(Any, MagicMock())
    fake_media.__str__.return_value = "/tmp/video.mp4"
    fake_meta = SourceMetadata(source="video.mp4", title="Backcompat Test")

    return [
        patch("video_kb.pipeline.fetch_media", return_value=(fake_media, fake_meta)),
        patch("video_kb.pipeline.extract_audio"),
        patch("video_kb.pipeline.extract_frames", return_value=[]),
        patch("video_kb.pipeline.probe_duration", return_value=60.0),
        patch("video_kb.pipeline.ocr_image_detailed", return_value=("", "")),
        patch("video_kb.pipeline.choose_language", return_value=("por", None)),
        patch("video_kb.pipeline.write_json"),
        patch("video_kb.pipeline.write_markdown"),
        patch("video_kb.pipeline.sha256_url", return_value=source_hash),
        patch("video_kb.pipeline.sha256_file", return_value=source_hash),
        patch("video_kb.pipeline.ensure_dir", side_effect=lambda p: Path(str(p))),
    ]


def _run_pipeline_with_patches(
    pipeline: Any,
    source: str,
    extra_patches: list[object] | None = None,
) -> Any:
    """Executa pipeline.run() com os patches ativos. Retorna resultado."""
    patches = _patch_pipeline_heavy()
    if extra_patches:
        patches.extend(extra_patches)
    for p in patches:
        p.start()  # type: ignore[attr-defined]
    try:
        return pipeline.run(source)  # type: ignore[attr-defined]
    finally:
        for p in patches:
            p.stop()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# PipelineOptions aceita campos de persistencia
# ---------------------------------------------------------------------------


class PipelineOptionsAceitaCamposPersistencia(unittest.TestCase):
    def test_storage_backend_default_filesystem(self) -> None:
        from video_kb.pipeline import PipelineOptions

        opts = PipelineOptions(out_dir=Path("/tmp"))
        self.assertEqual(opts.storage_backend, "filesystem")

    def test_force_default_false(self) -> None:
        from video_kb.pipeline import PipelineOptions

        opts = PipelineOptions(out_dir=Path("/tmp"))
        self.assertFalse(opts.force)

    def test_index_db_default_none(self) -> None:
        from video_kb.pipeline import PipelineOptions

        opts = PipelineOptions(out_dir=Path("/tmp"))
        self.assertIsNone(opts.index_db)

    def test_campos_customizaveis(self) -> None:
        from video_kb.pipeline import PipelineOptions

        opts = PipelineOptions(
            out_dir=Path("/tmp"),
            storage_backend="s3",
            force=True,
            index_db="/tmp/custom.db",
        )
        self.assertEqual(opts.storage_backend, "s3")
        self.assertTrue(opts.force)
        self.assertEqual(opts.index_db, "/tmp/custom.db")


# ---------------------------------------------------------------------------
# Analise com filesystem (storage default)
# ---------------------------------------------------------------------------


class AnalisePadraoComFilesystem(unittest.TestCase):
    def test_pipeline_retorna_analysis_result_valido(self) -> None:
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(pipeline, "https://example.com/video")

            self.assertIsInstance(result, AnalysisResult)
            self.assertIsNotNone(result.run_id)
            self.assertIsNotNone(result.synthesis)


# ---------------------------------------------------------------------------
# Degradacao gracil - falha de indice
# ---------------------------------------------------------------------------


class FalhaDeIndiceNaoDerruba(unittest.TestCase):
    def test_indice_falha_ao_conectar_result_valido(self) -> None:
        """Falha ao criar conexao com DB nao deve levantar excecao no pipeline."""
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[
                    patch(
                        "video_kb.pipeline.RunIndex._connect",
                        side_effect=RuntimeError("Falha simulada no DB"),
                    )
                ],
            )

            self.assertIsInstance(result, AnalysisResult)

    def test_indice_falha_no_register_result_valido(self) -> None:
        """Falha ao registrar no indice nao deve abortar o pipeline."""
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[
                    patch(
                        "video_kb.pipeline.RunIndex.register",
                        side_effect=Exception("Erro de escrita no DB"),
                    )
                ],
            )

            self.assertIsInstance(result, AnalysisResult)

    def test_indice_falha_no_update_result_valido(self) -> None:
        """Falha no update_run nao deve abortar o pipeline."""
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[
                    patch(
                        "video_kb.pipeline.RunIndex.update_run",
                        side_effect=Exception("Erro de update no DB"),
                    )
                ],
            )

            self.assertIsInstance(result, AnalysisResult)


# ---------------------------------------------------------------------------
# Degradacao gracil - falha de storage backend
# ---------------------------------------------------------------------------


class FalhaDeStorageNaoDerruba(unittest.TestCase):
    def test_storage_backend_falha_result_valido(self) -> None:
        """Falha no storage.save() adiciona warning mas nao aborta."""
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[
                    patch(
                        "video_kb.pipeline.load_storage",
                        side_effect=RuntimeError("Backend indisponivel"),
                    )
                ],
            )

            self.assertIsInstance(result, AnalysisResult)

    def test_storage_falha_adiciona_warning(self) -> None:
        """Quando storage falha, warnings deve conter aviso."""
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[
                    patch(
                        "video_kb.pipeline.load_storage",
                        side_effect=RuntimeError("Backend indisponivel"),
                    )
                ],
            )

            self.assertTrue(
                any("storage" in w.lower() or "backend" in w.lower() for w in result.warnings),
                f"Nenhum warning de storage encontrado em: {result.warnings}",
            )

    def test_storage_backend_save_levanta_exception_result_valido(self) -> None:
        """Se backend.save() levanta, pipeline ainda retorna resultado."""
        from video_kb.models import AnalysisResult
        from video_kb.pipeline import VideoKnowledgePipeline

        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "outputs"
            out_dir.mkdir()
            db_path = Path(d) / "index.db"
            opts = _make_options(out_dir, index_db=str(db_path))
            pipeline = VideoKnowledgePipeline(opts)  # type: ignore[arg-type]

            fake_backend = MagicMock()
            fake_backend.save.side_effect = Exception("save() falhou")

            result = _run_pipeline_with_patches(
                pipeline,
                "https://example.com/video",
                extra_patches=[patch("video_kb.pipeline.load_storage", return_value=fake_backend)],
            )

            self.assertIsInstance(result, AnalysisResult)


if __name__ == "__main__":
    unittest.main()
