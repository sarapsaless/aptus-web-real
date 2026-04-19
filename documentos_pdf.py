"""Geração de PDF — modelos APTUS Medicina do Trabalho (fpdf2 + DejaVu, UTF-8)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

try:
    from fpdf import FPDF
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "Instale o pacote PyPI **fpdf2** (import: `from fpdf import FPDF`). "
        "Na venv: pip install fpdf2"
    ) from e

import fpdf as _fpdf_pkg

# Rodapé fixo da clínica — só institucional + morada (o médico que assina vai no corpo do documento)
APTUS_RODAPE_LINHAS: tuple[str, ...] = (
    "DR. VICTOR HUGO FINI JUNIOR - CRM 2480/RO - RQE 1285",
    "AVENIDA JATUARANA Nº 5316 - COHAB - PORTO VELHO/RO",
    "TELEFONE: (69) 3227-9015 | 98500-0015",
)

_FONT_DIR = Path(_fpdf_pkg.__file__).resolve().parent / "font"
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "logo_aptus.png"
_DEJAVU_DISPONIVEL = (_FONT_DIR / "DejaVuSans.ttf").is_file()

_MESES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)

# Altura reservada ao rodapé fixo (linha + 3 linhas); margem de quebra > isto para não sobrepor texto
_RODAPE_FIXO_MM = 30


class _AptusPdf(FPDF):
    """Rodapé institucional sempre no fundo da página (hook `footer` do FPDF)."""

    def footer(self) -> None:
        self.set_y(-_RODAPE_FIXO_MM)
        self.set_draw_color(160, 160, 160)
        y_linha = self.get_y()
        self.line(self.l_margin, y_linha, self.w - self.r_margin, y_linha)
        self.set_draw_color(0, 0, 0)
        self.ln(3)
        try:
            self.set_font("DejaVu", "", 8)
        except Exception:
            self.set_font("Helvetica", "", 8)
        self.set_text_color(90, 90, 90)
        for linha in APTUS_RODAPE_LINHAS:
            self.set_x(self.l_margin)
            self.multi_cell(0, 4, _normalizar_travessoes_pdf(linha), align="C")
        self.set_text_color(0, 0, 0)


def _output_pdf_bytes(pdf: FPDF) -> bytes:
    raw = pdf.output(dest="S")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return raw.encode("latin-1")


def _registar_fontes(pdf: FPDF) -> None:
    """DejaVu para português (acentos); fallback Helvetica se faltar o ficheiro."""
    sans = _FONT_DIR / "DejaVuSans.ttf"
    sans_b = _FONT_DIR / "DejaVuSans-Bold.ttf"
    if sans.is_file():
        pdf.add_font("DejaVu", "", str(sans))
        if sans_b.is_file():
            pdf.add_font("DejaVu", "B", str(sans_b))
        else:
            pdf.add_font("DejaVu", "B", str(sans))


def _normalizar_travessoes_pdf(s: str) -> str:
    """Helvetica só aceita Latin-1; travessões tipográficos (U+2013 …) rebentam o render."""
    for a, b in (
        ("\u2013", "-"),
        ("\u2014", "-"),
        ("\u2212", "-"),
    ):
        s = s.replace(a, b)
    return s


def _font(pdf: FPDF, estilo: str = "", tamanho: int = 11) -> None:
    try:
        pdf.set_font("DejaVu", estilo, tamanho)
    except Exception:
        pdf.set_font("Helvetica", estilo, tamanho)


def _write_html_pt(pdf: FPDF, html: str) -> None:
    """HTML no PDF com fonte adequada ao português (DejaVu embutido no fpdf2)."""
    fam = "DejaVu" if _DEJAVU_DISPONIVEL else "Helvetica"
    try:
        pdf.write_html(html, font_family=fam)
    except TypeError:
        pdf.write_html(html)


def _fmt_cpf_pdf(digitos: str | None) -> str:
    """CPF para texto; placeholder alinhado ao modelo desktop."""
    if not digitos:
        return "000.000.000-00"
    d = "".join(c for c in str(digitos) if c.isdigit())[:11]
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return digitos


def _data_extenso(dt: datetime, local: str = "Porto Velho-Ro") -> str:
    mes = _MESES[dt.month - 1]
    return f"{local}, {dt.day} de {mes} de {dt.year}."


def _medico_nome_bold_html(row: dict | None) -> str:
    """Nome do médico para trecho \"Eu, Dr(a). **NOME**\" (sem repetir Dr)."""
    if not row:
        return html.escape("_________________")
    n = (row.get("nome") or "").strip()
    if not n:
        return html.escape("_________________")
    for pref in ("dr(a).", "dr.", "dra.", "dr ", "dra "):
        if n.lower().startswith(pref):
            n = n[len(pref) :].lstrip()
            break
    return html.escape(n)


