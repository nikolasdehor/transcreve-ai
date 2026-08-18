"""Deteccao de codigo-fonte em texto capturado por OCR nos frames.

Palestras tecnicas e tutoriais mostram codigo na tela. O OCR generico devolve
esse codigo como texto corrido, sem marcacao e sem indentacao, o que e inutil
para um agente que le o dossie: ele nao consegue distinguir "codigo mostrado no
slide" de "bullet point do slide".

Aqui a gente decide se o texto de um frame e codigo e devolve o bloco com a
indentacao preservada, pronto para virar bloco cercado no markdown.
"""

import re

# Palavras que praticamente so aparecem em codigo. Ambiguas em prosa inglesa
# ("select", "update", "print", "from") ficam fora de proposito: elas entram
# apenas pela lista SQL abaixo, e so em caixa alta.
_KEYWORDS = frozenset(
    {
        "def",
        "class",
        "return",
        "import",
        "function",
        "const",
        "let",
        "var",
        "async",
        "await",
        "public",
        "private",
        "static",
        "void",
        "struct",
        "impl",
        "func",
        "package",
        "interface",
        "extends",
        "implements",
        "elif",
        "except",
        "raise",
        "throw",
        "catch",
        "finally",
        "yield",
        "lambda",
        "printf",
        "println",
        "self",
        "null",
        "nil",
        "true",
        "false",
    }
)

# SQL so conta em CAIXA ALTA, que e como aparece em slide de codigo. Assim um
# bullet como "Select the right model" nao vira bloco de codigo.
_SQL_UPPER = frozenset(
    {
        "SELECT",
        "FROM",
        "WHERE",
        "JOIN",
        "INSERT",
        "UPDATE",
        "DELETE",
        "GROUP",
        "ORDER",
        "HAVING",
        "VALUES",
        "CREATE",
        "ALTER",
        "TABLE",
    }
)

# Operadores e digrafos que raramente aparecem em prosa de slide.
_OPERATORS = (
    "->",
    "=>",
    "==",
    "!=",
    ">=",
    "<=",
    "::",
    "&&",
    "||",
    "+=",
    "-=",
    "**",
    "//",
    "/*",
    "*/",
    "</",
    "/>",
)

_SYMBOLS = frozenset("{}[]()<>;=|&$#@_/\\*")

# Chamada de funcao: parentese COLADO no identificador. Com "\s*" antes do
# parentese um titulo tipo "Video Intelligence (2026)" acionaria o sinal.
_CALL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(")
_ATTR_CALL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")
_ASSIGN_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_\[\]\.]*\s*=\s*\S")
_COMMENT_RE = re.compile(r"^\s*(#|//|/\*|\*)\s*\S")
_INDENT_RE = re.compile(r"^[ \t]{2,}\S")
_WORD_RE = re.compile(r"[A-Za-z_]+")

# URL e email carregam "//", "/", "@", "_" e ponto entre identificadores, ou
# seja, quase todos os sinais de codigo de uma vez. Sem remove-los antes, um
# slide de contato ("https://empresa.com/carreiras", "fulano@empresa.net") era
# classificado como codigo. Caso real: o slide final de uma palestra do PyCon.
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _strip_links(line: str) -> str:
    """Remove URLs e emails, que imitam a pontuacao de codigo."""
    return _EMAIL_RE.sub(" ", _URL_RE.sub(" ", line))


# Abaixo disso o texto e curto demais para uma decisao confiavel: uma unica
# linha tipo "Ferramentas (2026)" acertaria varios sinais por acidente.
_MIN_LINES = 2
_MIN_CHARS = 24

# Sinais possiveis por linha usados como denominador. Linha de codigo real
# costuma disparar de 2 a 4 dos 6; normalizar por 6 achatava tudo e derrubava
# SQL, que e sintaticamente pobre em simbolos.
_SIGNALS_PER_LINE = 3.0

# Calibrado com os casos do demo(): slide de titulo fica em ~0.17, SQL em ~0.44.
_SCORE_THRESHOLD = 0.35


def _line_signals(line: str) -> int:
    """Quantos sinais independentes de codigo esta linha exibe."""
    stripped = _strip_links(line).strip()
    if not stripped:
        return 0

    signals = 0
    words = _WORD_RE.findall(stripped)
    if any(word.lower() in _KEYWORDS for word in words):
        signals += 1
    elif any(word in _SQL_UPPER for word in words):
        signals += 1
    if any(op in stripped for op in _OPERATORS):
        signals += 1
    if _CALL_RE.search(stripped) or _ATTR_CALL_RE.search(stripped):
        signals += 1
    if _ASSIGN_RE.match(line) or _COMMENT_RE.match(line):
        signals += 1
    if _INDENT_RE.match(line):
        signals += 1

    symbol_count = sum(1 for char in stripped if char in _SYMBOLS)
    if symbol_count / len(stripped) >= 0.08:
        signals += 1

    return signals


def looks_like_code(text: str) -> bool:
    """True quando o texto OCR tem cara de codigo-fonte, nao de prosa de slide.

    Conservador de proposito: marcar bullet point como codigo estraga o dossie
    de forma mais visivel do que deixar passar um trecho de codigo.
    """
    if not text:
        return False

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < _MIN_LINES or len(text.strip()) < _MIN_CHARS:
        return False

    total = sum(_line_signals(line) for line in lines)
    score = total / (len(lines) * _SIGNALS_PER_LINE)
    return score >= _SCORE_THRESHOLD


