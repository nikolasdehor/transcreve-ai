import json
import math
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .utils import CommandError, ensure_dir, run_command

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# O filtro metadata escreve dois pares de linhas por frame: o instante e, logo
# abaixo, o score de mudanca de cena calculado pelo select.
_SCENE_PTS_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_SCENE_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9]+(?:\.[0-9]+)?)")

# A deteccao decodifica o video inteiro, entao roda numa escala reduzida e a
# 2 quadros por segundo: "a tela mudou" nao precisa de resolucao nem de taxa
# cheia, e num video de uma hora isso corta o volume de log em ~15x.
_SCENE_ANALYSIS_WIDTH = 320
_SCENE_ANALYSIS_FPS = 2

# Piso absoluto do score que separa troca de slide de ruido de compressao.
# Medido: slide branco trocando marca ~0.024-0.035, frames identicos ~0.00003.
# O 0.15 que se ve por ai e calibrado para video natural e nao detecta NENHUM
# slide de palestra com fundo claro.
_SCENE_ABS_FLOOR = 0.008

# Em video natural (palestrante em cena, camera na mao) o ruido de base ja e
# alto, entao o corte sobe junto: multiplo da mediana do proprio video.
_SCENE_MEDIAN_MULTIPLIER = 8.0

# Dois keyframes colados quase sempre sao a mesma transicao (fade, animacao de
# bullet aparecendo); manter os dois so gasta chamada de visao a toa.
_MIN_SLIDE_GAP = 2.0

# A deteccao decodifica o video inteiro, entao um ffmpeg travado seguraria
# a CLI ou o servidor MCP para sempre. Com teto, o travamento vira apenas
# fallback para amostragem por intervalo.
_SCENE_DETECTION_TIMEOUT = 900.0


def probe_duration(media_path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media_path),
    ]
    proc = run_command(command)
    payload = json.loads(proc.stdout or "{}")
    duration = payload.get("format", {}).get("duration")
    return float(duration or 0)


def extract_audio(media_path: Path, audio_path: Path) -> Path:
    ensure_dir(audio_path.parent)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(audio_path),
    ]
    run_command(command)
    return audio_path


def _sample_timestamps(duration: float, interval: float, max_frames: int) -> list[float]:
    duration = max(0.0, duration)
    interval = _effective_frame_interval(duration, interval)
    if duration <= 0:
        return [0.0]

    timestamps = []
    current = 0.0
    while current <= duration:
        timestamps.append(round(current, 2))
        current += interval

    return _cap_timestamps(timestamps, max_frames)


def _cap_timestamps(timestamps: list[float], max_frames: int) -> list[float]:
    """Reduz a lista para no maximo max_frames, espalhando pela duracao."""
    if max_frames <= 0 or len(timestamps) <= max_frames:
        return timestamps
    if max_frames == 1:
        return timestamps[:1]

    step = (len(timestamps) - 1) / float(max_frames - 1)
    selected: list[float] = []
    seen = set()
    for index in range(max_frames):
        pos = int(round(index * step))
        value = timestamps[min(pos, len(timestamps) - 1)]
        if value not in seen:
            selected.append(value)
            seen.add(value)
    return selected


def _parse_scene_scores(stderr: str) -> list[tuple[float, float]]:
    """Pares (instante, score) na ordem em que o ffmpeg os imprimiu."""
    pairs: list[tuple[float, float]] = []
    pending: float | None = None
    for line in (stderr or "").splitlines():
        # Os dois padroes so casam digitos, entao float() aqui nao levanta.
        time_match = _SCENE_PTS_RE.search(line)
        if time_match:
            pending = float(time_match.group(1))
            continue
        score_match = _SCENE_SCORE_RE.search(line)
        if score_match and pending is not None:
            pairs.append((pending, float(score_match.group(1))))
            pending = None
    return pairs


def _scene_threshold(scores: list[float]) -> float:
    """Corte de score adaptado ao proprio video.

    Um numero fixo nao serve para os dois casos: em slide de fundo claro a troca
    marca ~0.03, enquanto em video natural o simples movimento do palestrante ja
    passa disso. O corte entao e o maior entre um piso absoluto e um multiplo da
    mediana do video, que e o nivel de ruido daquela filmagem.
    """
    if not scores:
        return _SCENE_ABS_FLOOR
    ordered = sorted(scores)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return max(_SCENE_ABS_FLOOR, median * _SCENE_MEDIAN_MULTIPLIER)


