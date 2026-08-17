import hashlib
import json
import os
import re
import subprocess
import urllib.parse
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CommandError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__("Command failed ({}): {}".format(returncode, " ".join(command)))


def run_command(
    command: list[str],
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise CommandError(command, proc.returncode, proc.stderr.strip())
    return proc


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str, fallback: str = "video") -> str:
    normalized = value.lower().strip()
    normalized = re.sub(r"https?://", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    return (normalized or fallback)[:80]


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_timestamp(seconds: float) -> str:
    seconds = max(0, float(seconds or 0))
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def compact_text(text: str, limit: int = 12000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    half = max(1000, limit // 2)
    return text[:half].rstrip() + "\n\n...[truncated]...\n\n" + text[-half:].lstrip()


def unique_strings(items: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = re.sub(r"\s+", " ", "" if item is None else str(item)).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sha256_url(url: str) -> str:
    """
    Retorna o sha256 de uma URL remota normalizada.

    Apenas URLs com scheme http/https sao normalizadas para deduplicacao.
    Para entradas sem scheme, retorna hash do caminho bruto (case-sensitive).

    Extrai o ID canonico quando possivel (YouTube, Vimeo) e descarta
    parametros de rastreamento para garantir que URLs equivalentes
    produzam o mesmo hash.
    """
    _TRACKING_PARAMS = frozenset(
        {
            "t",
            "si",
            "pp",
            "feature",
            "ref",
            "index",
            "list",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
        }
    )

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"scheme nao suportado para hash de URL: {parsed.scheme}")

    if not parsed.scheme:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.rstrip("/")
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)

    vid = _extract_youtube_id(host, path, qs, url)
    if vid:
        canonical = f"youtube:{vid}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    vid = _extract_vimeo_id(host, path)
    if vid:
        canonical = f"vimeo:{vid}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # Fallback generico: host + path sem parametros de rastreamento
    clean_qs = {k: v for k, v in qs.items() if k not in _TRACKING_PARAMS}
    clean_query = urllib.parse.urlencode(clean_qs, doseq=True)
    canonical = f"{host}{path.lower()}"
    if clean_query:
        canonical = f"{canonical}?{clean_query}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_youtube_id(
    host: str,
    path: str,
    qs: dict[str, list[str]],
    raw_url: str,
) -> str:
    youtube_hosts = {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtube-kids.com",
        "youtu.be",
    }
    candidate = ""
    if _valid_youtube_id(raw_url):
        candidate = raw_url
    elif host in youtube_hosts:
        parts = [part for part in path.strip("/").split("/") if part]
        if host == "youtu.be":
            candidate = parts[0] if parts else ""
        else:
            candidate = (qs.get("v") or [""])[0]
            if (
                not candidate
                and parts
                and parts[0]
                in {
                    "shorts",
                    "embed",
                    "v",
                    "e",
                    "live",
                }
            ):
                candidate = parts[1] if len(parts) > 1 else ""
    return candidate if _valid_youtube_id(candidate) else ""


def _valid_youtube_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", value or ""))


def _extract_vimeo_id(host: str, path: str) -> str:
    if host not in {"vimeo.com", "player.vimeo.com"}:
        return ""
    for part in path.strip("/").split("/"):
        if part.isdigit():
            return part
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value
