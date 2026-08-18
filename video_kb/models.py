from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SourceMetadata:
    source: str
    title: str = ""
    webpage_url: str = ""
    extractor: str = ""
    uploader: str = ""
    channel: str = ""
    duration: float = 0.0
    upload_date: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    media_kind: str = ""


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class FrameObservation:
    timestamp: float
    image_path: str
    ocr_text: str = ""
    visual_note: str = ""
    # Codigo lido na tela, com indentacao preservada (video_kb/code_extraction.py).
    # Vazio quando o frame nao mostra codigo.
    code: str = ""


@dataclass
class EvidenceSupport:
    signal: str
    confidence: str
    timestamp: float | None = None
    frame_path: str = ""
    excerpt: str = ""


@dataclass
class EvidenceItem:
    kind: str
    value: str
    confidence: str
    supports: list[EvidenceSupport] = field(default_factory=list)


@dataclass
class KnowledgeSynthesis:
    summary: str = ""
    chapters: list[dict[str, Any]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    tools_or_products: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    run_id: str
    created_at: str
    source: str
    workdir: str
    media_path: str
    audio_path: str
    metadata: SourceMetadata
    media_paths: list[str] = field(default_factory=list)
    transcript_text: str = ""
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    frames: list[FrameObservation] = field(default_factory=list)
    synthesis: KnowledgeSynthesis = field(default_factory=KnowledgeSynthesis)
    warnings: list[str] = field(default_factory=list)
    evidence_profile: dict[str, Any] = field(default_factory=dict)
    evidence_items: list[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
