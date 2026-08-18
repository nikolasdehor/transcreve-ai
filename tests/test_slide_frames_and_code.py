"""Testes de frames por troca de slide e de extracao de codigo dos frames.

Cobrem o caminho que torna o dossie util para palestra tecnica longa: escolher
frames pelo conteudo da tela (e nao de N em N segundos), reconhecer codigo no
OCR e sincronizar frame + codigo com os capitulos no markdown.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

from video_kb.agent_workflow import AgentWorkflowOptions
from video_kb.code_extraction import (
    extract_code_block,
    looks_like_code,
    normalize_code_block,
    redact_code_secrets,
    strip_line_numbers,
)
from video_kb.media import _cap_timestamps, detect_slide_changes, extract_frames
from video_kb.models import (
    AnalysisResult,
    FrameObservation,
    KnowledgeSynthesis,
    SourceMetadata,
)
from video_kb.ocr import ocr_code_layout
from video_kb.pipeline import PipelineOptions, _should_detect_slides
from video_kb.report import (
    _chapter_start_seconds,
    _frame_for_timestamp,
    _render_code_blocks,
    _render_illustrated_chapters,
    render_markdown,
)
from video_kb.utils import CommandError


class _FakeProc:
    def __init__(self, stderr: str) -> None:
        self.stderr = stderr
        self.stdout = ""


def _metadata_log(pairs: list[tuple[float, float]]) -> str:
    """Reproduz o stderr do ffmpeg com o filtro metadata=print."""
    linhas = []
    for index, (tempo, score) in enumerate(pairs):
        linhas.append(f"[Parsed_metadata_3 @ 0x1] frame:{index}   pts:{index}   pts_time:{tempo}")
        linhas.append(f"[Parsed_metadata_3 @ 0x1] lavfi.scene_score={score:.6f}")
    return "\n".join(linhas) + "\n"


# Valores medidos num video real de slides: frames identicos ficam na casa de
# 1e-5 e a troca de slide marca ~0.03.
_SLIDES = _metadata_log(
    [
        (0.0, 0.000030),
        (5.0, 0.000001),
        (12.5, 0.035128),
        (20.0, 0.000002),
        (48.0, 0.024227),
        (49.0, 0.019000),
        (60.0, 0.000001),
    ]
)


class TestDeteccaoDeTrocaDeSlide:
    def test_extrai_timestamps_dos_picos_e_inclui_o_inicio(self) -> None:
        # Arrange
        with patch("video_kb.media.run_command", return_value=_FakeProc(_SLIDES)):
            # Act
            timestamps = detect_slide_changes(Path("/tmp/palestra.mp4"))

        # Assert: 0.0 entra na mao porque o primeiro slide nao e uma "mudanca".
        assert timestamps[0] == 0.0
        assert 12.5 in timestamps
        assert 48.0 in timestamps

    def test_ignora_frames_de_ruido_entre_as_trocas(self) -> None:
        with patch("video_kb.media.run_command", return_value=_FakeProc(_SLIDES)):
            timestamps = detect_slide_changes(Path("/tmp/palestra.mp4"))

        assert 5.0 not in timestamps
        assert 60.0 not in timestamps

    def test_descarta_keyframes_colados_da_mesma_transicao(self) -> None:
        with patch("video_kb.media.run_command", return_value=_FakeProc(_SLIDES)):
            timestamps = detect_slide_changes(Path("/tmp/palestra.mp4"))

        # 49.0 esta a 1s de 48.0: e a mesma animacao de slide, nao um slide novo.
        assert 49.0 not in timestamps

    def test_threshold_fixo_sobrepoe_a_heuristica(self) -> None:
        with patch("video_kb.media.run_command", return_value=_FakeProc(_SLIDES)):
            timestamps = detect_slide_changes(Path("/tmp/palestra.mp4"), threshold=0.5)

        # Nenhum score alcanca 0.5: nada detectado, e quem chamou cai no
        # fallback por intervalo em vez de ficar com um frame unico.
        assert timestamps == []

    def test_video_natural_sobe_o_corte_pela_mediana(self) -> None:
        # Camera na mao: o ruido de base ja e 0.02, entao 0.02 nao e "troca".
        natural = _metadata_log(
            [(0.0, 0.020), (5.0, 0.022), (10.0, 0.019), (15.0, 0.400), (20.0, 0.021)]
        )
        with patch("video_kb.media.run_command", return_value=_FakeProc(natural)):
            timestamps = detect_slide_changes(Path("/tmp/camera.mp4"))

        assert timestamps == [0.0, 15.0]

    def test_retorna_vazio_quando_ffmpeg_falha(self) -> None:
        erro = CommandError(["ffmpeg"], 1, "boom")
        with patch("video_kb.media.run_command", side_effect=erro):
            assert detect_slide_changes(Path("/tmp/x.mp4")) == []

    def test_retorna_vazio_quando_nao_ha_troca_de_cena(self) -> None:
        with patch("video_kb.media.run_command", return_value=_FakeProc("sem frames aqui")):
            assert detect_slide_changes(Path("/tmp/pessoa-falando.mp4")) == []


class TestEscolhaDaEstrategiaDeFrames:
    def test_video_longo_demais_para_o_intervalo_usa_deteccao(self) -> None:
        # 1h de video, 1 frame a cada 5s, teto de 80: o intervalo perde slides.
        assert _should_detect_slides("auto", duration=3600, interval=5.0, max_frames=80)

    def test_video_curto_mantem_amostragem_por_intervalo(self) -> None:
        # Reel de 60s: 12 frames cobrem tudo, nao ha por que decodificar de novo.
        assert not _should_detect_slides("auto", duration=60, interval=5.0, max_frames=80)

    def test_estrategia_explicita_ignora_a_heuristica(self) -> None:
        assert _should_detect_slides("slides", duration=10, interval=5.0, max_frames=80)
        assert not _should_detect_slides("interval", duration=99999, interval=5.0, max_frames=80)

    def test_sem_duracao_conhecida_nao_arrisca_deteccao(self) -> None:
        assert not _should_detect_slides("auto", duration=0, interval=5.0, max_frames=80)


class TestCapTimestamps:
    def test_respeita_o_teto_mantendo_inicio_e_fim(self) -> None:
        capped = _cap_timestamps([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], max_frames=3)

        assert len(capped) == 3
        assert capped[0] == 0.0
        assert capped[-1] == 5.0

    def test_sem_teto_devolve_tudo(self) -> None:
        original = [0.0, 1.0, 2.0]
        assert _cap_timestamps(original, max_frames=0) == original


class TestExtractFramesComTimestampsExplicitos:
    def test_usa_os_instantes_informados_em_vez_do_intervalo(self, tmp_path: Path) -> None:
        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        frames_dir = tmp_path / "frames"
        usados: list[float] = []

        def _fake_run(command, cwd=None):  # noqa: ANN001, ARG001
            instante = float(command[command.index("-ss") + 1])
            usados.append(instante)
            saida = Path(command[-1])
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_bytes(b"jpg")
            return _FakeProc("")

        with patch("video_kb.media.run_command", side_effect=_fake_run):
            paths = extract_frames(
                media,
                frames_dir,
                duration=600.0,
                interval=5.0,
                max_frames=80,
                timestamps=[0.0, 42.0, 300.0],
            )

        assert usados == [0.0, 42.0, 300.0]
        assert len(paths) == 3


class TestExtracaoDeCodigo:
    def test_reconhece_codigo_e_preserva_indentacao_relativa(self) -> None:
        ocr_cru = (
            "    def handler(event):\n"
            "        payload = parse(event)\n"
            "        return respond(payload)\n"
        )

        bloco = extract_code_block(ocr_cru)

        assert bloco.startswith("def handler(event):")
        assert "    payload = parse(event)" in bloco

    def test_bullets_de_slide_nao_viram_codigo(self) -> None:
        slide = (
            "Tres motivos para usar video\nContexto visual importa\nTranscricao sozinha nao basta\n"
        )

        assert not looks_like_code(slide)
        assert extract_code_block(slide) == ""

    def test_sql_em_caixa_alta_e_reconhecido(self) -> None:
        assert looks_like_code("SELECT id, name\nFROM users\nWHERE active = true;")

    def test_texto_vazio_ou_curto_nao_e_codigo(self) -> None:
        assert not looks_like_code("")
        assert not looks_like_code("total = 1")

    def test_normalize_remove_margem_comum_e_linhas_vazias_das_bordas(self) -> None:
        bruto = "\n\n      alpha\n        beta\n\n"

        assert normalize_code_block(bruto) == "alpha\n  beta"


class _FakeCompleted:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


_TSV_HEADER = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext"


def _tsv(rows: list[tuple[int, int, int, str]]) -> str:
    """Monta um TSV do tesseract a partir de (linha, left, width, texto)."""
    linhas = [_TSV_HEADER]
    for index, (line_num, left, width, text) in enumerate(rows, start=1):
        linhas.append(f"5\t1\t1\t1\t{line_num}\t{index}\t{left}\t100\t{width}\t30\t96\t{text}")
    return "\n".join(linhas) + "\n"


class TestReconstrucaoDeIndentacao:
    def test_recupera_niveis_de_indentacao_pelas_coordenadas(self) -> None:
        # Arrange: fonte monoespacada de ~20px por caractere; a linha 2 comeca
        # 80px a direita (4 caracteres) e a linha 3, 160px (8 caracteres).
        tsv = _tsv(
            [
                (1, 100, 60, "def"),
                (1, 180, 140, "run():"),
                (2, 180, 120, "total"),
                (2, 320, 20, "="),
                (3, 260, 120, "value"),
            ]
        )

        # Act
        with patch("video_kb.ocr.which", return_value="/usr/bin/tesseract"):
            with patch("video_kb.ocr.subprocess.run", return_value=_FakeCompleted(tsv)):
                resultado = ocr_code_layout(Path("/tmp/frame.jpg"), "eng")

        # Assert
        linhas = resultado.splitlines()
        assert linhas[0] == "def run():"
        assert linhas[1].startswith("    "), f"linha 2 deveria estar indentada: {linhas[1]!r}"
        recuo_2 = len(linhas[1]) - len(linhas[1].lstrip())
        recuo_3 = len(linhas[2]) - len(linhas[2].lstrip())
        assert recuo_3 > recuo_2, "o terceiro nivel deve ser mais profundo que o segundo"

    def test_tsv_vazio_devolve_string_vazia(self) -> None:
        with patch("video_kb.ocr.which", return_value="/usr/bin/tesseract"):
            with patch("video_kb.ocr.subprocess.run", return_value=_FakeCompleted(_TSV_HEADER)):
                assert ocr_code_layout(Path("/tmp/frame.jpg"), "eng") == ""

    def test_falha_do_tesseract_devolve_string_vazia(self) -> None:
        with patch("video_kb.ocr.which", return_value="/usr/bin/tesseract"):
            with patch(
                "video_kb.ocr.subprocess.run",
                return_value=_FakeCompleted("", returncode=1),
            ):
                assert ocr_code_layout(Path("/tmp/frame.jpg"), "eng") == ""

    def test_sem_tesseract_instalado_devolve_string_vazia(self) -> None:
        with patch("video_kb.ocr.which", return_value=None):
            assert ocr_code_layout(Path("/tmp/frame.jpg"), "eng") == ""


class TestGutterDeNumerosDeLinha:
    def test_remove_numeracao_sequencial_do_editor(self) -> None:
        bruto = "1 def run():\n2     total = 0\n3     return total"

        assert strip_line_numbers(bruto) == "def run():\n    total = 0\n    return total"

    def test_preserva_numeros_que_nao_sao_gutter(self) -> None:
        # Nao e coluna de gutter: os numeros nao crescem de um em um.
        bruto = "2024 foi o ano\n1999 foi outro"

        assert strip_line_numbers(bruto) == bruto

    def test_preserva_quando_poucas_linhas_tem_numero(self) -> None:
        bruto = "1 def run():\ntotal = 0\nreturn total\noutra linha"

        assert strip_line_numbers(bruto) == bruto

    def test_gutter_sai_do_tsv_antes_da_indentacao(self) -> None:
        # Numeros da gutter alinhados em left=40; codigo comeca em 110/170.
        tsv = _tsv(
            [
                (1, 40, 20, "1"),
                (1, 110, 60, "def"),
                (1, 190, 140, "run():"),
                (2, 40, 20, "2"),
                (2, 170, 120, "total"),
                (3, 40, 20, "3"),
                (3, 170, 140, "return"),
            ]
        )

        with patch("video_kb.ocr.which", return_value="/usr/bin/tesseract"):
            with patch("video_kb.ocr.subprocess.run", return_value=_FakeCompleted(tsv)):
                resultado = ocr_code_layout(Path("/tmp/frame.png"), "eng")

        linhas = resultado.splitlines()
        assert not any(linha.strip().startswith(("1 ", "2 ", "3 ")) for linha in linhas)
        assert linhas[0].startswith("def"), f"primeira linha nao deveria ter recuo: {linhas[0]!r}"
        recuo_2 = len(linhas[1]) - len(linhas[1].lstrip())
        assert recuo_2 > 0, "a indentacao do corpo deve sobreviver a remocao da gutter"


class TestCompatibilidadePosicional:
    """A flag nova nao pode deslocar argumentos de chamadas antigas."""

    def test_ordem_posicional_antiga_continua_valendo(self, tmp_path: Path) -> None:
        # Assinatura antiga: (out_dir, frame_interval, max_frames, visual_limit).
        # Com frame_strategy inserido no meio, o 25 cairia nele silenciosamente.
        options = PipelineOptions(tmp_path, 5.0, 80, 25)

        assert options.visual_limit == 25
        assert options.frame_strategy == "auto"

    def test_workflow_tambem_preserva_a_ordem(self, tmp_path: Path) -> None:
        options = AgentWorkflowOptions(tmp_path, 5.0, 80, 25)

        assert options.visual_limit == 25
        assert options.frame_strategy == "auto"


class TestFindingsDoReview:
    """Regressoes dos achados do review da PR #51."""

    def test_linhas_de_blocos_diferentes_nao_se_fundem(self) -> None:
        # line_num reinicia a cada paragrafo: sem a chave composta, a linha 1 do
        # bloco 2 seria mesclada com a linha 1 do bloco 1.
        linhas = [
            "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t100\t10\t60\t30\t96\tprimeiro",
            "5\t1\t2\t1\t1\t1\t100\t80\t60\t30\t96\tsegundo",
        ]
        tsv = "\n".join(linhas) + "\n"

        with patch("video_kb.ocr.which", return_value="/usr/bin/tesseract"):
            with patch("video_kb.ocr.subprocess.run", return_value=_FakeCompleted(tsv)):
                resultado = ocr_code_layout(Path("/tmp/frame.png"), "eng")

        assert resultado.splitlines() == ["primeiro", "segundo"]

    def test_imagem_estatica_respeita_o_formato_pedido(self, tmp_path: Path) -> None:
        # Carrossel e imagem solta tambem precisam do PNG no modo slides.
        imagem = tmp_path / "slide.png"
        imagem.write_bytes(b"fake")
        gerados: list[str] = []

        def _fake_run(command, cwd=None):  # noqa: ANN001, ARG001
            saida = Path(command[-1])
            gerados.append(saida.suffix)
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_bytes(b"img")
            return _FakeProc("")

        with patch("video_kb.media.run_command", side_effect=_fake_run):
            extract_frames(
                imagem,
                tmp_path / "f",
                duration=0.0,
                image_format="png",
            )

        assert gerados == [".png"]

    def test_ffmpeg_travado_nao_derruba_a_analise(self) -> None:
        travado = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1)
        with patch("video_kb.media.run_command", side_effect=travado):
            # Sem tratamento, o TimeoutExpired subiria e mataria a analise
            # inteira em vez de cair no fallback por intervalo.
            assert detect_slide_changes(Path("/tmp/travado.mp4")) == []

    def test_segredo_na_tela_nao_vaza_para_o_codigo(self) -> None:
        codigo = 'API_KEY = "sk-live-abc123"\nclient = Client(API_KEY)'

        redigido = redact_code_secrets(codigo)

        assert "sk-live-abc123" not in redigido
        assert "API_KEY" in redigido, "o nome da variavel pode ficar, so o valor sai"

    def test_markdown_nao_publica_segredo_lido_da_tela(self) -> None:
        frames = [
            FrameObservation(
                timestamp=0.0,
                image_path="frames/f0.png",
                code='token = "ghp_secreto123"',
            )
        ]

        markdown = "\n".join(_render_code_blocks(frames, is_carousel=False))

        assert "ghp_secreto123" not in markdown


