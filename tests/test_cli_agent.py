from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video_kb.agent_workflow import AgentWorkflowOptions


def _run_cmd(argv: list[str]) -> tuple[str, str, int]:
    from video_kb.cli import main

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = 0
    with patch("sys.argv", ["transcreveai"] + argv):
        with patch("sys.stdout", buf_out):
            with patch("sys.stderr", buf_err):
                try:
                    main()
                except SystemExit as exc:
                    code = int(exc.code) if exc.code is not None else 0
    return buf_out.getvalue(), buf_err.getvalue(), code


class TestCliAgentRun(unittest.TestCase):
    def test_cli_loads_cwd_and_package_dotenvs(self) -> None:
        from video_kb import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            loaded: list[Path] = []

            with patch.object(cli.Path, "cwd", return_value=cwd):
                with patch(
                    "video_kb.cli.load_dotenv",
                    side_effect=lambda path: loaded.append(path),
                ):
                    cli._load_cli_dotenvs()

        self.assertIn(cwd / ".env", loaded)
        self.assertIn(Path(cli.__file__).resolve().parents[1] / ".env", loaded)

    def test_agent_run_unknown_source_json_exits_nonzero(self) -> None:
        out, err, code = _run_cmd(["agent", "run", "./README.md", "--json"])

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["probe"]["kind"], "unknown")
        self.assertFalse(payload["run_id"])
        self.assertGreater(len(payload["warnings"]), 0)

    def test_agent_run_unsafe_source_json_exits_nonzero(self) -> None:
        out, err, code = _run_cmd(
            ["agent", "run", "http://127.0.0.1/video.mp4", "--json"]
        )

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["probe"]["kind"], "unknown")
        self.assertFalse(payload["run_id"])
        warnings = " ".join(payload["warnings"])
        notes = " ".join(payload["probe"]["notes"])
        self.assertIn("validacao de seguranca", warnings)
        self.assertIn("local", notes)

    def test_agent_run_with_mocked_pipeline_outputs_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "video.mp4"
            source.write_bytes(b"fake")
            workdir = Path(tmpdir) / "outputs" / "run-001"
            workdir.mkdir(parents=True)
            (workdir / "knowledge.md").write_text("# Dossie\n", encoding="utf-8")
            (workdir / "analysis.json").write_text("{}", encoding="utf-8")
            index_db = Path(tmpdir) / "index.db"

            fake_result = SimpleNamespace(
                run_id="run-001",
                workdir=str(workdir),
                warnings=[],
            )

            with patch(
                "video_kb.agent_workflow.VideoKnowledgePipeline.run",
                return_value=fake_result,
            ):
                out, err, code = _run_cmd(
                    [
                        "--index-db",
                        str(index_db),
                        "agent",
                        "run",
                        str(source),
                        "--out",
                        str(workdir.parent),
                        "--json",
                    ]
                )

        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["probe"]["kind"], "local_file")
        self.assertEqual(payload["run_id"], "run-001")
        self.assertTrue(payload["markdown_path"].endswith("knowledge.md"))
        self.assertFalse(payload["reused_existing"])
        self.assertEqual(
            payload["share_command"],
            f"transcreveai --index-db {index_db} share run-001 --json",
        )
        self.assertEqual(
            payload["share_run_dir_command"],
            f"transcreveai share --run-dir {workdir} --json",
        )
        self.assertEqual(
            payload["share_catalog_command"],
            "transcreveai share --catalog --json",
        )

    def test_share_json_outputs_shared_agent_package(self) -> None:
        from video_kb.index import RunIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            run_dir = tmp / "outputs" / "run-001"
            run_dir.mkdir(parents=True)
            analysis_path = run_dir / "analysis.json"
            markdown_path = run_dir / "knowledge.md"
            analysis_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-001",
                        "source": "https://example.com/video.mp4",
                        "metadata": {"title": "Demo"},
                        "synthesis": {"summary": "Resumo."},
                    }
                ),
                encoding="utf-8",
            )
            markdown_path.write_text("# Demo\n", encoding="utf-8")
            index_db = tmp / "index.db"
            with RunIndex(index_db) as idx:
                idx.register(
                    "run-001",
                    "https://example.com/video.mp4",
                    "hash",
                    title="Demo",
                    output_dir=str(run_dir),
                    analysis_path=str(analysis_path),
                    markdown_path=str(markdown_path),
                )

            out, err, code = _run_cmd(
                [
                    "--index-db",
                    str(index_db),
                    "share",
                    "run-001",
                    "--out",
                    str(tmp / "shared"),
                    "--json",
                ]
            )
            payload = json.loads(out.strip() or "{}")
            manifest_exists = Path(payload["manifest_json"]).exists()
            catalog_out, catalog_err, catalog_code = _run_cmd(
                [
                    "share",
                    "--catalog",
                    "--out",
                    str(tmp / "shared"),
                    "--query",
                    "Resumo",
                    "--json",
                ]
            )
            catalog_payload = json.loads(catalog_out.strip() or "{}")

        self.assertEqual(code, 0, msg=err)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["run_id"], "run-001")
        self.assertTrue(manifest_exists)
        self.assertEqual(catalog_code, 0, msg=catalog_err)
        self.assertEqual(catalog_payload["query"], "Resumo")
        self.assertEqual(catalog_payload["entries"][0]["run_id"], "run-001")

    def test_share_json_outputs_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out, err, code = _run_cmd(
                [
                    "--index-db",
                    str(Path(tmpdir) / "index.db"),
                    "share",
                    "missing-run",
                    "--json",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out.strip() or "{}")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "share_failed")
        self.assertIn("missing-run", payload["error"]["message"])

    def test_agent_run_template_content_outputs_template_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "video.mp4"
            source.write_bytes(b"fake")
            workdir = Path(tmpdir) / "outputs" / "run-001"
            workdir.mkdir(parents=True)
            (workdir / "knowledge.md").write_text("# Dossie\n", encoding="utf-8")
            (workdir / "analysis.json").write_text("{}", encoding="utf-8")
            (workdir / "content.md").write_text("# Content\n", encoding="utf-8")
            (workdir / "content.json").write_text("{}", encoding="utf-8")

            fake_result = SimpleNamespace(
                run_id="run-001",
                workdir=str(workdir),
                warnings=[],
            )

            with patch(
                "video_kb.agent_workflow.VideoKnowledgePipeline.run",
                return_value=fake_result,
            ):
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "run",
                        str(source),
                        "--out",
                        str(workdir.parent),
                        "--template",
                        "content",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertTrue(payload["template_paths"]["content"].endswith("content.md"))
        self.assertTrue(
            payload["template_paths"]["content_json"].endswith("content.json")
        )

    def test_agent_batch_json_outputs_summary(self) -> None:
        from video_kb.agent_workflow import AgentWorkflowResult
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = tmp_path / "sources.txt"
            sources.write_text("https://example.com/video.mp4\n", encoding="utf-8")
            out_dir = tmp_path / "out"
            result = AgentWorkflowResult(
                source="https://example.com/video.mp4",
                probe=SourceProbe(
                    source="https://example.com/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://example.com/video.mp4",
                ),
                run_id="run-001",
                workdir=str(out_dir / "run-001"),
                analysis_path=str(out_dir / "run-001" / "analysis.json"),
                markdown_path=str(out_dir / "run-001" / "knowledge.md"),
                template_paths={
                    "content": str(out_dir / "run-001" / "content.md"),
                    "skill": str(out_dir / "run-001" / "skill.md"),
                },
            )

            with patch("video_kb.batch.run_agent_workflow", return_value=result):
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "batch",
                        str(sources),
                        "--out",
                        str(out_dir),
                        "--provider",
                        "local",
                        "--template",
                        "content",
                        "--template",
                        "skill",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["total"], 1)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["ok"], 1)
        expected_skill_path = str(out_dir / "run-001" / "skill.md")
        self.assertEqual(
            payload["items"][0]["template_paths"]["skill"], expected_skill_path
        )

    def test_agent_batch_passes_analysis_options_to_each_run(self) -> None:
        from video_kb.agent_workflow import AgentWorkflowResult
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = tmp_path / "sources.txt"
            sources.write_text("https://example.com/video.mp4\n", encoding="utf-8")
            out_dir = tmp_path / "out"
            captured_options: list[AgentWorkflowOptions] = []
            result = AgentWorkflowResult(
                source="https://example.com/video.mp4",
                probe=SourceProbe(
                    source="https://example.com/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://example.com/video.mp4",
                ),
                run_id="run-001",
                workdir=str(out_dir / "run-001"),
                analysis_path=str(out_dir / "run-001" / "analysis.json"),
                markdown_path=str(out_dir / "run-001" / "knowledge.md"),
            )

            def fake_run(_: str, options: AgentWorkflowOptions) -> AgentWorkflowResult:
                captured_options.append(options)
                return result

            with patch("video_kb.batch.run_agent_workflow", side_effect=fake_run):
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "batch",
                        str(sources),
                        "--out",
                        str(out_dir),
                        "--frame-interval",
                        "2.5",
                        "--max-frames",
                        "12",
                        "--visual-limit",
                        "4",
                        "--vision-model",
                        "vision-demo",
                        "--transcribe-model",
                        "transcribe-demo",
                        "--tesseract-lang",
                        "por",
                        "--provider",
                        "local",
                        "--storage",
                        "filesystem",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0, msg=err)
        self.assertTrue(json.loads(out.strip() or "{}")["items"][0]["ok"])
        self.assertEqual(len(captured_options), 1)
        options = captured_options[0]
        self.assertEqual(options.frame_interval, 2.5)
        self.assertEqual(options.max_frames, 12)
        self.assertEqual(options.visual_limit, 4)
        self.assertEqual(options.vision_model, "vision-demo")
        self.assertEqual(options.transcribe_model, "transcribe-demo")
        self.assertEqual(options.tesseract_lang, "por")
        self.assertEqual(options.provider_name, "local")
        self.assertEqual(options.storage_backend, "filesystem")

    def test_agent_batch_limit_stops_after_n_sources(self) -> None:
        from video_kb.agent_workflow import AgentWorkflowResult
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = tmp_path / "sources.txt"
            sources.write_text(
                "https://a.example/video.mp4\nhttps://b.example/video.mp4\n",
                encoding="utf-8",
            )
            out_dir = tmp_path / "out"
            result = AgentWorkflowResult(
                source="https://a.example/video.mp4",
                probe=SourceProbe(
                    source="https://a.example/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://a.example/video.mp4",
                ),
                run_id="run-001",
                workdir=str(out_dir / "run-001"),
                analysis_path=str(out_dir / "run-001" / "analysis.json"),
                markdown_path=str(out_dir / "run-001" / "knowledge.md"),
            )

            with patch(
                "video_kb.batch.run_agent_workflow", return_value=result
            ) as run_mock:
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "batch",
                        str(sources),
                        "--out",
                        str(out_dir),
                        "--limit",
                        "1",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(payload["total"], 1)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["ok"], 1)
        self.assertEqual(payload["items"][0]["position"], 1)

    def test_agent_batch_fail_fast_json_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = tmp_path / "sources.txt"
            sources.write_text(
                "https://a.example/video.mp4\nhttps://b.example/video.mp4\n",
                encoding="utf-8",
            )
            out_dir = tmp_path / "out"

            with patch(
                "video_kb.batch.run_agent_workflow",
                side_effect=RuntimeError("download falhou"),
            ) as run_mock:
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "batch",
                        str(sources),
                        "--out",
                        str(out_dir),
                        "--fail-fast",
                        "--json",
                    ]
                )

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(payload["total"], 1)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["ok"], 0)
        self.assertEqual(payload["failed"], 1)
        self.assertIn("download falhou", payload["items"][0]["error"])

    def test_agent_batch_strict_json_exits_nonzero_on_partial_failure(self) -> None:
        from video_kb.agent_workflow import AgentWorkflowResult
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = tmp_path / "sources.txt"
            sources.write_text(
                "https://a.example/video.mp4\nhttps://b.example/video.mp4\n",
                encoding="utf-8",
            )
            out_dir = tmp_path / "out"
            result = AgentWorkflowResult(
                source="https://b.example/video.mp4",
                probe=SourceProbe(
                    source="https://b.example/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://b.example/video.mp4",
                ),
                run_id="run-002",
                workdir=str(out_dir / "run-002"),
                analysis_path=str(out_dir / "run-002" / "analysis.json"),
                markdown_path=str(out_dir / "run-002" / "knowledge.md"),
            )

            with patch(
                "video_kb.batch.run_agent_workflow",
                side_effect=[RuntimeError("download falhou"), result],
            ) as run_mock:
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "batch",
                        str(sources),
                        "--out",
                        str(out_dir),
                        "--strict",
                        "--json",
                    ]
                )

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(run_mock.call_count, 2)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["ok"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["ok_count"], 1)
        self.assertEqual(payload["failed_count"], 1)

    def test_agent_batch_invalid_sources_file_json_returns_structured_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources = Path(tmpdir) / "sources.json"
            sources.write_text("{invalid", encoding="utf-8")

            out, err, code = _run_cmd(["agent", "batch", str(sources), "--json"])

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["ok"], 0)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["error"]["code"], "agent_batch_failed")

    def test_agent_run_pipeline_error_returns_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "video.mp4"
            source.write_bytes(b"fake")

            with patch(
                "video_kb.agent_workflow.VideoKnowledgePipeline.run",
                side_effect=RuntimeError("download falhou"),
            ):
                out, err, code = _run_cmd(["agent", "run", str(source), "--json"])

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["probe"]["kind"], "local_file")
        self.assertFalse(payload["run_id"])
        warnings = " ".join(payload["warnings"])
        self.assertNotIn("download falhou", warnings)
        self.assertIn("Consulte os logs", warnings)

    def test_agent_run_duplicate_without_artifacts_exits_nonzero(self) -> None:
        from video_kb.index import DuplicateRunError

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "video.mp4"
            source.write_bytes(b"fake")
            existing = {"id": "partial-run", "output_dir": "", "status": "partial"}

            with patch(
                "video_kb.agent_workflow.VideoKnowledgePipeline.run",
                side_effect=DuplicateRunError(existing),
            ):
                out, err, code = _run_cmd(["agent", "run", str(source), "--json"])

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["run_id"], "partial-run")
        self.assertFalse(payload["analysis_path"])
        self.assertIn("analysis.json", " ".join(payload["warnings"]))

    def test_agent_run_duplicate_remote_artifact_reference_exits_zero(self) -> None:
        from video_kb.index import DuplicateRunError

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "video.mp4"
            source.write_bytes(b"fake")
            existing = {
                "id": "remote-run",
                "output_dir": "s3://bucket/runs/remote-run",
                "analysis_path": "s3://bucket/runs/remote-run/analysis.json",
                "markdown_path": "s3://bucket/runs/remote-run/knowledge.md",
                "status": "completed",
            }

            with patch(
                "video_kb.agent_workflow.VideoKnowledgePipeline.run",
                side_effect=DuplicateRunError(existing),
            ):
                out, err, code = _run_cmd(["agent", "run", str(source), "--json"])

        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["run_id"], "remote-run")
        self.assertTrue(payload["reused_existing"])
        self.assertEqual(
            payload["analysis_path"], "s3://bucket/runs/remote-run/analysis.json"
        )

    def test_agent_run_question_without_answer_json_exits_nonzero(self) -> None:
        from video_kb.agent_workflow import AgentWorkflowResult
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            analysis_path = tmp_path / "analysis.json"
            analysis_path.write_text("{}", encoding="utf-8")
            result = AgentWorkflowResult(
                source="https://example.com/video.mp4",
                probe=SourceProbe(
                    source="https://example.com/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://example.com/video.mp4",
                ),
                run_id="run-001",
                workdir=str(tmp_path),
                analysis_path=str(analysis_path),
                markdown_path=str(tmp_path / "knowledge.md"),
                question="resuma",
                warnings=["Erro ao responder pergunta: sem provider"],
            )

            with patch(
                "video_kb.agent_workflow.run_agent_workflow", return_value=result
            ):
                out, err, code = _run_cmd(
                    [
                        "agent",
                        "run",
                        "https://example.com/video.mp4",
                        "--question",
                        "resuma",
                        "--json",
                    ]
                )

        self.assertEqual(code, 1, msg=err)
        payload = json.loads(out.strip() or "{}")
        self.assertEqual(payload["run_id"], "run-001")
        self.assertEqual(payload["question"], "resuma")
        self.assertIsNone(payload["answer"])

    def test_index_result_runtime_error_becomes_warning(self) -> None:
        from video_kb.agent_workflow import (
            AgentWorkflowOptions,
            AgentWorkflowResult,
            _index_result,
        )
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            analysis_path = tmp_path / "analysis.json"
            analysis_path.write_text("{}", encoding="utf-8")
            result = AgentWorkflowResult(
                source=str(tmp_path / "video.mp4"),
                probe=SourceProbe(
                    source=str(tmp_path / "video.mp4"),
                    kind="local_file",
                    adapter="local_file",
                    is_url=False,
                    canonical=str(tmp_path / "video.mp4"),
                ),
                run_id="run-001",
                analysis_path=str(analysis_path),
            )
            options = AgentWorkflowOptions(
                out_dir=tmp_path / "out",
                provider_name="local",
                index_db=str(tmp_path / "index.db"),
            )
            fake_provider = SimpleNamespace(capabilities=lambda: ["embed"])

            with patch("video_kb.providers.load_provider", return_value=fake_provider):
                with patch(
                    "video_kb.embeddings.index_run",
                    side_effect=RuntimeError("embed caiu"),
                ):
                    _index_result(result, options)

        self.assertFalse(result.indexed)
        warnings = " ".join(result.warnings)
        self.assertNotIn("embed caiu", warnings)
        self.assertIn("Consulte os logs", warnings)

    def test_answer_question_runtime_error_becomes_warning(self) -> None:
        from video_kb.agent_workflow import (
            AgentWorkflowOptions,
            AgentWorkflowResult,
            _answer_question,
        )
        from video_kb.sources import SourceProbe

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            result = AgentWorkflowResult(
                source="https://example.com/video.mp4",
                probe=SourceProbe(
                    source="https://example.com/video.mp4",
                    kind="direct_media_url",
                    adapter="yt_dlp_direct_media",
                    is_url=True,
                    canonical="https://example.com/video.mp4",
                ),
                run_id="run-001",
            )
            options = AgentWorkflowOptions(
                out_dir=tmp_path / "out",
                provider_name="local",
                index_db=str(tmp_path / "index.db"),
                question="resuma",
            )
            fake_provider = SimpleNamespace(capabilities=lambda: ["embed"])

            with patch("video_kb.providers.load_provider", return_value=fake_provider):
                with patch(
                    "video_kb.embeddings.rag.ask", side_effect=RuntimeError("rag caiu")
                ):
                    _answer_question(result, options)

        self.assertEqual(result.question, "resuma")
        self.assertIsNone(result.answer)
        warnings = " ".join(result.warnings)
        self.assertNotIn("rag caiu", warnings)
        self.assertIn("Consulte os logs", warnings)


