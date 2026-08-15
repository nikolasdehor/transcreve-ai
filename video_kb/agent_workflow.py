from __future__ import annotations

import json
import logging
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .index import DuplicateRunError, RunIndex, resolve_index_path
from .pipeline import PipelineOptions, VideoKnowledgePipeline
from .sources import SourceProbe, detect_source
from .storage.registry import resolve_storage_name
from .utils import sha256_file, sha256_url

_LOGGER = logging.getLogger(__name__)


@dataclass
class AgentWorkflowOptions:
    out_dir: Path
    frame_interval: float = 5.0
    max_frames: int = 80
    visual_limit: int = 30
    ai_mode: str = "auto"
    vision_model: str = ""
    transcribe_model: str = ""
    language: str | None = None
    tesseract_lang: str = "por+eng"
    cookies_browser: str | None = None
    cookies: str | None = None
    video_format: str = "bv*+ba/b"
    provider_name: str = ""
    storage_backend: str = ""
    force: bool = False
    index_db: str | None = None
    should_index: bool = False
    question: str | None = None
    top_k: int = 5
    index_force: bool = False
    templates: tuple[str, ...] = ()


@dataclass
class AgentWorkflowResult:
    source: str
    probe: SourceProbe
    provider: str = ""
    run_id: str = ""
    workdir: str = ""
    markdown_path: str = ""
    analysis_path: str = ""
    template_paths: dict[str, str] = field(default_factory=dict)
    reused_existing: bool = False
    indexed: bool = False
    indexed_chunks: int = 0
    question: str | None = None
    answer: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    share_command: str = ""
    share_run_dir_command: str = ""
    share_catalog_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["probe"] = self.probe.to_dict()
        return data


def run_agent_workflow(
    source: str, options: AgentWorkflowOptions
) -> AgentWorkflowResult:
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
        return AgentWorkflowResult(
            source=source,
            probe=probe,
            warnings=["Fonte rejeitada por validacao de seguranca."],
        )
    if probe.kind == "unknown":
        return AgentWorkflowResult(
            source=source,
            probe=probe,
            warnings=["Fonte nao reconhecida como video/audio processavel."],
        )

    storage_name = resolve_storage_name(options.storage_backend or None)
    provider_name = _resolve_agent_provider(options.provider_name)
    pipeline_options = PipelineOptions(
        out_dir=options.out_dir,
        frame_interval=options.frame_interval,
        max_frames=options.max_frames,
        visual_limit=options.visual_limit,
        ai_mode=options.ai_mode,
        vision_model=options.vision_model,
        transcribe_model=options.transcribe_model,
        language=options.language,
        tesseract_lang=options.tesseract_lang,
        cookies_browser=options.cookies_browser,
        cookies=options.cookies,
        video_format=options.video_format,
        provider_name=options.provider_name,
        force=options.force,
        storage_backend=storage_name,
        index_db=options.index_db,
        templates=options.templates,
    )

    warnings: list[str] = []
    if probe.requires_cookies and not (options.cookies_browser or options.cookies):
        warnings.append(
            "Fonte pode exigir cookies. Se o download falhar, tente --cookies-browser."
        )

    try:
        analysis_result = VideoKnowledgePipeline(pipeline_options).run(source)
        result = _result_from_analysis(
            source,
            probe,
            analysis_result,
            warnings,
            provider_name,
            options.templates,
        )
    except DuplicateRunError as exc:
        result = _result_from_existing(source, probe, exc.existing, warnings)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Falha no fluxo principal do agente para fonte '%s'.", source)
        failed_run_id = _mark_latest_partial_failed(source, probe, options.index_db)
        failure_warnings = [
            *warnings,
            "Falha ao processar a analise. Consulte os logs.",
        ]
        if failed_run_id:
            failure_warnings.append(
                f"Run parcial '{failed_run_id}' marcado como failed para nao bloquear retry."
            )
        return AgentWorkflowResult(
            source=source,
            probe=probe,
            provider=provider_name,
            warnings=failure_warnings,
        )

    if not result.run_id:
        return result

    if options.question and not options.should_index:
        options.should_index = True

    if options.should_index:
        _index_result(result, options)

    if options.question:
        _answer_question(result, options)
        if not result.answer:
            result.question = options.question
            result.warnings.append(
                "Pergunta solicitada, mas nenhuma resposta foi gerada."
            )

    _attach_share_commands(result, options)
    return result