class TestFormatoDoFrame:
    def test_slides_usa_png_para_nao_perder_texto_fino(self, tmp_path: Path) -> None:
        media = tmp_path / "v.mp4"
        media.write_bytes(b"fake")
        gerados: list[str] = []

        def _fake_run(command, cwd=None):  # noqa: ANN001, ARG001
            saida = Path(command[-1])
            gerados.append(saida.suffix)
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_bytes(b"img")
            return _FakeProc("")

        with patch("video_kb.media.run_command", side_effect=_fake_run):
            extract_frames(
                media,
                tmp_path / "f",
                duration=30.0,
                timestamps=[0.0, 10.0],
                image_format="png",
            )

        assert gerados == [".png", ".png"]

    def test_padrao_continua_jpg(self, tmp_path: Path) -> None:
        media = tmp_path / "v.mp4"
        media.write_bytes(b"fake")
        gerados: list[str] = []

        def _fake_run(command, cwd=None):  # noqa: ANN001, ARG001
            saida = Path(command[-1])
            gerados.append(saida.suffix)
            assert "-q:v" in command, "jpg deve manter o controle de qualidade"
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_bytes(b"img")
            return _FakeProc("")

        with patch("video_kb.media.run_command", side_effect=_fake_run):
            extract_frames(media, tmp_path / "f", duration=30.0, timestamps=[0.0])

        assert gerados == [".jpg"]