def _medico_crm_numero(row: dict | None) -> str:
    if not row:
        return "____/____"
    crm = (row.get("crm") or "").strip()
    uf = (row.get("uf") or "").strip()
    if crm and uf:
        return f"{crm}/{uf}"
    return crm or "____/____"


def _nova_pagina_base() -> _AptusPdf:
    pdf = _AptusPdf(format="A4")
    # Reservar espaço em baixo para o rodapé fixo (evita sobreposição e força quebra de página)
    pdf.set_auto_page_break(auto=True, margin=max(_RODAPE_FIXO_MM + 6, 32))
    _registar_fontes(pdf)
    pdf.add_page()
    pdf.set_margins(left=20, top=18, right=20)
    return pdf


def _cabecalho_logo_ou_texto(pdf: FPDF) -> None:
    # Sobe o logo/cabeçalho ~8 mm (~2 linhas em relação ao início da área útil)
    pdf.set_y(max(10.0, pdf.get_y() - 8))
    if _LOGO_PATH.is_file():
        try:
            img_w = 52
            x = pdf.l_margin + (pdf.epw - img_w) / 2
            pdf.image(str(_LOGO_PATH), x=x, w=img_w)
            pdf.ln(2)
            return
        except Exception:
            pass
    pdf.set_text_color(30, 80, 180)
    _font(pdf, "B", 16)
    pdf.multi_cell(0, 8, "APTUS", align="C")
    _font(pdf, "B", 10)
    pdf.multi_cell(0, 5, "MEDICINA DO TRABALHO", align="C")
    _font(pdf, "", 8)
    pdf.multi_cell(0, 4, "Saúde Ocupacional e Segurança do Trabalho", align="C")
    pdf.set_text_color(0, 0, 0)


def _titulo_doc(pdf: FPDF, titulo: str) -> None:
    pdf.ln(5)
    _font(pdf, "B", 13)
    pdf.multi_cell(0, 8, titulo.upper(), align="C")
    pdf.ln(4)


def _bloco_assinatura_carimbo(pdf: FPDF) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.ln(10)
    # Linha de assinatura com metade da largura útil, centrada
    metade = pdf.epw / 2
    x0 = pdf.l_margin + (pdf.epw - metade) / 2
    x1 = x0 + metade
    y = pdf.get_y()
    pdf.line(x0, y, x1, y)
    pdf.ln(2)
    _font(pdf, "", 10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, "CARIMBO E ASSINATURA", align="C")
    pdf.set_x(pdf.l_margin)
    pdf.ln(8)


def _data_alinhada_direita(pdf: FPDF, texto_data: str) -> None:
    _font(pdf, "", 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 7, _normalizar_travessoes_pdf(texto_data), align="R")
    pdf.set_x(pdf.l_margin)
    pdf.ln(4)