def detect_slide_changes(
    media_path: Path,
    threshold: float | None = None,
    min_gap: float = _MIN_SLIDE_GAP,
) -> list[float]:
    """Instantes em que a tela mudou de verdade (troca de slide, corte de cena).

    Amostrar de N em N segundos e cego para o conteudo: numa palestra de uma
    hora com teto de 80 frames sai um frame a cada 45s, o que captura o mesmo
    slide varias vezes e perde slides inteiros. Aqui quem decide onde olhar e a
    propria imagem.

    `threshold` fixa o corte de score manualmente; com None (padrao) ele e
    derivado da distribuicao do proprio video, que e o que faz a deteccao
    funcionar tanto em slide estatico quanto em filmagem com movimento.

    Retorna lista vazia quando o ffmpeg falha ou o video nao tem troca de cena
    detectavel (ex.: uma pessoa falando para a camera). Quem chama decide o
    fallback; o vazio e um resultado legitimo, nao um erro engolido.
    """
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(media_path),
        "-an",
        "-vf",
        (
            f"scale={_SCENE_ANALYSIS_WIDTH}:-2,fps={_SCENE_ANALYSIS_FPS},"
            "select='gt(scene,-1)',metadata=print:key=lavfi.scene_score"
        ),
        "-f",
        "null",
        "-",
    ]
    try:
        proc = run_command(command, timeout=_SCENE_DETECTION_TIMEOUT)
    except (CommandError, subprocess.TimeoutExpired):
        return []

    pairs = _parse_scene_scores(proc.stderr or "")
    if not pairs:
        return []

    cut = threshold if threshold is not None else _scene_threshold([score for _, score in pairs])
    detected = sorted({round(time, 2) for time, score in pairs if score >= cut})
    if not detected:
        return []

    # O primeiro slide nunca e uma "mudanca de cena", entao entra na mao.
    timestamps = [0.0]
    for value in detected:
        if value - timestamps[-1] >= min_gap:
            timestamps.append(value)
    return timestamps


def _effective_frame_interval(duration: float, requested_interval: float) -> float:
    requested_interval = max(1.0, requested_interval)
    if requested_interval != 5.0:
        return requested_interval
    if duration <= 0:
        return requested_interval
    if duration <= 30:
        return min(requested_interval, 2.0)
    if duration <= 90:
        return min(requested_interval, 3.0)
    return requested_interval


def extract_frames(
    media_path: Path,
    frames_dir: Path,
    duration: float,
    interval: float = 5.0,
    max_frames: int = 80,
    width: int = 1280,
    start_index: int = 1,
    timestamp_offset: float = 0.0,
    timestamps: Sequence[float] | None = None,
    image_format: str = "jpg",
) -> list[Path]:
    """Extrai frames do video.

    Com `timestamps` explicitos (ex.: vindos de `detect_slide_changes`) usa
    exatamente esses instantes; sem eles, amostra de `interval` em `interval`.

    `image_format="png"` grava sem perda. Medido em screencast de codigo: o
    JPEG (mesmo em q:v 1) transforma `def fetch_users(client):` em
    `il cet fotea users (cliem) e` no OCR, enquanto o PNG le certo. O custo e
    disco: em conteudo de tela o PNG fica ~1,5x maior que o JPEG, mas em video
    natural chega a 4x, por isso o JPEG segue como padrao.
    """
    ensure_dir(frames_dir)
    if media_path.suffix.lower() in _IMAGE_SUFFIXES:
        return _extract_static_image_frame(
            media_path,
            frames_dir,
            width=width,
            index=start_index,
            timestamp=timestamp_offset,
            image_format=image_format,
        )

    frame_paths = []
    if timestamps is None:
        sampled = _sample_timestamps(duration, interval, max_frames)
    else:
        sampled = _cap_timestamps(sorted(timestamps), max_frames)
    max_index = start_index + max(0, len(sampled) - 1)
    digits = max(4, int(math.log10(max(1, max_index))) + 1)

    suffix = "png" if str(image_format).lower() == "png" else "jpg"
    for index, timestamp in enumerate(sampled, start=start_index):
        output = frames_dir / (
            f"frame_{index:0{digits}d}_{_safe_ts(timestamp + timestamp_offset)}.{suffix}"
        )
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
        ]
        if suffix == "jpg":
            command += ["-q:v", "3"]
        command.append(str(output))
        try:
            run_command(command)
        except CommandError:
            continue
        if output.exists() and output.stat().st_size > 0:
            frame_paths.append(output)
    return frame_paths


def _extract_static_image_frame(
    media_path: Path,
    frames_dir: Path,
    width: int,
    index: int,
    timestamp: float,
    image_format: str = "jpg",
) -> list[Path]:
    digits = max(4, int(math.log10(max(1, index))) + 1)
    suffix = "png" if str(image_format).lower() == "png" else "jpg"
    output = frames_dir / f"frame_{index:0{digits}d}_{_safe_ts(timestamp)}.{suffix}"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "3",
        "-update",
        "1",
        str(output),
    ]
    try:
        run_command(command)
    except CommandError:
        return []
    if output.exists() and output.stat().st_size > 0:
        return [output]
    return []


def split_audio(audio_path: Path, chunks_dir: Path, segment_seconds: int = 600) -> list[Path]:
    ensure_dir(chunks_dir)
    pattern = chunks_dir / "chunk_%03d.mp3"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(pattern),
    ]
    run_command(command)
    return sorted(chunks_dir.glob("chunk_*.mp3"))


def _safe_ts(timestamp: float) -> str:
    return (f"{timestamp:08.2f}").replace(".", "s")
