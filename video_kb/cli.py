from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .index import DuplicateRunError, RunIndex, resolve_index_path
from .pipeline import PipelineOptions, VideoKnowledgePipeline
from .utils import load_dotenv

if TYPE_CHECKING:
    from .sources import SourceProbe

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcreveai",
        description="TranscreveAI extrai dossies multimodais de videos para base de conhecimento.",
    )

    # Flags globais
    parser.add_argument(
        "--index-db",
        default=None,
        metavar="PATH",
        help=(
            "Path do banco SQLite de indice. "
            "Sobreescreve VIDEO_KB_INDEX_DB. "
            "Default: ~/.transcreveai/index.db"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    sources_parser = subparsers.add_parser("sources", help="Inspeciona tipos de fontes")
    sources_sub = sources_parser.add_subparsers(dest="sources_command", required=True)

    probe_parser = sources_sub.add_parser(
        "probe",
        help="Detecta o tipo de uma URL ou arquivo de origem.",
    )
    probe_parser.add_argument("source", help="URL ou caminho local do video")
    probe_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Saida em JSON do probe.",
    )

    # ------------------------------------------------------------------
    # agent
    # ------------------------------------------------------------------
    agent_parser = subparsers.add_parser(
        "agent",
        help="Workflows de video intelligence para agentes",
    )
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=True)

    agent_run = agent_sub.add_parser(
        "run",
        help="Executa probe, analise e opcionalmente index/ask em uma origem.",
    )
    agent_run.add_argument("source", help="URL ou caminho local do video")
    agent_run.add_argument("--out", default="outputs", help="Diretorio de saida")
    agent_run.add_argument(
        "--frame-interval",
        type=float,
        default=5.0,
        help="Intervalo entre frames em segundos",
    )
    agent_run.add_argument(
        "--max-frames",
        type=int,
        default=80,
        help="Maximo de frames locais (0 = sem limite)",
    )
    agent_run.add_argument(
        "--visual-limit",
        type=int,
        default=30,
        help="Maximo de frames enviados para visao por IA",
    )
    agent_run.add_argument(
        "--ai",
        choices=["auto", "off", "full"],
        default="auto",
        help="auto usa IA se a chave de API do provider estiver definida",
    )
    agent_run.add_argument("--vision-model", default="", help="Modelo de visao/sintese")
    agent_run.add_argument(
        "--transcribe-model", default="", help="Modelo de transcricao"
    )
    agent_run.add_argument(
        "--language", default=None, help="Idioma do audio, ex: pt, en"
    )
    agent_run.add_argument(
        "--tesseract-lang", default="por+eng", help="Idioma OCR desejado"
    )
    agent_run.add_argument(
        "--cookies-browser",
        default=None,
        help="Browser para cookies do yt-dlp, ex: chrome",
    )
    agent_run.add_argument(
        "--cookies", default=None, help="Arquivo cookies.txt para yt-dlp"
    )
    agent_run.add_argument("--format", default="bv*+ba/b", help="Formato yt-dlp")
    agent_run.add_argument(
        "--provider",
        default="",
        metavar="NOME",
        help="Provider de IA/embedding: openai, local, gemini, anthropic ou externo.",
    )
    agent_run.add_argument(
        "--storage", default="", metavar="NOME", help="Backend de armazenamento"
    )
    agent_run.add_argument(
        "--template",
        choices=["content", "skill"],
        action="append",
        default=[],
        help="Gera artefato adicional: content ou skill.",
    )
    agent_run.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Reprocessa mesmo que a origem ja exista no indice.",
    )
    agent_run.add_argument(
        "--index",
        dest="should_index",
        action="store_true",
        default=False,
        help="Indexa o run apos a analise para RAG.",
    )
    agent_run.add_argument(
        "--index-force",
        action="store_true",
        default=False,
        help="Reindexa o run mesmo que ja existam embeddings.",
    )
    agent_run.add_argument(
        "--question", default=None, help="Pergunta a responder apos indexar"
    )
    agent_run.add_argument(
        "--top-k", type=int, default=5, help="Numero de trechos para RAG"
    )
    agent_run.add_argument(
        "--json", dest="as_json", action="store_true", help="Saida JSON"
    )

    agent_batch = agent_sub.add_parser(
        "batch",
        help="Executa o workflow de agente para uma lista txt/csv/json de origens.",
    )
    agent_batch.add_argument(
        "sources_file", help="Arquivo .txt, .csv ou .json com URLs/origens"
    )
    agent_batch.add_argument(
        "--out", default="outputs-batch", help="Diretorio de saida"
    )
    agent_batch.add_argument(
        "--frame-interval",
        type=float,
        default=5.0,
        help="Intervalo entre frames em segundos",
    )
    agent_batch.add_argument(
        "--max-frames",
        type=int,
        default=80,
        help="Maximo de frames locais por run (0 = sem limite)",
    )
    agent_batch.add_argument(
        "--visual-limit",
        type=int,
        default=30,
        help="Maximo de frames enviados para visao por IA em cada run",
    )
    agent_batch.add_argument(
        "--provider", default="", metavar="NOME", help="Provider de IA"
    )
    agent_batch.add_argument(
        "--ai",
        choices=["auto", "off", "full"],
        default="auto",
        help="Modo de IA repassado para cada run",
    )
    agent_batch.add_argument(
        "--vision-model", default="", help="Modelo de visao/sintese"
    )
    agent_batch.add_argument(
        "--transcribe-model", default="", help="Modelo de transcricao"
    )
    agent_batch.add_argument(
        "--language", default=None, help="Idioma do audio, ex: pt, en"
    )
    agent_batch.add_argument(
        "--tesseract-lang", default="por+eng", help="Idioma OCR desejado"
    )
    agent_batch.add_argument(
        "--cookies-browser", default=None, help="Browser para cookies"
    )
    agent_batch.add_argument("--cookies", default=None, help="Arquivo cookies.txt")
    agent_batch.add_argument("--format", default="bv*+ba/b", help="Formato yt-dlp")
    agent_batch.add_argument(
        "--storage",
        default="",
        metavar="NOME",
        help="Backend de armazenamento",
    )
    agent_batch.add_argument(
        "--template",
        choices=["content", "skill"],
        action="append",
        default=[],
        help="Gera artefatos adicionais para cada run.",
    )
    agent_batch.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Forca reprocessar",
    )
    agent_batch.add_argument(
        "--index",
        dest="should_index",
        action="store_true",
        default=False,
        help="Indexa cada run apos analise",
    )
    agent_batch.add_argument("--index-force", action="store_true", default=False)
    agent_batch.add_argument("--question", default=None, help="Pergunta para cada run")
    agent_batch.add_argument("--top-k", type=int, default=5)
    agent_batch.add_argument(
        "--limit", type=int, default=0, help="Limita numero de origens"
    )
    agent_batch.add_argument("--fail-fast", action="store_true", default=False)
    agent_batch.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Retorna exit code 1 se qualquer item do batch falhar",
    )
    agent_batch.add_argument(
        "--json", dest="as_json", action="store_true", help="Saida JSON"
    )

    # ------------------------------------------------------------------
    # analyze
    # ------------------------------------------------------------------
    analyze = subparsers.add_parser(
        "analyze", help="Analisa um link ou arquivo de video"
    )
    analyze.add_argument("source", help="URL ou caminho local do video")
    analyze.add_argument("--out", default="outputs", help="Diretorio de saida")
    analyze.add_argument(
        "--frame-interval",
        type=float,
        default=5.0,
        help="Intervalo entre frames em segundos",
    )
    analyze.add_argument(
        "--max-frames",
        type=int,
        default=80,
        help="Maximo de frames locais (0 = sem limite)",
    )
    analyze.add_argument(
        "--visual-limit",
        type=int,
        default=30,
        help="Maximo de frames enviados para visao por IA",
    )
    analyze.add_argument(
        "--ai",
        choices=["auto", "off", "full"],
        default="auto",
        help="auto usa IA se a chave de API do provider estiver definida",
    )
    analyze.add_argument("--vision-model", default="", help="Modelo de visao/sintese")
    analyze.add_argument("--transcribe-model", default="", help="Modelo de transcricao")
    analyze.add_argument("--language", default=None, help="Idioma do audio, ex: pt, en")
    analyze.add_argument(
        "--tesseract-lang", default="por+eng", help="Idioma OCR desejado"
    )
    analyze.add_argument(
        "--cookies-browser",
        default=None,
        help="Browser para cookies do yt-dlp, ex: chrome",
    )
    analyze.add_argument(
        "--cookies", default=None, help="Arquivo cookies.txt para yt-dlp"
    )
    analyze.add_argument("--format", default="bv*+ba/b", help="Formato yt-dlp")
    analyze.add_argument(
        "--provider",
        default="",
        metavar="NOME",
        help=(
            "Provider de IA a usar: openai (padrao), local, gemini, anthropic ou qualquer "
            "provider registrado via entry_points. Pode ser definido tambem via "
            "VIDEO_KB_PROVIDER. Precedencia: --provider > VIDEO_KB_PROVIDER > openai."
        ),
    )
    analyze.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Ignora dedupe: reprocessa mesmo que o source_hash ja exista no indice.",
    )
    analyze.add_argument(
        "--storage",
        default="",
        metavar="NOME",
        help=(
            "Backend de armazenamento: filesystem (padrao), obsidian, notion, supabase, s3. "
            "Sobreescreve VIDEO_KB_STORAGE."
        ),
    )
    analyze.add_argument(
        "--template",
        choices=["content", "skill"],
        action="append",
        default=[],
        help="Gera artefato adicional: content ou skill.",
    )
    analyze.add_argument(
        "--no-index",
        action="store_true",
        default=False,
        help="Nao gera embeddings apos a analise (por padrao, analyze indexa automaticamente).",
    )

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    runs_parser = subparsers.add_parser("runs", help="Gerencia o historico de runs")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)

    # runs list
    runs_list = runs_sub.add_parser("list", help="Lista runs do indice")
    runs_list.add_argument(
        "--limit", type=int, default=20, help="Numero maximo de entradas (default: 20)"
    )
    runs_list.add_argument(
        "--json", dest="as_json", action="store_true", help="Saida em JSON array"
    )
    runs_list.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="Filtrar por diretorio de saida",
    )

    # runs show
    runs_show = runs_sub.add_parser("show", help="Exibe detalhes de um run")
    runs_show.add_argument("run_id", help="ID do run")
    runs_show.add_argument(
        "--json", dest="as_json", action="store_true", help="Saida em JSON bruto"
    )

    # runs rm
    runs_rm = runs_sub.add_parser("rm", help="Remove um run do indice")
    runs_rm.add_argument("run_id", help="ID do run")
    runs_rm.add_argument(
        "--purge",
        action="store_true",
        default=False,
        help="Tambem deleta o output_dir do filesystem (rm -rf)",
    )
    runs_rm.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Nao pede confirmacao interativa",
    )

    # ------------------------------------------------------------------
    # share
    # ------------------------------------------------------------------
    share_parser = subparsers.add_parser(
        "share",
        help="Empacota um run como conhecimento compartilhavel para agentes",
    )
    share_parser.add_argument(
        "run_id", nargs="?", default="", help="ID do run no indice"
    )
    share_parser.add_argument(
        "--run-dir",
        default=None,
        metavar="PATH",
        help="Pasta de run com analysis.json e knowledge.md, sem consultar o indice",
    )
    share_parser.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Diretorio de destino (default: ~/.transcreveai/shared-knowledge)",
    )
    share_parser.add_argument(
        "--catalog",
        action="store_true",
        default=False,
        help="Lista o catalogo de conhecimento compartilhado",
    )
    share_parser.add_argument(
        "--limit", type=int, default=20, help="Limite para --catalog"
    )
    share_parser.add_argument("--query", default="", help="Filtra --catalog por termo")
    share_parser.add_argument(
        "--json", dest="as_json", action="store_true", help="Saida JSON"
    )

    # ------------------------------------------------------------------
    # index
    # ------------------------------------------------------------------
    index_parser = subparsers.add_parser(
        "index",
        help="Indexa runs para busca semantica (RAG)",
    )
    index_parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="ID do run a indexar (omita para usar --all)",
    )
    index_parser.add_argument(
        "--all",
        dest="index_all",
        action="store_true",
        default=False,
        help="Indexa todos os runs ainda nao indexados",
    )
    index_parser.add_argument(
        "--provider",
        default="",
        metavar="NOME",
        help="Provider de embed: openai, local ou gemini (default: VIDEO_KB_PROVIDER ou openai)",
    )
    index_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Reindexar mesmo que o run ja tenha embeddings",
    )

    # ------------------------------------------------------------------
    # ask
    # ------------------------------------------------------------------
    ask_parser = subparsers.add_parser(
        "ask",
        help="Faz uma pergunta sobre os videos indexados (RAG)",
    )
    ask_parser.add_argument("question", help="Pergunta a ser respondida")
    ask_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        metavar="N",
        help="Numero de trechos de contexto a recuperar (default: 5)",
    )
    ask_parser.add_argument(
        "--provider",
        default="",
        metavar="NOME",
        help="Provider de embed e sintese (default: VIDEO_KB_PROVIDER ou openai)",
    )
    ask_parser.add_argument(
        "--run-id",
        dest="run_ids",
        action="append",
        default=None,
        metavar="ID",
        help="Restringir busca a este run (repetivel)",
    )
    ask_parser.add_argument(
        "--search-only",
        action="store_true",
        default=False,
        help="Exibe apenas os trechos encontrados, sem chamar o LLM",
    )

    # ------------------------------------------------------------------
    # eval
    # ------------------------------------------------------------------
    eval_parser = subparsers.add_parser(
        "eval",
        help="Roda avaliacao comparativa de providers",
    )
    eval_parser.add_argument(
        "--dataset",
        default=None,
        metavar="PATH",
        help="JSON de dataset customizado",
    )
    eval_parser.add_argument(
        "--providers",
        default="",
        metavar="LISTA",
        help="Providers separados por virgula, ex: openai,gemini,local",
    )
    eval_parser.add_argument(
        "--judge",
        default=None,
        metavar="PROVIDER",
        help="Ativa LLM-as-judge com o provider informado",
    )
    eval_parser.add_argument(
        "--ai-mode",
        choices=["auto", "full", "off"],
        default="full",
        help="Modo de IA repassado ao pipeline",
    )
    eval_parser.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Diretorio de saida do relatorio",
    )
    eval_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Imprime results.json no stdout alem de salvar em disco",
    )
    eval_parser.add_argument(
        "--no-cost-warning",
        action="store_true",
        default=False,
        help="Suprime confirmacao interativa de custo",
    )

    # ------------------------------------------------------------------
    # serve
    # ------------------------------------------------------------------
    serve_parser = subparsers.add_parser(
        "serve", help="Inicia o servidor web TranscreveAI"
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Host do servidor (default: 127.0.0.1)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Porta do servidor (default: 8000)"
    )
    serve_parser.add_argument(
        "--out",
        default="outputs",
        help="Diretorio de saida dos jobs (default: outputs)",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Hot-reload (apenas desenvolvimento)",
    )

    return parser


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    _load_cli_dotenvs()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "index":
        _cmd_index(args)
    elif args.command == "ask":
        _cmd_ask(args)
    elif args.command == "eval":
        _cmd_eval(args)
    elif args.command == "runs":
        if args.runs_command == "list":
            _cmd_runs_list(args)
        elif args.runs_command == "show":
            _cmd_runs_show(args)
        elif args.runs_command == "rm":
            _cmd_runs_rm(args)
    elif args.command == "share":
        _cmd_share(args)
    elif args.command == "sources":
        if args.sources_command == "probe":
            _cmd_sources_probe(args)
    elif args.command == "agent":
        if args.agent_command == "run":
            _cmd_agent_run(args)
        elif args.agent_command == "batch":
            _cmd_agent_batch(args)