# ---------------------------------------------------------------------------
# index_analysis_result - funcao pura compartilhada por analyze/agent/mcp
# ---------------------------------------------------------------------------


class TestIndexAnalysisResult(unittest.TestCase):
    def test_sucesso_retorna_indexed_e_chunks(self) -> None:
        from video_kb.agent_workflow import index_analysis_result

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            analysis_path = tmp_path / "analysis.json"
            analysis_path.write_text("{}", encoding="utf-8")
            fake_provider = SimpleNamespace(capabilities=lambda: ["embed"])

            with patch("video_kb.providers.load_provider", return_value=fake_provider):
                with patch("video_kb.embeddings.index_run", return_value=7):
                    indexed, chunks, warnings = index_analysis_result(
                        run_id="run-001",
                        analysis_path=str(analysis_path),
                        provider_name="local",
                        index_db=str(tmp_path / "index.db"),
                    )

        self.assertTrue(indexed)
        self.assertEqual(chunks, 7)
        self.assertEqual(warnings, [])

    def test_embed_nao_suportado_gera_warning_acionavel(self) -> None:
        from video_kb.agent_workflow import index_analysis_result

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            analysis_path = tmp_path / "analysis.json"
            analysis_path.write_text("{}", encoding="utf-8")
            fake_provider = SimpleNamespace(capabilities=lambda: [])

            with patch("video_kb.providers.load_provider", return_value=fake_provider):
                indexed, chunks, warnings = index_analysis_result(
                    run_id="run-002",
                    analysis_path=str(analysis_path),
                    provider_name="local",
                    index_db=str(tmp_path / "index.db"),
                )

        self.assertFalse(indexed)
        self.assertEqual(chunks, 0)
        joined = " ".join(warnings)
        self.assertIn("transcreveai index run-002", joined)