def dumps_agent_result(result: AgentWorkflowResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def _attach_share_commands(
    result: AgentWorkflowResult,
    options: AgentWorkflowOptions,
) -> AgentWorkflowResult:
    if not result.run_id:
        return result
    command = ["transcreveai"]
    if options.index_db:
        command.extend(["--index-db", options.index_db])
    command.extend(["share", result.run_id, "--json"])
    result.share_command = _shell_command(command)
    if result.workdir:
        result.share_run_dir_command = _shell_command(
            ["transcreveai", "share", "--run-dir", result.workdir, "--json"]
        )
    result.share_catalog_command = _shell_command(
        ["transcreveai", "share", "--catalog", "--json"]
    )
    return result


def _shell_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def artifact_reference_available(reference: str) -> bool:
    if not reference:
        return False
    parsed = urlparse(reference)
    if parsed.scheme and parsed.scheme != "file":
        return True
    if parsed.scheme == "file":
        return Path(parsed.path).exists()
    return Path(reference).exists()


def _result_from_analysis(
    source: str,
    probe: SourceProbe,
    analysis_result: Any,
    warnings: list[str],
    provider_name: str,
    templates: tuple[str, ...],
) -> AgentWorkflowResult:
    workdir = Path(str(analysis_result.workdir))
    return AgentWorkflowResult(
        source=source,
        probe=probe,
        provider=provider_name,
        run_id=str(analysis_result.run_id),
        workdir=str(workdir),
        markdown_path=str(workdir / "knowledge.md"),
        analysis_path=str(workdir / "analysis.json"),
        template_paths=_template_paths(workdir, templates),
        warnings=[*warnings, *list(getattr(analysis_result, "warnings", []) or [])],
    )


def _result_from_existing(
    source: str,
    probe: SourceProbe,
    existing: dict[str, Any],
    warnings: list[str],
) -> AgentWorkflowResult:
    run_id = str(existing.get("id") or "")
    output_dir = str(existing.get("output_dir") or "")
    analysis_path = str(existing.get("analysis_path") or "")
    markdown_path = str(existing.get("markdown_path") or "")
    if output_dir:
        workdir = output_dir
        analysis_path = analysis_path or str(Path(output_dir) / "analysis.json")
        markdown_path = markdown_path or str(Path(output_dir) / "knowledge.md")
    else:
        workdir = ""

    existing_warnings = [
        *warnings,
        "Run existente reutilizado; use --force para reprocessar.",
    ]
    if not artifact_reference_available(analysis_path):
        existing_warnings.append(
            f"Run existente '{run_id}' nao tem analysis.json disponivel; use --force."
        )

    return AgentWorkflowResult(
        source=source,
        probe=probe,
        provider=str(existing.get("provider") or ""),
        run_id=run_id,
        workdir=workdir,
        markdown_path=markdown_path,
        analysis_path=analysis_path,
        template_paths=_existing_template_paths(Path(workdir)) if workdir else {},
        reused_existing=True,
        warnings=existing_warnings,
    )


def _template_paths(workdir: Path, templates: tuple[str, ...]) -> dict[str, str]:
    paths: dict[str, str] = {}
    if "content" in templates:
        content_md = workdir / "content.md"
        content_json = workdir / "content.json"
        content_csv = workdir / "content.csv"
        if content_md.exists():
            paths["content"] = str(content_md)
        if content_json.exists():
            paths["content_json"] = str(content_json)
        if content_csv.exists():
            paths["content_csv"] = str(content_csv)
    if "skill" in templates:
        skill_md = workdir / "skill.md"
        skill_json = workdir / "skill.json"
        if skill_md.exists():
            paths["skill"] = str(skill_md)
        if skill_json.exists():
            paths["skill_json"] = str(skill_json)
    return paths


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


def index_analysis_result(
    *,
    run_id: str,
    analysis_path: str,
    provider_name: str,
    index_db: str | None,
    index_force: bool = False,
) -> tuple[bool, int, list[str]]:
    """Indexa um run ja analisado para RAG (embeddings).

    Compartilhada por analyze, agent run/batch e o servidor MCP, para que todo
    run com analise concluida termine indexado por padrao. Nunca levanta
    excecao: falhas de indexacao viram warnings e cabe ao caller decidir como
    exibi-las (a analise em si nunca deve falhar por causa da indexacao).

    Retorna (indexed, indexed_chunks, warnings).
    """
    warnings: list[str] = []
    retry_hint = f"Run registrado mas nao indexado; rode 'transcreveai index {run_id}'."
    if not analysis_path or not Path(analysis_path).exists():
        warnings.append(
            f"Nao foi possivel indexar: analysis.json nao encontrado. {retry_hint}"
        )
        return False, 0, warnings

    try:
        from .embeddings import EmbedNotSupportedError, index_run
        from .embeddings.store import EmbeddingStore
        from .providers import (
            CapabilityNotSupported,
            load_provider,
            resolve_provider_name,
        )
    except ImportError:
        _LOGGER.exception("Falha ao importar dependencias de RAG para indexacao.")
        warnings.append(f"Dependencias de RAG ausentes para indexacao. {retry_hint}")
        return False, 0, warnings

    resolved_provider = resolve_provider_name(provider_name or None)
    try:
        provider = load_provider(resolved_provider)
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Falha ao carregar provider '%s' para indexacao.", resolved_provider
        )
        warnings.append(
            f"Erro ao carregar provider para indexacao: {resolved_provider}. {retry_hint}"
        )
        return False, 0, warnings

    if "embed" not in provider.capabilities():
        warnings.append(f"{EmbedNotSupportedError(resolved_provider)} {retry_hint}")
        return False, 0, warnings

    try:
        db_path = resolve_index_path(index_db)
        with EmbeddingStore(db_path) as store:
            if store.has_indexed(run_id) and not index_force:
                return True, 0, warnings
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Falha ao consultar indice para o run '%s'.", run_id)
        warnings.append(f"Erro ao acessar o indice. Consulte os logs. {retry_hint}")
        return False, 0, warnings

    try:
        analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Falha ao ler analysis.json para indexacao: run_id=%s", run_id
        )
        warnings.append(
            f"Nao foi possivel ler analysis.json para indexacao. {retry_hint}"
        )
        return False, 0, warnings

    try:
        count = index_run(
            run_id=run_id,
            analysis=analysis,
            provider=provider,
            provider_name=resolved_provider,
            model_name=_get_embed_model(provider, resolved_provider),
            db_path=db_path,
            force=index_force,
        )
    except CapabilityNotSupported:
        _LOGGER.exception(
            "Provider '%s' sem capability requerida para indexacao.", resolved_provider
        )
        warnings.append(
            f"Provider '{resolved_provider}' nao suporta embeddings para indexacao. {retry_hint}"
        )
        return False, 0, warnings
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Falha ao indexar run '%s'.", run_id)
        warnings.append(f"Erro ao indexar run. Consulte os logs. {retry_hint}")
        return False, 0, warnings

    return True, count, warnings


