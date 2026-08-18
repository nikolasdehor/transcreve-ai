import re
import subprocess
from pathlib import Path
from typing import NamedTuple

from .utils import which


def available_tesseract_languages() -> list[str]:
    if not which("tesseract"):
        return []
    proc = subprocess.run(
        ["tesseract", "--list-langs"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return sorted(
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.lower().startswith("list of")
    )


def choose_language(preferred: str) -> tuple[str, str]:
    available = set(available_tesseract_languages())
    if not available:
        return "", "tesseract is not available; OCR skipped"

    requested = [part for part in re.split(r"[+,]", preferred or "") if part]
    supported = [part for part in requested if part in available]
    if supported:
        return "+".join(supported), ""
    if "eng" in available:
        return "eng", f"Requested OCR language '{preferred}' is unavailable; using eng"
    return sorted(available)[0], f"Requested OCR language '{preferred}' is unavailable"


# Colunas do TSV do tesseract (level, page, block, par, line, word, left, top,
# width, height, conf, text).
_TSV_PAGE = 1
_TSV_BLOCK = 2
_TSV_PAR = 3
_TSV_LINE = 4
_TSV_LEFT = 6
_TSV_WIDTH = 8
_TSV_TEXT = 11
_TSV_COLUMNS = 12

# line_num reinicia a cada paragrafo, entao sozinho ele funde linhas de blocos
# diferentes. A identidade de uma linha e o caminho inteiro na hierarquia
# Page > Block > Paragraph > Line.
_LineKey = tuple[int, int, int, int]

# Recuo maximo aceito por linha. Acima disso quase certamente e erro de leitura
# (uma figura ao lado do codigo, por exemplo) e nao indentacao real.
_MAX_INDENT = 40


class OcrResult(NamedTuple):
    """Saida do OCR em duas formas.

    `text` e a versao normalizada (uma linha util por linha, sem recuo), que e o
    que o dossie sempre usou. `raw` preserva a indentacao original, necessaria
    para reconhecer e reconstruir codigo mostrado na tela: `line.strip()` apaga
    justamente o sinal que distingue codigo de bullet point.
    """

    text: str
    raw: str


def ocr_image_detailed(image_path: Path, language: str) -> OcrResult:
    """Roda o tesseract uma vez e devolve as duas formas do texto."""
    if not language:
        return OcrResult("", "")
    tesseract = which("tesseract")
    if not tesseract:
        return OcrResult("", "")
    proc = subprocess.run(
        [tesseract, str(image_path), "stdout", "-l", language, "--psm", "6"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        return OcrResult("", "")

    raw_lines = [line.rstrip() for line in proc.stdout.splitlines()]
    raw = "\n".join(raw_lines).strip("\n")
    text = "\n".join(line.strip() for line in raw_lines if line.strip())
    return OcrResult(text, raw)


def ocr_image(image_path: Path, language: str) -> str:
    return ocr_image_detailed(image_path, language).text


def _drop_line_number_gutter(
    lines: dict[_LineKey, list[tuple[int, int, str]]],
) -> dict[_LineKey, list[tuple[int, int, str]]]:
    """Descarta a coluna de numeros de linha do editor.

    Precisa acontecer ANTES do calculo de indentacao: os numeros da gutter ficam
    todos na mesma coluna, entao, se ficarem, toda linha passa a ter o mesmo
    `left` e a indentacao do codigo se perde por completo.
    """
    primeiras = []
    for key in sorted(lines):
        palavras = sorted(lines[key], key=lambda item: item[0])
        if palavras:
            primeiras.append((key, palavras[0][2].strip()))

    numeradas = [(key, texto) for key, texto in primeiras if texto.isdigit()]
    if len(numeradas) < max(2, int(len(primeiras) * 0.7)):
        return lines

    valores = [int(texto) for _, texto in numeradas]
    if any(b <= a for a, b in zip(valores, valores[1:])):
        return lines

    limpas: dict[_LineKey, list[tuple[int, int, str]]] = {}
    chaves_numeradas = {key for key, _ in numeradas}
    for key, palavras in lines.items():
        ordenadas = sorted(palavras, key=lambda item: item[0])
        if key in chaves_numeradas:
            ordenadas = ordenadas[1:]
        if ordenadas:
            limpas[key] = ordenadas
    return limpas


def ocr_code_layout(image_path: Path, language: str) -> str:
    """Le a imagem preservando a indentacao, a partir das coordenadas do TSV.

    O tesseract alinha todas as linhas a esquerda em qualquer `--psm`, o que
    destroi a estrutura de codigo indentado (Python vira ambiguo). As posicoes
    horizontais do TSV, divididas pela largura media de caractere, devolvem o
    recuo original.

    Retorna string vazia quando o TSV nao vem utilizavel; quem chama mantem o
    texto simples nesse caso.

    ponytail: o recuo sai proporcional, nao exato (4 espacos podem virar 5),
    porque a largura de caractere e uma media. A hierarquia entre os niveis se
    mantem, que e o que importa para ler e para colar em Python. Se algum dia
    precisar do recuo exato, arredondar cada nivel para o multiplo do menor
    recuo nao nulo da imagem.

    LIMITE CONHECIDO: o tesseract perde o underscore em fonte de editor, entao
    `fetch_users` sai como `fetch users` e `__init__` como `init`. Testado sem
    sucesso: upscale 2x com lanczos e OCR so em ingles. Para codigo fiel o
    caminho e mandar o frame para o modelo de visao com um prompt de
    transcricao literal, o que custa API e por isso nao entra aqui.
    """
    if not language:
        return ""
    tesseract = which("tesseract")
    if not tesseract:
        return ""
    proc = subprocess.run(
        [tesseract, str(image_path), "stdout", "-l", language, "--psm", "6", "tsv"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        return ""

    lines: dict[_LineKey, list[tuple[int, int, str]]] = {}
    char_widths: list[float] = []
    for row in proc.stdout.splitlines()[1:]:
        columns = row.split("\t")
        if len(columns) < _TSV_COLUMNS:
            continue
        text = columns[_TSV_TEXT].strip()
        if not text:
            continue
        try:
            line_key = (
                int(columns[_TSV_PAGE]),
                int(columns[_TSV_BLOCK]),
                int(columns[_TSV_PAR]),
                int(columns[_TSV_LINE]),
            )
            left = int(columns[_TSV_LEFT])
            width = int(columns[_TSV_WIDTH])
        except ValueError:
            # Linha de cabecalho repetido ou coluna vazia: nao ha geometria
            # utilizavel nela, entao segue para a proxima palavra.
            continue
        lines.setdefault(line_key, []).append((left, width, text))
        char_widths.append(width / len(text))

    if not lines or not char_widths:
        return ""

    char_width = sum(char_widths) / len(char_widths)
    if char_width <= 0:
        return ""

    lines = _drop_line_number_gutter(lines)
    if not lines:
        return ""

    margin = min(min(left for left, _, _ in words) for words in lines.values())
    rendered: list[str] = []
    for key in sorted(lines):
        words = sorted(lines[key], key=lambda item: item[0])
        indent = int(round((words[0][0] - margin) / char_width))
        indent = max(0, min(indent, _MAX_INDENT))
        rendered.append(" " * indent + " ".join(text for _, _, text in words))
    return "\n".join(rendered)
