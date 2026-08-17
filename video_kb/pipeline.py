from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .ai import (
    openai_available,
    select_visual_frames,
    transcript_near,
)
from .code_extraction import (
    extract_code_block,
    normalize_code_block,
    redact_code_secrets,
    strip_line_numbers,
)
from .content_intelligence import write_content_artifacts
from .downloader import DownloadedMedia
from .downloader import fetch_media_bundle as fetch_media
from .evidence import build_evidence_items
from .index import DuplicateRunError, RunIndex, resolve_index_path
from .media import (
    detect_slide_changes,
    extract_audio,
    extract_frames,
    probe_duration,
)
from .models import AnalysisResult, FrameObservation, KnowledgeSynthesis
from .ocr import choose_language, ocr_code_layout, ocr_image_detailed
from .providers import (
    CapabilityNotSupported,
    SynthesisContext,
    load_provider,
    resolve_provider_name,
)
from .report import write_markdown
from .skill_intelligence import write_skill_artifacts
from .storage import ArtifactPaths, load_storage, resolve_storage_name
from .transcript_quality import TranscriptQualityResult, sanitize_transcription
from .utils import (
    compact_text,
    ensure_dir,
    iso_now,
    now_id,
    sha256_file,
    sha256_url,
    slugify,
    write_json,
)


@dataclass
class PipelineOptions:
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
    run_id: str = ""
    # --- novas flags de persistencia ---
    force: bool = False
    storage_backend: str = "filesystem"
    index_db: str | None = None
    templates: tuple[str, ...] = ()
    # "auto" | "slides" | "interval" - ver _should_detect_slides().
    frame_strategy: str = "auto"
    # --- callback opcional de progresso (web UI) ---
    # Assinatura: on_progress(step: str, detail: str) -> None
    # Default None: comportamento identico ao anterior (so prints)
    on_progress: Callable[[str, str], None] | None = field(default=None, repr=False)


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _resolve_run_id(source: str, requested_run_id: str = "") -> str:
    if not requested_run_id:
        return f"{now_id()}-{slugify(source)}"

    run_id = requested_run_id.strip()
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id invalido: use apenas letras, numeros, hifen ou underscore, "
            "sem caminhos ou separadores."
        )
    return run_id


def _resolve_run_dir(out_dir: Path, run_id: str) -> Path:
    out_root = ensure_dir(out_dir).resolve()
    run_dir = ensure_dir(out_root / run_id).resolve()
    if not run_dir.is_relative_to(out_root):
        raise ValueError("run_id invalido: diretorio de execucao fora de out_dir.")
    return run_dir


