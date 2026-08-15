from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Literal, TypeVar

from .agent_workflow import (
    AgentWorkflowOptions,
    artifact_reference_available,
    index_analysis_result,
    run_agent_workflow,
)
from .cli import _load_cli_dotenvs
from .index import DuplicateRunError, RunIndex, resolve_index_path
from .pipeline import PipelineOptions, VideoKnowledgePipeline
from .sources import SourceProbe, detect_source

_T = TypeVar("_T")


def mcp_sources_probe(source: str) -> dict[str, Any]:
    """Classify a source URL/path using the same probe as the CLI."""
    _prepare_runtime()
    try:
        probe = detect_source(source)
    except ValueError as exc:
        probe = SourceProbe(
            source=source,
            kind="unknown",
            adapter="unknown",
            is_url=False,
            canonical=source,
            notes=[str(exc)],
        )
    return {
        "ok": probe.kind != "unknown",
        "probe": probe.to_dict(),
        "warnings": []
        if probe.kind != "unknown"
        else ["Fonte nao processavel pelo probe."],
    }


def mcp_analyze(
    source: str,
    out: str = "outputs",
    provider: str = "",
    ai: Literal["auto", "off", "full"] = "auto",
    language: str | None = None,
    cookies_browser: str | None = None,
    cookies: str | None = None,
    force: bool = False,
    frame_interval: float = 5.0,
    max_frames: int = 80,
    visual_limit: int = 30,
    vision_model: str = "",
    transcribe_model: str = "",
    tesseract_lang: str = "por+eng",
    video_format: str = "bv*+ba/b",
    index_db: str | None = None,
    storage: str = "",
    templates: list[str] | None = None,
    no_index: bool = False,
) -> dict[str, Any]:
    """Run the core analysis pipeline and return artifact paths."""
    _prepare_runtime()
    options = PipelineOptions(
        out_dir=Path(out),
        frame_interval=frame_interval,
        max_frames=max_frames,
        visual_limit=visual_limit,
        ai_mode=ai,
        vision_model=vision_model,
        transcribe_model=transcribe_model,
        language=language,
        tesseract_lang=tesseract_lang,
        cookies_browser=cookies_browser,
        cookies=cookies,
        video_format=video_format,
        provider_name=provider,
        force=force,
        storage_backend=storage,
        index_db=index_db,
        templates=_normalize_templates(templates),
    )

    result, logs, error = _capture_stdio(
        lambda: VideoKnowledgePipeline(options).run(source)
    )
    if error is not None:
        if isinstance(error, DuplicateRunError):
            return _duplicate_payload(error, logs)
        return _error_payload("analysis_failed", "Falha ao processar a analise.", logs)
    assert result is not None  # sem erro implica pipeline.run() concluido com sucesso

    indexed = False
    indexed_chunks = 0
    index_warnings: list[str] = []
    if not no_index:
        indexed, indexed_chunks, index_warnings = index_analysis_result(
            run_id=str(result.run_id),
            analysis_path=str(Path(result.workdir) / "analysis.json"),
            provider_name=provider,
            index_db=index_db,
            index_force=force,
        )
    return _analysis_payload(
        result,
        logs,
        indexed=indexed,
        indexed_chunks=indexed_chunks,
        index_warnings=index_warnings,
    )


def mcp_agent_run(
    source: str,
    out: str = "outputs",
    provider: str = "",
    ai: Literal["auto", "off", "full"] = "auto",
    language: str | None = None,
    question: str | None = None,
    should_index: bool = False,
    index_force: bool = False,
    top_k: int = 5,
    cookies_browser: str | None = None,
    cookies: str | None = None,
    force: bool = False,
    frame_interval: float = 5.0,
    max_frames: int = 80,
    visual_limit: int = 30,
    vision_model: str = "",
    transcribe_model: str = "",
    tesseract_lang: str = "por+eng",
    video_format: str = "bv*+ba/b",
    index_db: str | None = None,
    storage: str = "",
    templates: list[str] | None = None,
) -> dict[str, Any]:
    """Run probe, analysis, optional indexing and optional RAG answer."""
    _prepare_runtime()
    options = AgentWorkflowOptions(
        out_dir=Path(out),
        frame_interval=frame_interval,
        max_frames=max_frames,
        visual_limit=visual_limit,
        ai_mode=ai,
        vision_model=vision_model,
        transcribe_model=transcribe_model,
        language=language,
        tesseract_lang=tesseract_lang,
        cookies_browser=cookies_browser,
        cookies=cookies,
        video_format=video_format,
        provider_name=provider,
        force=force,
        storage_backend=storage,
        index_db=index_db,
        should_index=should_index,
        question=question,
        top_k=top_k,
        index_force=index_force,
        templates=_normalize_templates(templates),
    )

    result, logs, error = _capture_stdio(lambda: run_agent_workflow(source, options))
    if error is not None:
        return _error_payload(
            "agent_run_failed", "Falha ao executar workflow de agente.", logs
        )
    if result is None:
        return _error_payload(
            "agent_run_failed", "Falha ao executar workflow de agente.", logs
        )

    payload = result.to_dict()
    payload["ok"] = _agent_result_ok(payload)
    payload["logs"] = logs
    return payload