# ---------------------------------------------------------------------------
# Implementacoes dos comandos
# ---------------------------------------------------------------------------


def _load_cli_dotenvs() -> None:
    """Load local env files without overriding an already-exported shell env.

    Agent/skill calls often invoke the editable CLI from a task workspace instead
    of the repository root. Loading both locations keeps provider selection
    deterministic while preserving normal shell precedence.
    """
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        load_dotenv(path)


def _normalize_templates(raw_templates: list[str] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    templates: list[str] = []
    for template in raw_templates or []:
        name = template.strip().lower()
        if name and name not in seen:
            seen.add(name)
            templates.append(name)
    return tuple(templates)


def _template_output_paths(
    workdir: Path, templates: tuple[str, ...]
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if "content" in templates:
        content_md = workdir / "content.md"
        content_json = workdir / "content.json"
        content_csv = workdir / "content.csv"
        if content_md.exists():
            paths["content"] = content_md
        if content_json.exists():
            paths["content_json"] = content_json
        if content_csv.exists():
            paths["content_csv"] = content_csv
    if "skill" in templates:
        skill_md = workdir / "skill.md"
        skill_json = workdir / "skill.json"
        if skill_md.exists():
            paths["skill"] = skill_md
        if skill_json.exists():
            paths["skill_json"] = skill_json
    return paths


def _source_probe_message(probe: SourceProbe) -> str:
    from .sources import needs_cookie_message

    lines = [
        f"Origem: {probe.source}",
        f"Tipo: {probe.kind}",
        f"Adapter: {probe.adapter}",
        f"URL: {'Sim' if probe.is_url else 'Nao'}",
        f"Canonical: {probe.canonical}",
    ]

    if probe.notes:
        lines.append("Observacoes:")
        lines.extend(f" - {note}" for note in probe.notes)

    if probe.requires_cookies:
        cookie_msg = needs_cookie_message(probe)
        if cookie_msg:
            lines.append(f"Cookies: {cookie_msg}")
        else:
            lines.append("Cookies: provavelmente necessario para esta fonte.")

    if probe.kind == "generic_yt_dlp_url":
        lines.append(
            "Fallback: sem adapter dedicado; sera usado parser generico do yt-dlp."
        )
    return "\n".join(lines)


def _cmd_sources_probe(args: argparse.Namespace) -> None:
    from .sources import detect_source

    try:
        probe = detect_source(args.source)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(probe.to_dict(), ensure_ascii=False, indent=2))
        return

    print(_source_probe_message(probe))


def _cmd_agent_run(args: argparse.Namespace) -> None:
    import contextlib
    import io

    from .agent_workflow import (
        AgentWorkflowOptions,
        artifact_reference_available,
        dumps_agent_result,
        run_agent_workflow,
    )

    options = AgentWorkflowOptions(
        out_dir=Path(args.out),
        frame_interval=args.frame_interval,
        max_frames=args.max_frames,
        visual_limit=args.visual_limit,
        ai_mode=args.ai,
        vision_model=args.vision_model,
        transcribe_model=args.transcribe_model,
        language=args.language,
        tesseract_lang=args.tesseract_lang,
        cookies_browser=args.cookies_browser,
        cookies=args.cookies,
        video_format=args.format,
        provider_name=args.provider,
        storage_backend=args.storage,
        force=args.force,
        index_db=getattr(args, "index_db", None),
        should_index=args.should_index,
        question=args.question,
        top_k=args.top_k,
        index_force=args.index_force,
        templates=_normalize_templates(args.template),
    )
    if args.as_json:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            result = run_agent_workflow(args.source, options)
    else:
        result = run_agent_workflow(args.source, options)
    has_artifact = artifact_reference_available(result.analysis_path)
    question_failed = bool(args.question and not result.answer)

    if args.as_json:
        print(dumps_agent_result(result))
        if not result.run_id or not has_artifact or question_failed:
            sys.exit(1)
        return

    print(f"Fonte: {result.source}")
    print(f"Tipo: {result.probe.kind}")
    print(f"Adapter: {result.probe.adapter}")
    if result.probe.requires_cookies:
        print("Cookies: esta fonte pode exigir cookies/autenticacao.")
    if result.run_id:
        print(f"Run: {result.run_id}")
        print(f"Diretorio: {result.workdir}")
        print(f"Markdown: {result.markdown_path}")
        print(f"JSON: {result.analysis_path}")
        if result.share_command:
            print(f"Share: {result.share_command}")
        for name, path in result.template_paths.items():
            print(f"Template {name}: {path}")
    if result.reused_existing:
        print("Reuso: run existente reutilizado.")
    if result.indexed:
        print(f"Index: ok ({result.indexed_chunks} chunks novos).")
    if result.question:
        print(f"\nPergunta: {result.question}\n")
        print(f"Resposta:\n{result.answer or ''}")
    if result.sources:
        print("\nFontes:")
        for i, hit in enumerate(result.sources, start=1):
            score = hit.get("score")
            score_pct = (
                f"{float(score) * 100:.1f}%" if isinstance(score, (int, float)) else "?"
            )
            title = hit.get("title") or hit.get("run_id") or "fonte"
            print(f"  [{i}] {title} - score: {score_pct}")
    if result.warnings:
        print("\nAvisos:")
        for warning in result.warnings:
            print(f" - {warning}")
    if not result.run_id or not has_artifact or question_failed:
        sys.exit(1)


def _cmd_agent_batch(args: argparse.Namespace) -> None:
    import contextlib
    import io

    from .agent_workflow import AgentWorkflowOptions
    from .batch import run_agent_batch

    options = AgentWorkflowOptions(
        out_dir=Path(args.out),
        frame_interval=args.frame_interval,
        max_frames=args.max_frames,
        visual_limit=args.visual_limit,
        ai_mode=args.ai,
        vision_model=args.vision_model,
        transcribe_model=args.transcribe_model,
        language=args.language,
        tesseract_lang=args.tesseract_lang,
        cookies_browser=args.cookies_browser,
        cookies=args.cookies,
        video_format=args.format,
        provider_name=args.provider,
        storage_backend=args.storage,
        force=args.force,
        index_db=getattr(args, "index_db", None),
        should_index=args.should_index,
        question=args.question,
        top_k=args.top_k,
        index_force=args.index_force,
        templates=_normalize_templates(args.template),
    )

    try:
        if args.as_json:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                summary = run_agent_batch(
                    Path(args.sources_file),
                    options,
                    limit=args.limit,
                    fail_fast=args.fail_fast,
                )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            summary = run_agent_batch(
                Path(args.sources_file),
                options,
                limit=args.limit,
                fail_fast=args.fail_fast,
            )
    except Exception as exc:  # noqa: BLE001
        summary = _batch_error_summary(Path(args.sources_file), exc)
        if args.as_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.as_json:
        print(f"OK: {args.out}")
        print(f"Total: {summary['total']}")
        print(f"Sucesso: {summary['ok']}")
        print(f"Falhas: {summary['failed']}")
        print(f"Resumo: {Path(args.out) / 'batch.md'}")
        print(f"JSON: {Path(args.out) / 'batch.json'}")

    if summary["failed"] and (args.fail_fast or args.strict):
        sys.exit(1)


def _batch_error_summary(sources_file: Path, exc: Exception) -> dict[str, object]:
    return {
        "source_file": str(sources_file),
        "total": 0,
        "success": False,
        "ok": 0,
        "failed": 1,
        "ok_count": 0,
        "failed_count": 1,
        "items": [],
        "error": {
            "code": "agent_batch_failed",
            "message": str(exc),
        },
        "warnings": ["Falha ao carregar ou executar o batch."],
    }


def _cmd_eval(args: argparse.Namespace) -> None:
    try:
        from .eval.report_writer import write_report
        from .eval.runner import EvalRunner, load_dataset
    except ImportError as exc:
        print(f"Dependencias de eval ausentes: {exc}", file=sys.stderr)
        sys.exit(1)

    dataset_path = Path(args.dataset) if args.dataset else _default_eval_dataset_path()
    out_dir = Path(args.out) if args.out else _default_eval_out_dir()
    providers = _resolve_eval_providers(args.providers)
    judge_provider = args.judge.strip() if args.judge and args.judge.strip() else None

    _confirm_eval_cost_if_needed(
        providers=providers,
        judge_provider=judge_provider,
        no_cost_warning=args.no_cost_warning,
    )

    try:
        dataset = load_dataset(dataset_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao carregar dataset '{dataset_path}': {exc}", file=sys.stderr)
        sys.exit(1)

    progress_stream = sys.stderr if args.as_json else sys.stdout

    def _progress(msg: str) -> None:
        print(msg, file=progress_stream)

    runner = EvalRunner(
        dataset=dataset,
        providers=providers,
        out_dir=out_dir,
        ai_mode=args.ai_mode,
        judge_provider=judge_provider,
        on_progress=_progress,
    )

    try:
        results = runner.run()
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao executar eval: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        report_path, results_path = write_report(
            results=results,
            out_dir=out_dir,
            dataset_path=str(dataset_path),
            judge_provider=judge_provider,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao escrever relatorio: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"Report: {report_path}", file=sys.stderr)
        print(f"JSON: {results_path}", file=sys.stderr)
        return

    print("")
    print(f"OK: {out_dir}")
    print(f"Report: {report_path}")
    print(f"JSON: {results_path}")


def _cmd_serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn

        from .web.app import create_app
    except ImportError as exc:
        print(f"Dependencias web ausentes: {exc}", file=sys.stderr)
        print("Instale com: pip install 'transcreve-ai[web]'", file=sys.stderr)
        sys.exit(1)

    app = create_app(
        out_dir=Path(args.out),
        index_db=getattr(args, "index_db", None),
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from .storage.registry import resolve_storage_name

    storage_name = resolve_storage_name(args.storage or None)

    options = PipelineOptions(
        out_dir=Path(args.out),
        frame_interval=args.frame_interval,
        max_frames=args.max_frames,
        visual_limit=args.visual_limit,
        ai_mode=args.ai,
        vision_model=args.vision_model,
        transcribe_model=args.transcribe_model,
        language=args.language,
        tesseract_lang=args.tesseract_lang,
        cookies_browser=args.cookies_browser,
        cookies=args.cookies,
        video_format=args.format,
        provider_name=args.provider,
        force=args.force,
        storage_backend=storage_name,
        index_db=getattr(args, "index_db", None),
        templates=_normalize_templates(args.template),
    )

    try:
        result = VideoKnowledgePipeline(options).run(args.source)
    except DuplicateRunError as exc:
        run_id = exc.existing.get("id", "?")
        output_dir = exc.existing.get("output_dir", "?")
        print(f"Pulando: run '{run_id}' ja existe em '{output_dir}'.")
        print("Use --force para reprocessar mesmo assim.")
        sys.exit(0)

    indexed = False
    indexed_chunks = 0
    index_warnings: list[str] = []
    if not args.no_index:
        from .agent_workflow import index_analysis_result

        indexed, indexed_chunks, index_warnings = index_analysis_result(
            run_id=str(result.run_id),
            analysis_path=str(Path(result.workdir) / "analysis.json"),
            provider_name=args.provider,
            index_db=getattr(args, "index_db", None),
            index_force=args.force,
        )

    print("")
    print(f"OK: {result.workdir}")
    print("Markdown: %s" % (Path(result.workdir) / "knowledge.md"))
    print("JSON: %s" % (Path(result.workdir) / "analysis.json"))
    if indexed:
        if indexed_chunks:
            print(f"Index: ok ({indexed_chunks} chunks novos).")
        else:
            print("Index: ok (ja indexado).")
    for warning in index_warnings:
        print(f"Aviso: {warning}")
    template_paths = _template_output_paths(
        Path(result.workdir),
        _normalize_templates(args.template),
    )
    for name, path in template_paths.items():
        print(f"Template {name}: {path}")


def _cmd_runs_list(args: argparse.Namespace) -> None:
    db_path = resolve_index_path(getattr(args, "index_db", None))
    try:
        with RunIndex(db_path) as idx:
            runs = idx.list_runs(
                limit=args.limit,
                output_dir_filter=args.out,
            )
    except Exception as exc:
        print(f"Erro ao acessar indice: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(runs, ensure_ascii=False, indent=2))
        return

    if not runs:
        print("Nenhum run encontrado.")
        return

    # Tabela simples
    header = f"{'ID':<40} {'STATUS':<10} {'TITULO':<35} {'CRIADO EM':<25}"
    print(header)
    print("-" * len(header))
    for r in runs:
        run_id = r.get("id", "")[:40]
        status = r.get("status", "")[:10]
        title = (r.get("title") or r.get("source", ""))[:35]
        created = r.get("created_at", "")[:25]
        print(f"{run_id:<40} {status:<10} {title:<35} {created:<25}")


def _cmd_runs_show(args: argparse.Namespace) -> None:
    db_path = resolve_index_path(getattr(args, "index_db", None))
    try:
        with RunIndex(db_path) as idx:
            run = idx.get_run(args.run_id)
    except Exception as exc:
        print(f"Erro ao acessar indice: {exc}", file=sys.stderr)
        sys.exit(1)

    if run is None:
        print(f"Run '{args.run_id}' nao encontrado.", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(run, ensure_ascii=False, indent=2))
        return

    # Exibicao legivel
    for key, value in run.items():
        print(f"{key}: {value}")


def _cmd_runs_rm(args: argparse.Namespace) -> None:
    db_path = resolve_index_path(getattr(args, "index_db", None))

    # Carregar run antes de perguntar
    try:
        with RunIndex(db_path) as idx:
            run = idx.get_run(args.run_id)
    except Exception as exc:
        print(f"Erro ao acessar indice: {exc}", file=sys.stderr)
        sys.exit(1)

    if run is None:
        print(f"Run '{args.run_id}' nao encontrado.", file=sys.stderr)
        sys.exit(1)

    output_dir = run.get("output_dir", "")

    if not args.force:
        purge_msg = f" e deletar '{output_dir}'" if args.purge and output_dir else ""
        resposta = (
            input(f"Remover '{args.run_id}'{purge_msg} do indice? [s/N] ")
            .strip()
            .lower()
        )
        if resposta not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            return

    try:
        with RunIndex(db_path) as idx:
            removed = idx.delete_run(args.run_id)
    except Exception as exc:
        print(f"Erro ao remover do indice: {exc}", file=sys.stderr)
        sys.exit(1)

    if not removed:
        print(f"Run '{args.run_id}' nao encontrado.", file=sys.stderr)
        sys.exit(1)

    print(f"Run '{args.run_id}' removido do indice.")

    if args.purge and output_dir:
        dir_path = Path(output_dir)
        if not _is_within_cli_scope(output_dir, Path.cwd()):
            print(
                "Aviso: caminho fora do escopo atual; pulando delecao de arquivos.",
                file=sys.stderr,
            )
            return
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)
            print(f"Diretorio '{output_dir}' deletado.")
        else:
            print(f"Aviso: diretorio '{output_dir}' nao encontrado no disco.")


def _is_within_cli_scope(raw_output_dir: str, scope_root: Path) -> bool:
    """Evita remover pastas fora do escopo seguro do CLI."""
    try:
        root = scope_root.resolve()
        candidate = (root / Path(raw_output_dir)).resolve()
    except OSError:
        return False
    return candidate != root and candidate.is_relative_to(root)


def _cmd_share(args: argparse.Namespace) -> None:
    from .share import ShareRunError, share_run, shared_catalog

    try:
        if args.catalog:
            payload = shared_catalog(
                out_dir=args.out, limit=args.limit, query=args.query
            )
        else:
            payload = share_run(
                run_id=args.run_id,
                run_dir=args.run_dir,
                out_dir=args.out,
                index_db=getattr(args, "index_db", None),
            )
    except ShareRunError as exc:
        if args.as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {"code": "share_failed", "message": str(exc)},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        message = f"Falha inesperada ao compartilhar run: {exc}"
        if args.as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {"code": "share_failed", "message": message},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"Erro: {message}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.catalog:
        print(f"Catalog: {payload['catalog_md']}")
        for entry in payload["entries"]:
            print(f"- {entry.get('run_id', '')}: {entry.get('handoff_md', '')}")
        return

    print(f"OK: {payload['share_dir']}")
    print(f"Handoff: {payload['handoff_md']}")
    print(f"Manifest: {payload['manifest_json']}")
    print(f"Catalog: {payload['catalog_md']}")
    print(payload["handoff_message"])


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


def _cmd_index(args: argparse.Namespace) -> None:
    # Import lazy do modulo embeddings - nao exige numpy no import do pacote
    try:
        from .embeddings import EmbedNotSupportedError, index_run
        from .embeddings.store import DimMismatchError
    except ImportError as exc:
        print(f"Dependencias de indexacao ausentes: {exc}", file=sys.stderr)
        print("Instale com: pip install 'transcreve-ai[rag]'", file=sys.stderr)
        sys.exit(1)

    if not args.run_id and not args.index_all:
        print(
            "Erro: informe um run_id ou use --all para indexar todos os runs.",
            file=sys.stderr,
        )
        sys.exit(1)

    from .providers import CapabilityNotSupported, load_provider, resolve_provider_name

    provider_name = resolve_provider_name(args.provider or None)
    try:
        provider = load_provider(provider_name)
    except Exception as exc:
        print(f"Erro ao carregar provider '{provider_name}': {exc}", file=sys.stderr)
        sys.exit(1)

    if "embed" not in provider.capabilities():
        try:
            raise EmbedNotSupportedError(provider_name)
        except EmbedNotSupportedError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            sys.exit(1)

    db_path = resolve_index_path(getattr(args, "index_db", None))

    # Determina modelo de embed do provider
    model_name = _get_embed_model(provider, provider_name)

    if args.run_id:
        run_ids_to_index = [args.run_id]
    else:
        with RunIndex(db_path) as idx:
            runs = idx.list_runs(limit=9999)
        if not runs:
            print("Nenhum run encontrado. Execute 'transcreveai analyze' primeiro.")
            return
        run_ids_to_index = [r["id"] for r in runs]

    indexed = 0
    skipped = 0

    for run_id in run_ids_to_index:
        with RunIndex(db_path) as idx:
            run = idx.get_run(run_id)

        if run is None:
            print(f"Run '{run_id}' nao encontrado no indice.", file=sys.stderr)
            continue

        analysis_path = run.get("analysis_path") or ""
        if not analysis_path or not Path(analysis_path).exists():
            print(
                f"  Pulando '{run_id}': analysis.json nao encontrado em '{analysis_path}'."
            )
            skipped += 1
            continue

        # Verifica se ja indexado (sem --force)
        from .embeddings.store import EmbeddingStore

        with EmbeddingStore(db_path) as store:
            already = store.has_indexed(run_id)

        if already and not args.force:
            title = run.get("title") or run_id
            print(
                f"  Run '{title}' ({run_id}) ja indexado. Use --force para reindexar."
            )
            skipped += 1
            continue

        import json as _json

        analysis = _json.loads(Path(analysis_path).read_text(encoding="utf-8"))
        title = run.get("title") or run_id

        try:
            count = index_run(
                run_id=run_id,
                analysis=analysis,
                provider=provider,
                provider_name=provider_name,
                model_name=model_name,
                db_path=db_path,
                force=args.force,
            )
        except DimMismatchError as exc:
            print(f"  Erro: {exc}", file=sys.stderr)
            skipped += 1
            continue
        except CapabilityNotSupported as exc:
            print(f"  Erro: {exc}", file=sys.stderr)
            sys.exit(1)

        if count == 0 and not args.force:
            print(
                f"  Run '{title}' ({run_id}) ja indexado. Use --force para reindexar."
            )
            skipped += 1
        else:
            print(f"  Indexando '{title}'... {count} chunks gerados.")
            indexed += 1

    print(f"\nConcluido: {indexed} indexado(s), {skipped} pulado(s).")


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def _cmd_ask(args: argparse.Namespace) -> None:
    try:
        from .embeddings import EmbedNotSupportedError, search
        from .embeddings.rag import ask
    except ImportError as exc:
        print(f"Dependencias de busca ausentes: {exc}", file=sys.stderr)
        print("Instale com: pip install 'transcreve-ai[rag]'", file=sys.stderr)
        sys.exit(1)

    from .providers import load_provider, resolve_provider_name

    provider_name = resolve_provider_name(args.provider or None)
    try:
        provider = load_provider(provider_name)
    except Exception as exc:
        print(f"Erro ao carregar provider '{provider_name}': {exc}", file=sys.stderr)
        sys.exit(1)

    if "embed" not in provider.capabilities():
        try:
            raise EmbedNotSupportedError(provider_name)
        except EmbedNotSupportedError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            sys.exit(1)

    db_path = resolve_index_path(getattr(args, "index_db", None))
    run_ids = args.run_ids or None

    # Verifica se ha embeddings no banco
    from .embeddings.store import EmbeddingStore

    with EmbeddingStore(db_path) as store:
        conn = store._connect()
        row = conn.execute("SELECT 1 FROM embeddings LIMIT 1").fetchone()
        has_any = row is not None

    if not has_any:
        print("Nenhum conteudo indexado. Execute 'transcreveai index --all' primeiro.")
        sys.exit(0)

    if args.search_only:
        hits = search(
            query=args.question,
            provider=provider,
            db_path=db_path,
            top_k=args.top_k,
            run_ids=run_ids,
        )
        if not hits:
            print("Nenhum trecho encontrado.")
            return
        print(f'Top {len(hits)} trechos para: "{args.question}"\n')
        for i, hit in enumerate(hits, start=1):
            tipo = hit.chunk_type
            titulo = hit.title or hit.run_id
            score_pct = f"{hit.score * 100:.1f}%"
            print(f"[{i}] {titulo} ({tipo}) - score: {score_pct}")
            print(f"    {hit.excerpt[:120]}...")
            if hit.chapter_start is not None:
                mins = int(hit.chapter_start // 60)
                secs = int(hit.chapter_start % 60)
                print(f"    Capitulo em: {mins}:{secs:02d}")
            print()
        return

    result = ask(
        question=args.question,
        embed_provider=provider,
        synth_provider=provider,
        db_path=db_path,
        top_k=args.top_k,
        run_ids=run_ids,
    )

    print(f"Pergunta: {result.question}\n")
    print(f"Resposta:\n{result.answer}\n")

    if result.sources:
        print("Fontes:")
        for i, hit in enumerate(result.sources, start=1):
            titulo = hit.title or hit.run_id
            score_pct = f"{hit.score * 100:.1f}%"
            print(f"  [{i}] {titulo} ({hit.run_id}) - score: {score_pct}")


# ---------------------------------------------------------------------------
# Helper: detecta modelo de embed do provider
# ---------------------------------------------------------------------------


def _get_embed_model(provider: object, provider_name: str) -> str:
    """Retorna o nome do modelo de embedding do provider."""
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


# ---------------------------------------------------------------------------
# Helper: eval
# ---------------------------------------------------------------------------


def _default_eval_dataset_path() -> Path:
    return Path(__file__).parent / "eval" / "datasets" / "default.json"


def _default_eval_out_dir() -> Path:
    return Path("eval-report") / datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_eval_providers(raw_providers: str) -> list[str]:
    if raw_providers.strip():
        providers = [part.strip() for part in raw_providers.split(",") if part.strip()]
    else:
        from .providers import resolve_provider_name

        providers = [resolve_provider_name(None)]

    if not providers:
        print("Erro: informe ao menos um provider em --providers.", file=sys.stderr)
        sys.exit(1)
    return providers


def _is_paid_eval_provider(provider_name: str) -> bool:
    # Local e o unico provider explicitamente sem custo. Providers externos ou
    # desconhecidos podem chamar APIs remotas, entao pedem confirmacao.
    return provider_name.strip().lower() != "local"


def _paid_eval_targets(providers: list[str], judge_provider: str | None) -> list[str]:
    targets = [p for p in providers if _is_paid_eval_provider(p)]
    if judge_provider and _is_paid_eval_provider(judge_provider):
        targets.append(f"judge:{judge_provider}")
    return targets


def _confirm_eval_cost_if_needed(
    providers: list[str],
    judge_provider: str | None,
    no_cost_warning: bool,
) -> None:
    if no_cost_warning:
        return

    paid_targets = _paid_eval_targets(providers, judge_provider)
    if not paid_targets:
        return

    print(
        "Atencao: este eval pode fazer chamadas reais a APIs pagas.",
        file=sys.stderr,
    )
    print(f"Providers com possivel custo: {', '.join(paid_targets)}", file=sys.stderr)

    try:
        resposta = input("Continuar? [s/N] ").strip().lower()
    except EOFError:
        print("Cancelado: confirmacao de custo nao recebida.", file=sys.stderr)
        sys.exit(1)

    if resposta not in ("s", "sim", "y", "yes"):
        print("Cancelado.")
        sys.exit(0)