class VideoKnowledgePipeline:
    def __init__(self, options: PipelineOptions):
        self.options = options

    def run(self, source: str) -> AnalysisResult:
        run_id = _resolve_run_id(source, self.options.run_id)
        run_dir = _resolve_run_dir(self.options.out_dir, run_id)

        def _emit(step: str, detail: str) -> None:
            print(detail)
            if self.options.on_progress:
                self.options.on_progress(step, detail)

        # ------------------------------------------------------------------
        # Indice e dedupe - erros sao gracis: nunca derrubam a analise
        # ------------------------------------------------------------------
        index_path = resolve_index_path(self.options.index_db)
        _index_ok = True
        try:
            _index_ctx = RunIndex(index_path)
            _index_ctx._connect()
        except Exception as _exc:  # noqa: BLE001
            _index_ok = False
            _index_ctx = None  # type: ignore[assignment]

        source_is_url = source.lower().startswith(("http://", "https://"))

        # Calcula hash para URLs antes do download (early-exit de dedupe)
        source_hash: str | None = None
        if source_is_url:
            try:
                source_hash = sha256_url(source)
            except Exception:  # noqa: BLE001
                source_hash = None

        # Checagem de dedupe para URLs (antes de baixar)
        if source_hash and _index_ok and not self.options.force:
            try:
                existing = _index_ctx.find_by_hash(source_hash)  # type: ignore[union-attr]
                if existing and existing.get("status") != "failed":
                    if _index_ctx is not None:
                        _index_ctx.close()
                    raise DuplicateRunError(existing)
            except DuplicateRunError:
                raise
            except Exception:  # noqa: BLE001
                pass  # falha no indice nao derruba o pipeline

        # Registro inicial no indice (status="partial") - gracil
        _run_registered = False
        if _index_ok and source_hash:
            try:
                _provider_name_for_index = resolve_provider_name(self.options.provider_name or None)
                _index_ctx.register(  # type: ignore[union-attr]
                    run_id=run_id,
                    source=source,
                    source_hash=source_hash,
                    provider=_provider_name_for_index,
                    ai_mode=self.options.ai_mode,
                    status="partial",
                    created_at=iso_now(),
                    storage_backend=self.options.storage_backend,
                )
                _run_registered = True
            except Exception:  # noqa: BLE001
                pass

        warnings = []

        _emit("download", "Baixando ou copiando video...")
        download_result = fetch_media(
            source,
            run_dir,
            cookies_browser=self.options.cookies_browser,
            cookies=self.options.cookies,
            video_format=self.options.video_format,
        )
        if isinstance(download_result, DownloadedMedia):
            media_path = download_result.primary_path
            media_paths = download_result.media_paths or [media_path]
            metadata = download_result.metadata
            warnings.extend(download_result.warnings)
        else:
            media_path, metadata = download_result
            media_paths = [media_path]
        metadata.media_kind = _infer_media_kind(media_paths, current=metadata.media_kind)

        # Para arquivos locais, calcula hash apos download
        if not source_is_url:
            try:
                source_hash = sha256_file(media_path)
            except Exception:  # noqa: BLE001
                source_hash = None

            # Checagem de dedupe para arquivos locais
            if source_hash and _index_ok and not self.options.force:
                try:
                    existing = _index_ctx.find_by_hash(source_hash)  # type: ignore[union-attr]
                    if existing and existing.get("status") != "failed":
                        if _index_ctx is not None:
                            _index_ctx.close()
                        raise DuplicateRunError(existing)
                except DuplicateRunError:
                    raise
                except Exception:  # noqa: BLE001
                    pass

            # Registro inicial para arquivos locais (apos calcular hash)
            if _index_ok and source_hash and not _run_registered:
                try:
                    _provider_name_for_index = resolve_provider_name(
                        self.options.provider_name or None
                    )
                    _index_ctx.register(  # type: ignore[union-attr]
                        run_id=run_id,
                        source=source,
                        source_hash=source_hash,
                        provider=_provider_name_for_index,
                        ai_mode=self.options.ai_mode,
                        status="partial",
                        created_at=iso_now(),
                        storage_backend=self.options.storage_backend,
                    )
                    _run_registered = True
                except Exception:  # noqa: BLE001
                    pass

        try:
            metadata.duration = metadata.duration or probe_duration(media_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Nao foi possivel ler duracao com ffprobe: {exc}")

        _emit("audio", "Extraindo audio...")
        audio_path = run_dir / "audio.mp3"
        audio_source = _first_audio_capable_media(media_paths)
        if audio_source is None:
            if metadata.media_kind == "carousel":
                warnings.append("Carrossel de imagens; transcricao de audio nao se aplica.")
            else:
                warnings.append("Fonte de imagem estatica; sem audio para transcrever.")
            audio_path = None  # type: ignore[assignment]
        else:
            try:
                extract_audio(audio_source, audio_path)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Nao foi possivel extrair audio: {exc}")
                audio_path = None  # type: ignore[assignment]

        _emit("frames", "Extraindo frames...")
        frames_dir = ensure_dir(run_dir / "frames")
        frame_paths, frame_notes = _extract_collection_frames(
            media_paths,
            frames_dir,
            primary_duration=metadata.duration,
            interval=self.options.frame_interval,
            max_frames=self.options.max_frames,
            frame_strategy=self.options.frame_strategy,
        )
        for note in frame_notes:
            _emit("frames", note)

        _emit("ocr", f"Rodando OCR em {len(frame_paths)} frames...")
        ocr_lang, ocr_warning = choose_language(self.options.tesseract_lang)
        if ocr_warning:
            warnings.append(ocr_warning)
        frames = []
        for frame_path in frame_paths:
            timestamp = _timestamp_from_frame_name(frame_path.name)
            ocr_text, ocr_raw = ocr_image_detailed(frame_path, ocr_lang)
            code = extract_code_block(ocr_raw)
            if code:
                # Segunda leitura, so nos frames que tem codigo: recupera a
                # indentacao pelas coordenadas, que o modo texto nao devolve.
                layout = ocr_code_layout(frame_path, ocr_lang)
                if layout:
                    code = normalize_code_block(layout)
                code = normalize_code_block(strip_line_numbers(code))
            code = redact_code_secrets(code)
            frames.append(
                FrameObservation(
                    timestamp=timestamp,
                    image_path=str(frame_path.relative_to(run_dir)),
                    ocr_text=ocr_text,
                    code=code,
                )
            )
        code_frames = sum(1 for frame in frames if frame.code)
        if code_frames:
            _emit("ocr", f"Codigo detectado em {code_frames} frames.")

        result = AnalysisResult(
            run_id=run_id,
            created_at=iso_now(),
            source=source,
            workdir=str(run_dir),
            media_path=str(media_path.relative_to(run_dir)),
            audio_path=str(audio_path.relative_to(run_dir)) if audio_path else "",
            metadata=metadata,
            media_paths=[str(path.relative_to(run_dir)) for path in media_paths],
            frames=frames,
            warnings=warnings,
        )

        provider_name = resolve_provider_name(self.options.provider_name or None)
        use_ai = self._should_use_ai(provider_name)
        transcript_quality = TranscriptQualityResult(text="", segments=[], status="not_run")

        if use_ai:
            _emit("ai", f"Transcrevendo e descrevendo com IA ({provider_name})...")
            try:
                provider = load_provider(
                    provider_name,
                    vision_model=self.options.vision_model,
                    transcribe_model=self.options.transcribe_model,
                    language=self.options.language,
                )

                # --- transcricao ---
                if audio_path and "transcribe" in provider.capabilities():
                    transcribe_result = provider.transcribe(
                        audio_path,
                        run_dir / "audio_chunks",
                        language=self.options.language,
                    )
                    transcript_quality = sanitize_transcription(
                        transcribe_result.text,
                        transcribe_result.segments,
                    )
                    result.transcript_text = transcript_quality.text
                    result.transcript_segments = transcript_quality.segments
                    _append_transcript_quality_warning(result, transcript_quality, has_audio=True)
                elif audio_path:
                    transcript_quality = TranscriptQualityResult(
                        text="",
                        segments=[],
                        status="unsupported",
                        reason=f"provider:{provider_name}",
                    )
                    result.warnings.append(
                        f"Transcricao nao suportada pelo provider '{provider_name}'."
                    )
                elif result.metadata.media_kind == "carousel":
                    transcript_quality = TranscriptQualityResult(
                        text="",
                        segments=[],
                        status="not_applicable",
                        reason="carousel_without_audio",
                    )
                    result.warnings.append("Carrossel sem audio; usando OCR/visao por slide.")
                else:
                    transcript_quality = TranscriptQualityResult(
                        text="",
                        segments=[],
                        status="not_applicable",
                        reason="audio_unavailable",
                    )
                    result.warnings.append(
                        "Audio nao disponivel; seguindo com OCR/visao quando suportado."
                    )

                # --- visao por frame ---
                visual_indexes = select_visual_frames(result.frames, self.options.visual_limit)
                for position, index in enumerate(visual_indexes, start=1):
                    frame = result.frames[index]
                    _emit("ai_frame", f"Frame {position}/{len(visual_indexes)}")
                    frame_path = run_dir / frame.image_path
                    context = transcript_near(result.transcript_segments, frame.timestamp)
                    try:
                        frame.visual_note = provider.describe_frame(
                            frame_path,
                            result.metadata,
                            frame.timestamp,
                            frame.ocr_text,
                            context,
                        )
                    except CapabilityNotSupported as exc:
                        result.warnings.append(
                            f"Visao nao suportada pelo provider '{provider_name}': {exc}"
                        )
                        break  # nao tentar os demais frames

                # --- sintese ---
                result.evidence_profile = _build_evidence_profile(result, transcript_quality)
                ctx = SynthesisContext(
                    metadata=result.metadata,
                    transcript_text=result.transcript_text,
                    frames=result.frames,
                    media_kind=result.metadata.media_kind,
                    evidence_profile=result.evidence_profile,
                )
                try:
                    result.synthesis = provider.synthesize(ctx)
                except CapabilityNotSupported:
                    if self.options.ai_mode == "full":
                        raise
                    result.warnings.append(
                        f"Sintese nao suportada pelo provider '{provider_name}';"
                        " usando sintese local."
                    )
                    result.synthesis = _local_synthesis(result)

            except Exception as exc:  # noqa: BLE001
                if self.options.ai_mode == "full":
                    raise
                result.warnings.append(
                    f"Camada de IA falhou; artefatos locais foram mantidos: {exc}"
                )
                result.synthesis = _local_synthesis(result)
        else:
            if self.options.ai_mode != "off":
                result.warnings.append(
                    f"Provider '{provider_name}' indisponivel;"
                    " gerando dossie local sem transcricao/visao por IA"
                )
            print("5/6 Gerando sintese local...")  # sem step SSE para este branch
            result.synthesis = _local_synthesis(result)

        if not result.evidence_profile:
            result.evidence_profile = _build_evidence_profile(result, transcript_quality)
        result.evidence_items = build_evidence_items(result)

        _emit("persist", "Salvando analysis.json e knowledge.md...")
        write_json(run_dir / "analysis.json", result.to_dict())
        write_markdown(result, run_dir / "knowledge.md")
        if "content" in self.options.templates:
            write_content_artifacts(result, run_dir)
        if "skill" in self.options.templates:
            write_skill_artifacts(result, run_dir)

        # ------------------------------------------------------------------
        # Storage backend - gracil: falha adiciona warning mas nao aborta
        # ------------------------------------------------------------------
        artifacts = ArtifactPaths(
            analysis_json=run_dir / "analysis.json",
            markdown=run_dir / "knowledge.md",
            frames_dir=frames_dir,
            run_dir=run_dir,
        )
        storage_ref = None
        try:
            # Passa o backend ja resolvido explicitamente (default "filesystem"),
            # em vez de None, para nao deixar VIDEO_KB_STORAGE sobrescrever a
            # escolha que o pipeline ja fez.
            storage_name = resolve_storage_name(self.options.storage_backend or "filesystem")
            backend = load_storage(storage_name)
            storage_ref = backend.save(result, artifacts)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"Storage backend falhou (artefatos locais mantidos): {exc}")

        # ------------------------------------------------------------------
        # Atualiza registro no indice com status final e paths
        # ------------------------------------------------------------------
        if _index_ok and _run_registered and source_hash:
            try:
                finished_at = datetime.now(timezone.utc).isoformat()
                _index_ctx.update_run(  # type: ignore[union-attr]
                    run_id,
                    status="completed",
                    finished_at=finished_at,
                    title=result.metadata.title or "",
                    duration_seconds=result.metadata.duration or 0.0,
                    warnings_count=len(result.warnings),
                    output_dir=(storage_ref.output_dir if storage_ref else str(run_dir)),
                    analysis_path=(
                        storage_ref.analysis_path if storage_ref else str(run_dir / "analysis.json")
                    ),
                    markdown_path=(
                        storage_ref.markdown_path if storage_ref else str(run_dir / "knowledge.md")
                    ),
                    storage_backend=(storage_ref.backend if storage_ref else "filesystem"),
                )
            except Exception:  # noqa: BLE001
                pass

        if _index_ctx is not None:
            try:
                _index_ctx.close()
            except Exception:  # noqa: BLE001
                pass

        return result

    def _should_use_ai(self, provider_name: str) -> bool:
        if self.options.ai_mode == "off":
            return False
        if self.options.ai_mode == "full":
            return True
        # modo "auto": verifica disponibilidade conforme o provider
        return _provider_available(provider_name)