def mcp_agent_batch(
    sources_file: str,
    out: str = "outputs-batch",
    provider: str = "",
    ai: Literal["auto", "off", "full"] = "auto",
    language: str | None = None,
    question: str | None = None,
    should_index: bool = False,
    index_force: bool = False,
    top_k: int = 5,
    cookies_browser: str | None = None,
    cookies: str | None = None,
    force: bool = False,
    frame_interval: float = 5.0,
    max_frames: int = 80,
    visual_limit: int = 30,
    vision_model: str = "",
    transcribe_model: str = "",
    tesseract_lang: str = "por+eng",
    video_format: str = "bv*+ba/b",
    index_db: str | None = None,
    storage: str = "",
    templates: list[str] | None = None,
    limit: int = 0,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Run agent workflow for a txt/csv/json list of sources."""
    _prepare_runtime()
    from .batch import run_agent_batch

    options = AgentWorkflowOptions(
        out_dir=Path(out),
        frame_interval=frame_interval,
        max_frames=max_frames,
        visual_limit=visual_limit,
        ai_mode=ai,
        vision_model=vision_model,
        transcribe_model=transcribe_model,
        language=language,
        tesseract_lang=tesseract_lang,
        cookies_browser=cookies_browser,
        cookies=cookies,
        video_format=video_format,
        provider_name=provider,
        force=force,
        storage_backend=storage,
        index_db=index_db,
        should_index=should_index,
        question=question,
        top_k=top_k,
        index_force=index_force,
        templates=_normalize_templates(templates),
    )
    summary, logs, error = _capture_stdio(
        lambda: run_agent_batch(
            Path(sources_file),
            options,
            limit=limit,
            fail_fast=fail_fast,
        )
    )
    if error is not None or summary is None:
        return _error_payload("agent_batch_failed", "Falha ao executar batch.", logs)
    summary["logs"] = logs
    return summary


def mcp_index(
    run_id: str = "",
    index_all: bool = False,
    provider: str = "",
    force: bool = False,
    index_db: str | None = None,
) -> dict[str, Any]:
    """Index one run or all runs for semantic search."""
    _prepare_runtime()
    if not run_id and not index_all:
        return _error_payload(
            "missing_run",
            "Informe run_id ou index_all=true para indexar os runs.",
            _empty_logs(),
        )

    try:
        from .embeddings import EmbedNotSupportedError, index_run
        from .embeddings.store import DimMismatchError, EmbeddingStore
        from .providers import (
            CapabilityNotSupported,
            load_provider,
            resolve_provider_name,
        )
    except ImportError as exc:
        return _error_payload(
            "missing_dependency",
            f"Dependencias de RAG ausentes: {exc}. Instale transcreve-ai[rag].",
            _empty_logs(),
        )

    provider_name = resolve_provider_name(provider or None)
    try:
        embed_provider = load_provider(provider_name)
    except Exception as exc:  # noqa: BLE001
        return _error_payload(
            "provider_load_failed",
            f"Erro ao carregar provider: {exc}",
            _empty_logs(),
        )

    if "embed" not in embed_provider.capabilities():
        return _error_payload(
            "embed_not_supported",
            str(EmbedNotSupportedError(provider_name)),
            _empty_logs(),
        )

    db_path = resolve_index_path(index_db)
    with RunIndex(db_path) as idx:
        runs = idx.list_runs(limit=9999) if index_all else [idx.get_run(run_id)]

    indexed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    model_name = _get_embed_model(embed_provider, provider_name)
    for run in runs:
        if not run:
            skipped.append({"run_id": run_id, "reason": "run_not_found"})
            continue
        current_run_id = str(run.get("id") or "")
        analysis_path = str(run.get("analysis_path") or "")
        if not analysis_path or not Path(analysis_path).exists():
            skipped.append(
                {"run_id": current_run_id, "reason": "analysis_json_not_found"}
            )
            continue

        with EmbeddingStore(db_path) as store:
            if store.has_indexed(current_run_id) and not force:
                skipped.append({"run_id": current_run_id, "reason": "already_indexed"})
                continue

        try:
            analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
            count = index_run(
                run_id=current_run_id,
                analysis=analysis,
                provider=embed_provider,
                provider_name=provider_name,
                model_name=model_name,
                db_path=db_path,
                force=force,
            )
        except DimMismatchError as exc:
            skipped.append(
                {"run_id": current_run_id, "reason": "dim_mismatch", "detail": str(exc)}
            )
            continue
        except CapabilityNotSupported as exc:
            return _error_payload("capability_not_supported", str(exc), _empty_logs())
        except Exception as exc:  # noqa: BLE001
            skipped.append(
                {"run_id": current_run_id, "reason": "index_failed", "detail": str(exc)}
            )
            continue

        indexed.append({"run_id": current_run_id, "chunks": count})

    return {
        "ok": bool(indexed) or not skipped,
        "provider": provider_name,
        "indexed": indexed,
        "skipped": skipped,
    }


def mcp_ask(
    question: str,
    provider: str = "",
    top_k: int = 5,
    run_ids: list[str] | None = None,
    search_only: bool = False,
    index_db: str | None = None,
) -> dict[str, Any]:
    """Ask a question over indexed runs."""
    _prepare_runtime()
    try:
        from .embeddings import EmbedNotSupportedError, ask, search
        from .providers import load_provider, resolve_provider_name
    except ImportError as exc:
        return _error_payload(
            "missing_dependency",
            f"Dependencias de RAG ausentes: {exc}. Instale transcreve-ai[rag].",
            _empty_logs(),
        )

    provider_name = resolve_provider_name(provider or None)
    try:
        rag_provider = load_provider(provider_name)
    except Exception as exc:  # noqa: BLE001
        return _error_payload(
            "provider_load_failed",
            f"Erro ao carregar provider: {exc}",
            _empty_logs(),
        )

    if "embed" not in rag_provider.capabilities():
        return _error_payload(
            "embed_not_supported",
            str(EmbedNotSupportedError(provider_name)),
            _empty_logs(),
        )

    clean_run_ids = [rid for rid in (run_ids or []) if rid] or None
    db_path = resolve_index_path(index_db)
    try:
        if search_only:
            hits = search(
                query=question,
                provider=rag_provider,
                db_path=db_path,
                top_k=top_k,
                run_ids=clean_run_ids,
            )
            return {
                "ok": True,
                "question": question,
                "answer": None,
                "sources": [_search_hit_to_dict(hit) for hit in hits],
            }

        result = ask(
            question=question,
            embed_provider=rag_provider,
            synth_provider=rag_provider,
            db_path=db_path,
            top_k=top_k,
            run_ids=clean_run_ids,
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(
            "ask_failed", f"Erro ao responder pergunta: {exc}", _empty_logs()
        )

    return {
        "ok": True,
        "question": result.question,
        "answer": result.answer,
        "sources": [_search_hit_to_dict(hit) for hit in result.sources],
    }


def mcp_runs_list(limit: int = 20, index_db: str | None = None) -> dict[str, Any]:
    """List known runs from the SQLite index."""
    _prepare_runtime()
    with RunIndex(resolve_index_path(index_db)) as idx:
        runs = idx.list_runs(limit=max(1, min(limit, 500)))
    return {"ok": True, "runs": runs}


def mcp_runs_show(run_id: str, index_db: str | None = None) -> dict[str, Any]:
    """Return one run from the SQLite index."""
    _prepare_runtime()
    with RunIndex(resolve_index_path(index_db)) as idx:
        run = idx.get_run(run_id)
    if run is None:
        return _error_payload(
            "run_not_found", f"Run '{run_id}' nao encontrado.", _empty_logs()
        )
    return {"ok": True, "run": run}


def mcp_share_run(
    run_id: str = "",
    run_dir: str | None = None,
    out: str = "",
    index_db: str | None = None,
) -> dict[str, Any]:
    """Package one indexed run as a durable shared-knowledge handoff."""
    _prepare_runtime()
    try:
        from .share import ShareRunError, share_run
    except ImportError as exc:
        return _error_payload(
            "share_unavailable", f"Dependencia ausente: {exc}", _empty_logs()
        )

    try:
        return share_run(
            run_id=run_id, run_dir=run_dir, out_dir=out or None, index_db=index_db
        )
    except ShareRunError as exc:
        return _error_payload("share_failed", str(exc), _empty_logs())
    except Exception as exc:
        return _error_payload(
            "share_failed",
            f"Falha inesperada ao compartilhar run: {exc}",
            _empty_logs(),
        )


def mcp_shared_catalog(
    out: str = "", limit: int = 20, query: str = ""
) -> dict[str, Any]:
    """List durable shared-knowledge packets."""
    _prepare_runtime()
    try:
        from .share import shared_catalog
    except ImportError as exc:
        return _error_payload(
            "share_unavailable", f"Dependencia ausente: {exc}", _empty_logs()
        )

    try:
        return shared_catalog(out_dir=out or None, limit=limit, query=query)
    except Exception as exc:
        return _error_payload(
            "share_failed",
            f"Falha inesperada ao listar catalogo compartilhado: {exc}",
            _empty_logs(),
        )


def create_server(host: str = "127.0.0.1", port: int = 8765) -> Any:
    """Create the optional FastMCP server."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "Dependencia opcional ausente. Instale com: pip install 'transcreve-ai[mcp]'"
        ) from exc

    _prepare_runtime()
    server = FastMCP(
        "TranscreveAI",
        instructions=(
            "Use TranscreveAI para transformar URLs/arquivos de video em dossies "
            "multimodais, indexar runs e responder perguntas com base nas evidencias."
        ),
        host=host,
        port=port,
    )

    @server.tool(name="sources_probe", structured_output=True)
    def sources_probe_tool(source: str) -> dict[str, Any]:
        return mcp_sources_probe(source)

    @server.tool(name="analyze", structured_output=True)
    def analyze_tool(
        source: str,
        out: str = "outputs",
        provider: str = "",
        ai: Literal["auto", "off", "full"] = "auto",
        language: str | None = None,
        cookies_browser: str | None = None,
        cookies: str | None = None,
        force: bool = False,
        frame_interval: float = 5.0,
        max_frames: int = 80,
        visual_limit: int = 30,
        vision_model: str = "",
        transcribe_model: str = "",
        tesseract_lang: str = "por+eng",
        video_format: str = "bv*+ba/b",
        index_db: str | None = None,
        storage: str = "",
        templates: list[str] | None = None,
        no_index: bool = False,
    ) -> dict[str, Any]:
        return mcp_analyze(
            source=source,
            out=out,
            provider=provider,
            ai=ai,
            language=language,
            cookies_browser=cookies_browser,
            cookies=cookies,
            force=force,
            frame_interval=frame_interval,
            max_frames=max_frames,
            visual_limit=visual_limit,
            vision_model=vision_model,
            transcribe_model=transcribe_model,
            tesseract_lang=tesseract_lang,
            video_format=video_format,
            index_db=index_db,
            storage=storage,
            templates=templates,
            no_index=no_index,
        )

    @server.tool(name="agent_run", structured_output=True)
    def agent_run_tool(
        source: str,
        out: str = "outputs",
        provider: str = "",
        ai: Literal["auto", "off", "full"] = "auto",
        language: str | None = None,
        question: str | None = None,
        should_index: bool = False,
        index_force: bool = False,
        top_k: int = 5,
        cookies_browser: str | None = None,
        cookies: str | None = None,
        force: bool = False,
        frame_interval: float = 5.0,
        max_frames: int = 80,
        visual_limit: int = 30,
        vision_model: str = "",
        transcribe_model: str = "",
        tesseract_lang: str = "por+eng",
        video_format: str = "bv*+ba/b",
        index_db: str | None = None,
        storage: str = "",
        templates: list[str] | None = None,
    ) -> dict[str, Any]:
        return mcp_agent_run(
            source=source,
            out=out,
            provider=provider,
            ai=ai,
            language=language,
            question=question,
            should_index=should_index,
            index_force=index_force,
            top_k=top_k,
            cookies_browser=cookies_browser,
            cookies=cookies,
            force=force,
            frame_interval=frame_interval,
            max_frames=max_frames,
            visual_limit=visual_limit,
            vision_model=vision_model,
            transcribe_model=transcribe_model,
            tesseract_lang=tesseract_lang,
            video_format=video_format,
            index_db=index_db,
            storage=storage,
            templates=templates,
        )

    @server.tool(name="agent_batch", structured_output=True)
    def agent_batch_tool(
        sources_file: str,
        out: str = "outputs-batch",
        provider: str = "",
        ai: Literal["auto", "off", "full"] = "auto",
        language: str | None = None,
        question: str | None = None,
        should_index: bool = False,
        index_force: bool = False,
        top_k: int = 5,
        cookies_browser: str | None = None,
        cookies: str | None = None,
        force: bool = False,
        frame_interval: float = 5.0,
        max_frames: int = 80,
        visual_limit: int = 30,
        vision_model: str = "",
        transcribe_model: str = "",
        tesseract_lang: str = "por+eng",
        video_format: str = "bv*+ba/b",
        index_db: str | None = None,
        storage: str = "",
        templates: list[str] | None = None,
        limit: int = 0,
        fail_fast: bool = False,
    ) -> dict[str, Any]:
        return mcp_agent_batch(
            sources_file=sources_file,
            out=out,
            provider=provider,
            ai=ai,
            language=language,
            question=question,
            should_index=should_index,
            index_force=index_force,
            top_k=top_k,
            cookies_browser=cookies_browser,
            cookies=cookies,
            force=force,
            frame_interval=frame_interval,
            max_frames=max_frames,
            visual_limit=visual_limit,
            vision_model=vision_model,
            transcribe_model=transcribe_model,
            tesseract_lang=tesseract_lang,
            video_format=video_format,
            index_db=index_db,
            storage=storage,
            templates=templates,
            limit=limit,
            fail_fast=fail_fast,
        )

    @server.tool(name="index", structured_output=True)
    def index_tool(
        run_id: str = "",
        index_all: bool = False,
        provider: str = "",
        force: bool = False,
        index_db: str | None = None,
    ) -> dict[str, Any]:
        return mcp_index(
            run_id=run_id,
            index_all=index_all,
            provider=provider,
            force=force,
            index_db=index_db,
        )

    @server.tool(name="ask", structured_output=True)
    def ask_tool(
        question: str,
        provider: str = "",
        top_k: int = 5,
        run_ids: list[str] | None = None,
        search_only: bool = False,
        index_db: str | None = None,
    ) -> dict[str, Any]:
        return mcp_ask(
            question=question,
            provider=provider,
            top_k=top_k,
            run_ids=run_ids,
            search_only=search_only,
            index_db=index_db,
        )

    @server.tool(name="runs_list", structured_output=True)
    def runs_list_tool(limit: int = 20, index_db: str | None = None) -> dict[str, Any]:
        return mcp_runs_list(limit=limit, index_db=index_db)

    @server.tool(name="runs_show", structured_output=True)
    def runs_show_tool(run_id: str, index_db: str | None = None) -> dict[str, Any]:
        return mcp_runs_show(run_id=run_id, index_db=index_db)

    @server.tool(name="share_run", structured_output=True)
    def share_run_tool(
        run_id: str = "",
        run_dir: str | None = None,
        out: str = "",
        index_db: str | None = None,
    ) -> dict[str, Any]:
        return mcp_share_run(run_id=run_id, run_dir=run_dir, out=out, index_db=index_db)

    @server.tool(name="shared_catalog", structured_output=True)
    def shared_catalog_tool(
        out: str = "", limit: int = 20, query: str = ""
    ) -> dict[str, Any]:
        return mcp_shared_catalog(out=out, limit=limit, query=query)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="transcreveai-mcp",
        description="Servidor MCP opcional do TranscreveAI.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transporte MCP.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host para SSE/HTTP.")
    parser.add_argument("--port", type=int, default=8765, help="Porta para SSE/HTTP.")
    parser.add_argument(
        "--mount-path", default=None, help="Mount path opcional para SSE."
    )
    args = parser.parse_args(argv)

    try:
        server = create_server(host=args.host, port=args.port)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    server.run(transport=args.transport, mount_path=args.mount_path)