def _frames() -> list[FrameObservation]:
    return [
        FrameObservation(timestamp=0.0, image_path="frames/f0.jpg", ocr_text="Titulo"),
        FrameObservation(
            timestamp=60.0,
            image_path="frames/f1.jpg",
            ocr_text="def run(): pass",
            code="def run():\n    pass",
        ),
        FrameObservation(timestamp=120.0, image_path="frames/f2.jpg", ocr_text="Fim"),
    ]


class TestCapitulosIlustrados:
    def test_associa_o_frame_que_estava_na_tela_no_inicio_do_capitulo(self) -> None:
        frames = _frames()

        # 90s cai depois do frame de 60s: o slide vigente e o de 60s, nao o de 120s.
        frame = _frame_for_timestamp(frames, 90.0)

        assert frame is not None
        assert frame.image_path == "frames/f1.jpg"

    def test_antes_do_primeiro_frame_usa_o_primeiro(self) -> None:
        frame = _frame_for_timestamp(_frames(), -5.0)

        assert frame is not None
        assert frame.image_path == "frames/f0.jpg"

    def test_capitulo_recebe_imagem_e_codigo_do_frame(self) -> None:
        capitulos = [{"start": 60, "title": "Implementacao", "notes": "mostra o handler"}]

        linhas = _render_illustrated_chapters(capitulos, _frames())
        texto = "\n".join(linhas)

        assert "![01:00](frames/f1.jpg)" in texto
        assert "mostra o handler" in texto
        assert "def run():" in texto

    def test_sem_frames_nao_renderiza_capitulo_ilustrado(self) -> None:
        capitulos = [{"start": 10, "title": "Intro"}]

        assert _render_illustrated_chapters(capitulos, []) == []

    def test_aceita_start_em_formato_de_relogio(self) -> None:
        assert _chapter_start_seconds({"start": "01:30"}) == 90.0
        assert _chapter_start_seconds({"start": "1:00:00"}) == 3600.0
        assert _chapter_start_seconds({"start": 12.5}) == 12.5
        assert _chapter_start_seconds({"start": "abertura"}) is None