def _provider_available(provider_name: str) -> bool:
    """Verifica se o provider esta disponivel (chave de API presente ou sem requisito)."""
    if provider_name == "openai":
        return openai_available()
    if provider_name == "local":
        return True  # local nao precisa de API key
    if provider_name == "gemini":
        import os

        return bool(os.environ.get("GOOGLE_API_KEY"))
    if provider_name == "anthropic":
        import os

        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    # provider externo desconhecido - tenta carregar e deixa falhar depois se necessario
    return True


def _timestamp_from_frame_name(name: str) -> float:
    # frame_0001_00010s00.jpg -> 10.00
    marker = name.rsplit("_", 1)[-1].split(".", 1)[0]
    try:
        return float(marker.replace("s", "."))
    except ValueError:
        return 0.0


def _first_audio_capable_media(media_paths: list[Path]) -> Path | None:
    for media_path in media_paths:
        if media_path.suffix.lower() not in _IMAGE_SUFFIXES:
            return media_path
    return None


def _infer_media_kind(media_paths: list[Path], current: str = "") -> str:
    if len(media_paths) > 1:
        return "carousel"
    if current:
        return current
    if media_paths and media_paths[0].suffix.lower() in _IMAGE_SUFFIXES:
        return "image"
    return "video"


def _should_detect_slides(strategy: str, duration: float, interval: float, max_frames: int) -> bool:
    """Decide se vale rodar deteccao de troca de slide neste video.

    "auto" so liga a deteccao quando a amostragem por intervalo nao cobriria o
    video inteiro (duracao/intervalo acima do teto de frames): e exatamente o
    caso em que hoje se perde slide. Video curto continua no caminho antigo,
    sem pagar a decodificacao extra.
    """
    if strategy == "interval":
        return False
    if strategy == "slides":
        return True
    if duration <= 0 or interval <= 0 or max_frames <= 0:
        return False
    return (duration / interval) > max_frames