def _prepare_runtime() -> None:
    _load_cli_dotenvs()


def _normalize_templates(raw_templates: list[str] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    templates: list[str] = []
    for template in raw_templates or []:
        name = template.strip().lower()
        if name in {"content", "skill"} and name not in seen:
            seen.add(name)
            templates.append(name)
    return tuple(templates)


def _capture_stdio(
    fn: Callable[[], _T]
) -> tuple[_T | None, dict[str, str], BaseException | None]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return fn(), _logs(stdout, stderr), None
    except BaseException as exc:  # noqa: BLE001
        return None, _logs(stdout, stderr), exc


def _logs(stdout: io.StringIO, stderr: io.StringIO) -> dict[str, str]:
    return {"stdout": stdout.getvalue(), "stderr": stderr.getvalue()}


def _empty_logs() -> dict[str, str]:
    return {"stdout": "", "stderr": ""}


def _analysis_payload(
    result: Any,
    logs: dict[str, str],
    *,
    indexed: bool = False,
    indexed_chunks: int = 0,
    index_warnings: list[str] | None = None,
) -> dict[str, Any]:
    workdir = Path(str(result.workdir))
    return {
        "ok": True,
        "run_id": str(result.run_id),
        "workdir": str(workdir),
        "analysis_path": str(workdir / "analysis.json"),
        "markdown_path": str(workdir / "knowledge.md"),
        "media_path": str(workdir / result.media_path) if result.media_path else "",
        "audio_path": str(workdir / result.audio_path) if result.audio_path else "",
        "source": result.source,
        "metadata": result.metadata.__dict__,
        "warnings": [*list(result.warnings or []), *(index_warnings or [])],
        "frames_count": len(result.frames or []),
        "transcript_chars": len(result.transcript_text or ""),
        "synthesis": result.synthesis.__dict__,
        "template_paths": _existing_template_paths(workdir),
        "indexed": indexed,
        "indexed_chunks": indexed_chunks,
        "logs": logs,
    }


def _duplicate_payload(
    error: DuplicateRunError, logs: dict[str, str]
) -> dict[str, Any]:
    existing = dict(error.existing)
    analysis_path = str(existing.get("analysis_path") or "")
    return {
        "ok": artifact_reference_available(analysis_path),
        "reused_existing": True,
        "run": existing,
        "warnings": ["Run existente reutilizado; use force=true para reprocessar."],
        "logs": logs,
    }


def _error_payload(code: str, message: str, logs: dict[str, str]) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}, "logs": logs}