class TestSecaoDeCodigo:
    def test_lista_codigo_por_timestamp_sem_repetir(self) -> None:
        frames = _frames()
        frames.append(
            FrameObservation(
                timestamp=180.0,
                image_path="frames/f3.jpg",
                code="def run():\n    pass",
            )
        )

        linhas = _render_code_blocks(frames, is_carousel=False)
        texto = "\n".join(linhas)

        assert texto.count("def run():") == 1, "codigo repetido em outro frame nao duplica"
        assert "### 01:00" in texto

    def test_sem_codigo_nao_gera_secao(self) -> None:
        frames = [FrameObservation(timestamp=0.0, image_path="frames/f0.jpg")]

        assert _render_code_blocks(frames, is_carousel=False) == []


class TestMarkdownFinal:
    def test_dossie_traz_capitulos_ilustrados_e_secao_de_codigo(self) -> None:
        resultado = AnalysisResult(
            run_id="run-teste",
            created_at="2026-08-17T00:00:00Z",
            source="https://exemplo.test/palestra",
            workdir="/tmp/run-teste",
            media_path="video.mp4",
            audio_path="audio.mp3",
            metadata=SourceMetadata(source="https://exemplo.test/palestra", title="Palestra"),
            frames=_frames(),
            synthesis=KnowledgeSynthesis(
                summary="Uma palestra tecnica.",
                chapters=[{"start": 60, "title": "Implementacao"}],
            ),
        )

        markdown = render_markdown(resultado)

        assert "## Capitulos" in markdown
        assert "![01:00](frames/f1.jpg)" in markdown
        assert "## Codigo mostrado na tela" in markdown
        assert "```" in markdown