def _extract_collection_frames(
    media_paths: list[Path],
    frames_dir: Path,
    primary_duration: float,
    interval: float,
    max_frames: int,
    frame_strategy: str = "auto",
) -> tuple[list[Path], list[str]]:
    frame_paths: list[Path] = []
    notes: list[str] = []
    timestamp_offset = 0.0
    multiple_items = len(media_paths) > 1

    # Com "slides" o usuario esta dizendo que o conteudo e tela/apresentacao,
    # onde o texto e fino e o JPEG arruina o OCR de codigo. Nos outros modos o
    # JPEG continua, para nao inflar o disco de video natural.
    image_format = "png" if frame_strategy == "slides" else "jpg"

    for media_path in media_paths:
        if max_frames > 0 and len(frame_paths) >= max_frames:
            break

        remaining = max_frames - len(frame_paths) if max_frames > 0 else 0
        is_image = media_path.suffix.lower() in _IMAGE_SUFFIXES
        item_max_frames = 1 if is_image else remaining
        duration = 0.0
        if not is_image:
            try:
                duration = probe_duration(media_path)
            except Exception:  # noqa: BLE001
                duration = primary_duration if not multiple_items else 0.0

        effective_duration = duration or (primary_duration if not multiple_items else 0.0)

        timestamps: list[float] | None = None
        if not is_image and _should_detect_slides(
            frame_strategy, effective_duration, interval, item_max_frames
        ):
            detected = detect_slide_changes(media_path)
            if detected:
                timestamps = detected
                notes.append(
                    f"Frames por troca de slide: {len(detected)} mudancas detectadas "
                    f"em {media_path.name}."
                )
            else:
                notes.append(
                    "Nenhuma troca de slide detectada em "
                    f"{media_path.name}; frames amostrados por intervalo."
                )

        new_frames = extract_frames(
            media_path,
            frames_dir,
            duration=effective_duration,
            interval=interval,
            max_frames=item_max_frames,
            start_index=len(frame_paths) + 1,
            timestamp_offset=timestamp_offset,
            timestamps=timestamps,
            image_format=image_format,
        )
        frame_paths.extend(new_frames)
        timestamp_offset += max(duration, 1.0)

    return frame_paths, notes