def gerar_declaracao_comparecimento_pdf(
    *,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    periodo: str,
    cidade_data: str = "Porto Velho-Ro",
) -> bytes:
    """Modelo Declaração de Comparecimento (texto e período como no desktop)."""

    dt = datetime.now()
    cpf_txt = _fmt_cpf_pdf(paciente_cpf_digitos)
    nome_esc = html.escape((paciente_nome or "").strip())

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, "DECLARAÇÃO DE COMPARECIMENTO")

    _font(pdf, "", 11)
    corpo = (
        f'<p align="justify">Declaro, para os devidos fins, que o(a) Sr(a). <b>{nome_esc}</b>, '
        f'inscrito(a) no CPF sob o nº <b>{html.escape(cpf_txt)}</b>, compareceu a esta clínica '
        f"para a realização de consulta médica nesta data, no período:</p>"
    )
    _write_html_pt(pdf, corpo)
    pdf.ln(6)

    mat = periodo.strip().lower().startswith("mat")
    m_sel, v_sel = ("X", " ") if mat else (" ", "X")
    _font(pdf, "", 11)
    pdf.cell(0, 8, f"({m_sel}) MATUTINO          ({v_sel}) VESPERTINO", ln=1)
    pdf.ln(6)

    _font(pdf, "", 11)
    pdf.multi_cell(0, 7, "E, por ser verdade, firmo a presente.", align="J")
    pdf.ln(8)

    _data_alinhada_direita(pdf, _data_extenso(dt, cidade_data))

    _bloco_assinatura_carimbo(pdf)

    return _output_pdf_bytes(pdf)


def gerar_acuidade_visual_pdf(
    *,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    medico_row: dict | None,
    cidade_data: str = "Porto Velho-Ro",
) -> bytes:
    _ = paciente_cpf_digitos  # reservado para futuras versões do modelo
    dt = datetime.now()
    nome_esc = html.escape((paciente_nome or "").strip())
    m_nome = _medico_nome_bold_html(medico_row)
    crm_n = html.escape(_medico_crm_numero(medico_row))

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, "ACUIDADE VISUAL")

    intro = (
        f'<p align="justify">Eu, Dr(a). <b>{m_nome}</b>, inscrito(a) no Conselho Regional de Medicina sob o CRM nº '
        f"<b>{crm_n}</b>, declaro para os devidos fins que examinei o(a) Sr(a). <b>{nome_esc}</b>, "
        f"apresentando visão:</p>"
    )
    _write_html_pt(pdf, intro)
    pdf.ln(6)

    _font(pdf, "", 11)
    pdf.cell(0, 7, "OD: ___________________________ | OE: ___________________________", ln=1)
    pdf.ln(5)
    pdf.multi_cell(0, 7, "( ) Normal / Sem correção    ( ) Com correção (uso de lentes/óculos)")
    pdf.ln(6)
    pdf.multi_cell(0, 7, "Estando, assim, apto(a) para as suas atividades laborais.", align="J")
    pdf.ln(10)

    _data_alinhada_direita(pdf, _data_extenso(dt, cidade_data))
    _bloco_assinatura_carimbo(pdf)

    return _output_pdf_bytes(pdf)


def gerar_acuidade_ishihara_pdf(
    *,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    medico_row: dict | None,
    cidade_data: str = "Porto Velho-Ro",
) -> bytes:
    _ = paciente_cpf_digitos  # não entra neste modelo; parâmetro alinhado à página
    dt = datetime.now()
    nome_esc = html.escape((paciente_nome or "").strip())
    m_nome = _medico_nome_bold_html(medico_row)
    crm_n = html.escape(_medico_crm_numero(medico_row))

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, "ACUIDADE VISUAL E ISHIHARA")

    intro = (
        f'<p align="justify">Eu, Dr(a). <b>{m_nome}</b>, inscrito(a) no Conselho Regional de Medicina sob o CRM nº '
        f"<b>{crm_n}</b>, declaro para os devidos fins que examinei o(a) Sr(a). <b>{nome_esc}</b>, "
        f"apresentando visão:</p>"
    )
    _write_html_pt(pdf, intro)
    pdf.ln(6)

    _font(pdf, "B", 11)
    pdf.cell(0, 7, "1. ACUIDADE VISUAL:", ln=1)
    _font(pdf, "", 11)
    pdf.cell(0, 7, "OD: ___________________________ | OE: ___________________________", ln=1)
    pdf.ln(4)
    pdf.multi_cell(0, 7, "( ) Normal / Sem correção    ( ) Com correção (uso de lentes/óculos)")
    pdf.ln(6)

    _font(pdf, "B", 11)
    pdf.cell(0, 7, "2. TESTE DE ISHIHARA", ln=1)
    _font(pdf, "", 11)
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 7, "( ) Normal (sem alterações na percepção de cores)")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        7,
        "( ) Alterado: ________________________________________________________________",
    )
    pdf.ln(6)
    pdf.multi_cell(0, 7, "Estando, assim, apto(a) para as suas atividades laborais.", align="J")
    pdf.ln(10)

    _data_alinhada_direita(pdf, _data_extenso(dt, cidade_data))
    _bloco_assinatura_carimbo(pdf)

    return _output_pdf_bytes(pdf)