# ---------------------------------------------------------------------------
# analyze - auto-indexacao por padrao (nunca mais run sem embeddings)
# ---------------------------------------------------------------------------


class TestCliAnalyzeAutoIndex(unittest.TestCase):
    def _run_analyze(self, extra_args: list[str]) -> tuple[str, str, int, Path]:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            workdir = tmp_path / "outputs" / "run-001"
            workdir.mkdir(parents=True)
            (workdir / "knowledge.md").write_text("# Dossie\n", encoding="utf-8")
            (workdir / "analysis.json").write_text("{}", encoding="utf-8")
            db_path = tmp_path / "index.db"

            fake_result = SimpleNamespace(run_id="run-001", workdir=str(workdir))

            with patch(
                "video_kb.pipeline.VideoKnowledgePipeline.run",
                return_value=fake_result,
            ):
                out, err, code = _run_cmd(
                    [
                        "--index-db",
                        str(db_path),
                        "analyze",
                        "https://example.com/v",
                        "--out",
                        str(tmp_path / "outputs"),
                        "--ai",
                        "off",
                        "--provider",
                        "local",
                        *extra_args,
                    ]
                )
            return out, err, code, db_path

    def test_analyze_indexa_por_padrao(self) -> None:
        with patch(
            "video_kb.agent_workflow.index_analysis_result",
            return_value=(True, 3, []),
        ) as index_mock:
            out, err, code, db_path = self._run_analyze([])

        self.assertEqual(code, 0, msg=err)
        self.assertIn("Index: ok (3 chunks novos).", out)
        index_mock.assert_called_once()
        call_kwargs = index_mock.call_args.kwargs
        self.assertEqual(call_kwargs["run_id"], "run-001")
        self.assertTrue(call_kwargs["analysis_path"].endswith("analysis.json"))
        self.assertEqual(call_kwargs["provider_name"], "local")
        self.assertEqual(call_kwargs["index_db"], str(db_path))
        self.assertFalse(call_kwargs["index_force"])

    def test_analyze_no_index_pula_indexacao(self) -> None:
        with patch(
            "video_kb.agent_workflow.index_analysis_result",
            return_value=(True, 3, []),
        ) as index_mock:
            out, err, code, _db_path = self._run_analyze(["--no-index"])

        self.assertEqual(code, 0, msg=err)
        self.assertNotIn("Index: ok", out)
        index_mock.assert_not_called()

    def test_analyze_falha_de_indexacao_nao_derruba_analyze(self) -> None:
        falha = (
            "Erro ao indexar run. Consulte os logs. "
            "Run registrado mas nao indexado; rode 'transcreveai index run-001'."
        )
        with patch(
            "video_kb.agent_workflow.index_analysis_result",
            return_value=(False, 0, [falha]),
        ):
            out, err, code, _db_path = self._run_analyze([])

        self.assertEqual(code, 0, msg=err)
        self.assertIn(f"Aviso: {falha}", out)
        self.assertNotIn("Index: ok", out)

    def test_analyze_force_propaga_index_force(self) -> None:
        with patch(
            "video_kb.agent_workflow.index_analysis_result",
            return_value=(True, 1, []),
        ) as index_mock:
            out, err, code, _db_path = self._run_analyze(["--force"])

        self.assertEqual(code, 0, msg=err)
        index_mock.assert_called_once()
        self.assertTrue(index_mock.call_args.kwargs["index_force"])


if __name__ == "__main__":
    unittest.main()