def _append_transcript_quality_warning(
    result: AnalysisResult,
    transcript_quality: TranscriptQualityResult,
    *,
    has_audio: bool,
) -> None:
    if transcript_quality.warning:
        result.warnings.append(transcript_quality.warning)
    elif has_audio and transcript_quality.status == "empty":
        result.warnings.append(
            "Nenhuma fala util foi detectada na transcricao; a analise deve priorizar OCR/visao."
        )


def _build_evidence_profile(
    result: AnalysisResult,
    transcript_quality: TranscriptQualityResult,
) -> dict[str, object]:
    ocr_frames = sum(1 for frame in result.frames if (frame.ocr_text or "").strip())
    visual_note_frames = sum(1 for frame in result.frames if (frame.visual_note or "").strip())
    has_speech = bool((result.transcript_text or "").strip())
    has_visual = bool(result.frames)

    if has_speech and (ocr_frames or visual_note_frames):
        primary_signal = "speech+visual"
    elif has_speech:
        primary_signal = "speech"
    elif visual_note_frames:
        primary_signal = "vision"
    elif ocr_frames:
        primary_signal = "ocr"
    elif has_visual:
        primary_signal = "frames"
    else:
        primary_signal = "metadata"

    speech: dict[str, object] = {
        "status": transcript_quality.status,
        "chars": len(result.transcript_text or ""),
        "segments": len(result.transcript_segments),
    }
    if transcript_quality.reason:
        speech["reason"] = transcript_quality.reason
    if transcript_quality.original_text:
        speech["discarded_preview"] = compact_text(transcript_quality.original_text, 180)

    return {
        "primary_signal": primary_signal,
        "speech": speech,
        "visual": {
            "frames": len(result.frames),
            "ocr_frames": ocr_frames,
            "visual_note_frames": visual_note_frames,
        },
    }


def _local_synthesis(result: AnalysisResult) -> KnowledgeSynthesis:
    ocr_hits = [frame.ocr_text for frame in result.frames if frame.ocr_text]
    summary_parts = []
    is_carousel = result.metadata.media_kind == "carousel"
    if result.metadata.title:
        label = "Carrossel" if is_carousel else "Video"
        summary_parts.append(f"{label}: {result.metadata.title}.")
    if result.metadata.description:
        summary_parts.append(result.metadata.description[:500])
    if ocr_hits:
        unit = "slides" if is_carousel else "frames"
        summary_parts.append(f"OCR encontrou textos em {len(ocr_hits)} {unit}.")
    if not summary_parts:
        summary_parts.append(
            "Analise local concluida; ative OPENAI_API_KEY"
            " para transcricao e notas visuais completas."
        )

    return KnowledgeSynthesis(
        summary=" ".join(summary_parts),
        chapters=[],
        entities=[],
        tools_or_products=[],
        claims=[],
        action_items=[],
        questions=[],
        raw={"mode": "local"},
    )