def normalize_code_block(text: str) -> str:
    """Limpa o bloco preservando a indentacao relativa.

    Tesseract costuma acrescentar uma margem uniforme (o slide e centralizado),
    entao a gente remove o recuo comum a todas as linhas e mantem o resto, que e
    a estrutura real do codigo.
    """
    lines = [line.rstrip() for line in (text or "").splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    common = min(indents) if indents else 0
    if common:
        lines = [line[common:] if line.strip() else "" for line in lines]
    return "\n".join(lines)


_LINE_NUMBER_RE = re.compile(r"^(\s*)(\d{1,4})\s+(?=\S)")
# Na remocao tira o numero e UM separador apenas: o resto dos espacos e a
# indentacao do codigo, que precisa sobreviver.
_LINE_NUMBER_SUB_RE = re.compile(r"^(\s*)\d{1,4}[ \t]")


def strip_line_numbers(text: str) -> str:
    """Remove a coluna de numeros de linha que editores mostram na gutter.

    Num screencast o OCR le a gutter junto com o codigo, e o bloco sai como
    "1 def run():" / "2     total = 0", que nao cola em lugar nenhum. So remove
    quando a maioria das linhas tem numero E eles crescem, para nao mutilar
    codigo que legitimamente comeca com numero.
    """
    linhas = text.splitlines()
    uteis = [linha for linha in linhas if linha.strip()]
    if len(uteis) < 2:
        return text

    numeros: list[int] = []
    for linha in uteis:
        match = _LINE_NUMBER_RE.match(linha)
        if match:
            numeros.append(int(match.group(2)))

    if len(numeros) < max(2, int(len(uteis) * 0.7)):
        return text
    if any(b <= a for a, b in zip(numeros, numeros[1:])):
        return text

    return "\n".join(_LINE_NUMBER_SUB_RE.sub(r"\1", linha) for linha in linhas)


def extract_code_block(raw_ocr_text: str) -> str:
    """Bloco de codigo pronto para o markdown, ou string vazia se nao for codigo.

    Recebe o texto OCR CRU (com indentacao). Passar o texto ja normalizado por
    linha destroi o sinal de indentacao e degrada a deteccao.
    """
    if not looks_like_code(raw_ocr_text):
        return ""
    return normalize_code_block(raw_ocr_text)


def demo() -> None:
    """Self-check executavel: `uv run python -m video_kb.code_extraction`."""
    python_snippet = (
        "    def process(items):\n"
        "        results = []\n"
        "        for item in items:\n"
        "            results.append(item.value * 2)\n"
        "        return results\n"
    )
    js_snippet = (
        "const client = new Client({\n  apiKey: process.env.API_KEY,\n});\nawait client.run();\n"
    )
    sql_snippet = "SELECT id, name\nFROM users\nWHERE active = true;\n"
    prose_slide = (
        "Por que isso importa\n"
        "Agentes perdem contexto visual\n"
        "Slides carregam a informacao densa\n"
        "Transcricao sozinha nao basta\n"
    )
    title_slide = "Video Intelligence (2026)\nNikolas de Hor\n"
    english_bullets = (
        "Select the right model\nUpdate your prompts\nDelete old runs\nReview the output\n"
    )

    assert looks_like_code(python_snippet), "codigo Python deveria ser detectado"
    assert looks_like_code(js_snippet), "codigo JS deveria ser detectado"
    assert looks_like_code(sql_snippet), "SQL em caixa alta deveria ser detectado"
    assert not looks_like_code(prose_slide), "bullets de slide nao sao codigo"
    assert not looks_like_code(title_slide), "slide de titulo nao e codigo"
    assert not looks_like_code(english_bullets), "bullets em ingles nao sao codigo"

    # Caso real: slide final de palestra do PyCon, com OCR degradado. As URLs e
    # o email faziam o texto passar por codigo.
    slide_contato = (
        "Thank you!\n"
        "https://TechAtBloomberg.com/python\n"
        "https://www.bloomberg.com/careers\n"
        "Contact me: zchen344@bloomberg.net\n"
    )
    assert not looks_like_code(slide_contato), "slide de contato com URLs nao e codigo"
    assert not looks_like_code(""), "texto vazio nao e codigo"
    assert not looks_like_code("x = 1"), "uma linha so e curta demais para decidir"

    block = extract_code_block(python_snippet)
    assert block.startswith("def process"), f"indentacao comum nao foi removida: {block!r}"
    assert "    results = []" in block, "indentacao relativa deveria ser preservada"
    assert extract_code_block(prose_slide) == "", "prosa nao deveria virar bloco"

    print("code_extraction: todos os checks passaram")


if __name__ == "__main__":
    demo()

# Um frame pode mostrar chave de API, token ou URL assinada, e esse texto acaba
# no analysis.json e no markdown do dossie. Estes padroes cobrem o formato usual
# em codigo: atribuicao com nome sensivel, prefixos conhecidos de token e query
# string de URL assinada.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization|bearer|cookie)"
    r"(\s*[:=]\s*)"
    r"(['\"]?)([^\s'\"]{4,})(['\"]?)"
)
_TOKEN_PREFIX_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}"
    r"|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,})"
)
_SIGNED_QUERY_RE = re.compile(
    r"(?i)([?&](?:sig|signature|token|key|access_token|api_key)=)([^\s&'\"]+)"
)

_REDACTED = "[redacted]"


def redact_code_secrets(code: str) -> str:
    """Remove segredos de um bloco de codigo lido da tela.

    Mantem o nome da variavel, que e informacao util para quem le o dossie, e
    troca so o valor. Autocontido de proposito: a redacao precisa valer para
    qualquer consumidor do bloco, inclusive o markdown gerado de um
    analysis.json antigo.
    """
    if not code:
        return code
    redigido = _SECRET_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_REDACTED}{m.group(5)}", code
    )
    redigido = _TOKEN_PREFIX_RE.sub(_REDACTED, redigido)
    return _SIGNED_QUERY_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", redigido)
