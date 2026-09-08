from __future__ import annotations

import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).parent.parent
SITE = ROOT / "docs/app-directory-site"
BASE = "https://transcreve-ai-site.vercel.app/"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        """Inicialize os metadados extraídos de uma página pública."""
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()
        self.canonical = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Registre IDs, links e o canonical presentes em uma tag inicial."""
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if values.get("href"):
            self.hrefs.append(str(values["href"]))
        if tag == "link" and "canonical" in str(values.get("rel", "")).split():
            self.canonical = str(values.get("href", ""))


def parse_page(path: Path) -> PageParser:
    """Leia uma página HTML e devolva seus links e metadados estruturais."""
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def css_block(source: str, marker: str) -> str:
    """Extraia um bloco CSS, respeitando chaves aninhadas."""
    marker_start = source.index(marker)
    block_start = source.index("{", marker_start) + 1
    depth = 1
    for index, character in enumerate(source[block_start:], start=block_start):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[block_start:index]
    raise AssertionError(f"bloco CSS não fechado: {marker}")


def css_declarations(source: str, selector: str) -> dict[str, str]:
    """Converta as declarações simples de um seletor em um dicionário."""
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", source)
    assert match is not None, f"seletor CSS ausente: {selector}"
    declarations: dict[str, str] = {}
    for declaration in match.group(1).split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        declarations[name.strip()] = value.strip()
    return declarations


def test_claims_refletem_defaults_e_prova_publica() -> None:
    """Mantenha a copy alinhada aos defaults e às provas do produto."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    privacy = (SITE / "privacidade.html").read_text(encoding="utf-8")
    markdown = (SITE / "index.md").read_text(encoding="utf-8")
    llms = (SITE / "llms.txt").read_text(encoding="utf-8")

    assert html.count("<details") >= 5
    assert 'id="caso-tecnico"' in html and "sem cliente ou ganho atribuído" in html
    for text in (html, privacy, markdown):
        assert "outputs/" in text and "--no-index" in text and "no_index" in text
    assert "transcreveai share" in html and "share_run" in html and html.count("manifest.json") == 1
    assert "manifesto para auditoria e compartilhamento" not in html
    assert "caso técnico é do próprio produto" in llms


def test_links_canonicals_sitemap_e_mimes() -> None:
    """Valide rotas, canonicals, sitemap e tipos MIME portáveis."""
    pages = {path.name: parse_page(path) for path in SITE.glob("*.html")}
    for name, page in pages.items():
        route = "" if name == "index.html" else name
        assert page.canonical == BASE + route
        for href in page.hrefs:
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                continue
            target = (SITE / (parsed.path.lstrip("/") or "index.html")).resolve()
            assert target.is_relative_to(SITE.resolve()), f"link fora do site em {name}: {href}"
            assert target.is_file(), f"link quebrado em {name}: {href}"
            if parsed.fragment:
                assert parsed.fragment in pages[target.name].ids

    xml = ElementTree.parse(SITE / "sitemap.xml")
    locations = {
        node.text
        for node in xml.findall(
            "{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
        )
    }
    assert locations == {page.canonical for page in pages.values()}
    assert f"Sitemap: {BASE}sitemap.xml" in (SITE / "robots.txt").read_text()
    expected_mimes = {
        "index.html": {"text/html"},
        "style.css": {"text/css"},
        "index.md": {"text/markdown", "text/x-markdown"},
        "llms.txt": {"text/plain"},
        "robots.txt": {"text/plain"},
        "sitemap.xml": {"application/xml", "text/xml"},
    }
    for name, accepted in expected_mimes.items():
        assert mimetypes.guess_type(name)[0] in accepted
    assert (
        'rel="alternate" type="text/markdown" href="/index.md"' in (SITE / "index.html").read_text()
    )


def test_alvos_interativos_declaram_area_minima_de_44px() -> None:
    """Exija área mínima declarada para os principais alvos interativos."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    navigation = css_declarations(css, ".brand, .links a, .footer-row a")
    faq_summary = css_declarations(css, ".faq-list summary")

    assert navigation["min-width"] == "44px"
    assert navigation["min-height"] == "44px"
    assert navigation["justify-content"] == "center"
    assert faq_summary["min-height"] == "44px"


def test_header_sticky_nao_cobre_ancoras_no_layout_movel() -> None:
    """Evite que o header móvel cubra o destino de links internos."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    desktop_header = css_declarations(css, "header")
    mobile = css_block(css, "@media (max-width: 760px)")
    mobile_header = css_declarations(mobile, "header")

    assert desktop_header["position"] == "sticky"
    assert mobile_header["position"] == "static"
