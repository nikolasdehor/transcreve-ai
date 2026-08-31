from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
SITE = ROOT / "docs/app-directory-site"


def test_landing_publica_checklist_com_evidencia_honesta() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")

    assert html.count("<details") >= 5
    assert 'id="caso-tecnico"' in html
    assert "sem cliente ou ganho atribuído" in html
    assert 'href="/privacidade.html"' in html
    assert 'href="/index.md"' in html
    assert 'href="/llms.txt"' in html


def test_site_publica_aeo_robots_e_politica_baseada_no_fluxo() -> None:
    privacy = (SITE / "privacidade.html").read_text(encoding="utf-8")
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")

    for filename in ("index.md", "llms.txt", "robots.txt", "sitemap.xml"):
        assert (SITE / filename).is_file()
    assert "áudio, frames, transcrição, OCR" in privacy
    assert "Execuções podem ser temporárias" in privacy
    assert "Sitemap: https://transcreve-ai-site.vercel.app/sitemap.xml" in robots