def _agent_result_ok(payload: dict[str, Any]) -> bool:
    if not payload.get("run_id"):
        return False
    probe = payload.get("probe") or {}
    if probe.get("kind") == "unknown":
        return False
    if payload.get("question") and not payload.get("answer"):
        return False
    analysis_path = str(payload.get("analysis_path") or "")
    if analysis_path and not artifact_reference_available(analysis_path):
        return False
    return True


def _existing_template_paths(workdir: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    content_md = workdir / "content.md"
    content_json = workdir / "content.json"
    content_csv = workdir / "content.csv"
    skill_md = workdir / "skill.md"
    skill_json = workdir / "skill.json"
    if content_md.exists():
        paths["content"] = str(content_md)
    if content_json.exists():
        paths["content_json"] = str(content_json)
    if content_csv.exists():
        paths["content_csv"] = str(content_csv)
    if skill_md.exists():
        paths["skill"] = str(skill_md)
    if skill_json.exists():
        paths["skill_json"] = str(skill_json)
    return paths


def _search_hit_to_dict(hit: Any) -> dict[str, Any]:
    return {
        "run_id": hit.run_id,
        "chunk_id": hit.chunk_id,
        "chunk_type": hit.chunk_type,
        "title": hit.title,
        "score": hit.score,
        "excerpt": hit.excerpt,
        "chapter_start": hit.chapter_start,
        "metadata": dict(hit.metadata or {}),
    }


def _get_embed_model(provider: object, provider_name: str) -> str:
    for attr in ("_embed_model", "_embedding_model", "embed_model"):
        val = getattr(provider, attr, None)
        if val and isinstance(val, str):
            return val
    defaults = {
        "openai": "text-embedding-3-small",
        "local": "all-MiniLM-L6-v2",
        "gemini": "text-embedding-004",
    }
    return defaults.get(provider_name, "unknown")


if __name__ == "__main__":  # pragma: no cover
    main()