def gerar_romberg_pdf(
    *,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    medico_row: dict | None,
    cidade_data: str = "Porto Velho-Ro",
) -> bytes:
    dt = datetime.now()
    cpf_txt = _fmt_cpf_pdf(paciente_cpf_digitos)
    nome_esc = html.escape((paciente_nome or "").strip())
    m_nome = _medico_nome_bold_html(medico_row)
    crm_n = html.escape(_medico_crm_numero(medico_row))

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, "TESTE DE ROMBERG")

    corpo = (
        f'<p align="justify">Eu, Dr(a). <b>{m_nome}</b>, inscrito(a) no Conselho Regional de Medicina sob o CRM nº '
        f"<b>{crm_n}</b>, declaro para os devidos fins que realizei o Teste de Romberg em "
        f"<b>{nome_esc}</b>, portador(a) do CPF <b>{html.escape(cpf_txt)}</b>, registrando abaixo o "
        f"resultado observado à data deste exame.</p>"
    )
    _write_html_pt(pdf, corpo)
    pdf.ln(7)
    _font(pdf, "", 11)
    pdf.multi_cell(0, 7, "Resultado / observações: _________________________________________________")
    pdf.ln(6)
    pdf.multi_cell(0, 7, "( ) Normal    ( ) Alterado (descrever): _______________________________________", align="J")
    pdf.ln(10)

    _data_alinhada_direita(pdf, _data_extenso(dt, cidade_data))
    _bloco_assinatura_carimbo(pdf)

    return _output_pdf_bytes(pdf)


def gerar_atestado_fisico_mental_pdf(
    *,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    medico_row: dict | None,
    cidade_data: str = "Porto Velho-Ro",
) -> bytes:
    dt = datetime.now()
    cpf_txt = _fmt_cpf_pdf(paciente_cpf_digitos)
    nome_esc = html.escape((paciente_nome or "").strip())
    m_nome = _medico_nome_bold_html(medico_row)
    crm_n = html.escape(_medico_crm_numero(medico_row))

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, "ATESTADO FÍSICO E MENTAL")

    corpo = (
        f'<p align="justify">Eu, Dr(a). <b>{m_nome}</b>, inscrito(a) no Conselho Regional de Medicina sob nº <b>{crm_n}</b>, '
        f"declaro que <b>{nome_esc}</b>, inscrito(a) no CPF sob nº <b>{html.escape(cpf_txt)}</b>, "
        f"foi por mim examinado(a) e, no momento, goza de boa saúde física e mental, estando "
        f"<b>APTO(A)</b> para exercer sua atividade laboral.</p>"
    )
    _write_html_pt(pdf, corpo)
    pdf.ln(12)

    _data_alinhada_direita(pdf, _data_extenso(dt, cidade_data))
    _bloco_assinatura_carimbo(pdf)

    return _output_pdf_bytes(pdf)


def gerar_pdf_documento_simples(
    *,
    titulo_documento: str,
    paciente_nome: str,
    paciente_cpf_digitos: str | None,
    periodo: str | None,
    medico_linha: str,
) -> bytes:
    """Compatibilidade: PDF genérico mínimo (evitar uso — prefira funções por tipo)."""
    dt = datetime.now()
    cpf_txt = _fmt_cpf_pdf(paciente_cpf_digitos)

    pdf = _nova_pagina_base()
    _cabecalho_logo_ou_texto(pdf)
    _titulo_doc(pdf, titulo_documento)

    _font(pdf, "", 11)
    txt = (
        f"Paciente / colaborador: {paciente_nome.strip()}\n\n"
        f"CPF: {cpf_txt}\n\n"
        + (f"Período: {periodo}\n\n" if periodo else "")
        + f"Médico / assinatura:\n{medico_linha}\n\n"
        f"Data: {dt.strftime('%d/%m/%Y')}"
    )
    pdf.multi_cell(0, 7, txt)

    return _output_pdf_bytes(pdf)