def _index_result(result: AgentWorkflowResult, options: AgentWorkflowOptions) -> None:
    indexed, indexed_chunks, warnings = index_analysis_result(
        run_id=result.run_id,
        analysis_path=result.analysis_path,
        provider_name=options.provider_name,
        index_db=options.index_db,
        index_force=options.index_force,
    )
    result.indexed = indexed
    result.indexed_chunks = indexed_chunks
    result.warnings.extend(warnings)


def _answer_question(
    result: AgentWorkflowResult, options: AgentWorkflowOptions
) -> None:
    if not options.question:
        return
    try:
        from .embeddings.rag import ask
        from .providers import load_provider, resolve_provider_name
    except ImportError:
        _LOGGER.exception("Falha ao importar dependencias de RAG para ask.")
        result.warnings.append("Dependencias de RAG ausentes para responder pergunta.")
        return

    provider_name = resolve_provider_name(options.provider_name or None)
    try:
        provider = load_provider(provider_name)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Falha ao carregar provider '%s' para ask.", provider_name)
        result.warnings.append(
            f"Erro ao carregar provider para pergunta: {provider_name}."
        )
        return

    if "embed" not in provider.capabilities():
        result.warnings.append(
            f"Provider '{provider_name}' nao suporta embeddings para ask."
        )
        return

    try:
        rag_result = ask(
            question=options.question,
            embed_provider=provider,
            synth_provider=provider,
            db_path=resolve_index_path(options.index_db),
            top_k=options.top_k,
            run_ids=[result.run_id],
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Falha ao responder pergunta no fluxo do agente para run '%s'.",
            result.run_id,
        )
        result.question = options.question
        result.warnings.append("Erro ao responder pergunta. Consulte os logs.")
        return
    result.question = rag_result.question
    result.answer = rag_result.answer
    result.sources = [
        {
            "run_id": hit.run_id,
            "chunk_type": hit.chunk_type,
            "title": hit.title,
            "score": hit.score,
            "excerpt": hit.excerpt,
            "chapter_start": hit.chapter_start,
        }
        for hit in rag_result.sources
    ]


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


def _resolve_agent_provider(raw_provider: str | None) -> str:
    from .providers import resolve_provider_name

    return resolve_provider_name(raw_provider or None)


def _mark_latest_partial_failed(
    source: str,
    probe: SourceProbe,
    index_db: str | None,
) -> str:
    try:
        if probe.is_url:
            source_hash = sha256_url(source)
        else:
            source_hash = sha256_file(Path(probe.canonical))
    except Exception:  # noqa: BLE001
        return ""

    try:
        with RunIndex(resolve_index_path(index_db)) as idx:
            existing = idx.find_by_hash(source_hash)
            if not existing or existing.get("status") != "partial":
                return ""
            if existing.get("analysis_path"):
                return ""
            run_id = str(existing.get("id") or "")
            if not run_id:
                return ""
            idx.update_run(run_id, status="failed")
            return run_id
    except Exception:  # noqa: BLE001
        return ""
