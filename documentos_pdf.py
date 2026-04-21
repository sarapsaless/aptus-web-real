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


# Cabeçalho da guia de exames (alinhar aos dados cadastrais da clínica)
APTUS_GUIA_TITULO_CLINICA = "Aptus Medicina Do Trabalho / Dr. Victor Fini"
APTUS_GUIA_LINHAS_CABECALHO: tuple[str, ...] = (
    "CNPJ: 13.372.618/0001-24",
    "Avenida Jatuarana, 5316 - Cohab, Porto Velho-RO | CEP 76807-526",
    "Email: aptusclinica@hotmail.com",
    "Telefone: (69) 3227-9015 | 98500-0015",
)


def _cabecalho_guia_exames(pdf: FPDF, data_pedido: datetime) -> None:
    """Cabeçalho: logo à esquerda, dados da clínica ao lado, data no canto superior direito."""
    top_y = max(12.0, pdf.get_y())
    pdf.set_y(top_y)
    left_x = pdf.l_margin
    logo_w = 38.0
    logo_bottom = top_y + 26.0
    if _LOGO_PATH.is_file():
        try:
            pdf.image(str(_LOGO_PATH), x=left_x, y=top_y, w=logo_w)
            logo_bottom = top_y + 26.0
        except Exception:
            pass

    box_w = 34.0
    box_h = 9.0
    date_x = pdf.w - pdf.r_margin - box_w
    data_str = data_pedido.strftime("%d/%m/%Y")
    pdf.set_fill_color(238, 238, 238)
    pdf.rect(date_x, top_y, box_w, box_h, "F")
    _font(pdf, "", 9)
    pdf.set_text_color(55, 55, 55)
    pdf.set_xy(date_x, top_y + 2)
    pdf.cell(box_w, 5, data_str, align="C")
    pdf.set_text_color(0, 0, 0)

    text_x = left_x + logo_w + 6
    max_w = date_x - text_x - 4
    pdf.set_xy(text_x, top_y)
    _font(pdf, "B", 10)
    pdf.multi_cell(max_w, 5, _normalizar_travessoes_pdf(APTUS_GUIA_TITULO_CLINICA), align="L")
    _font(pdf, "", 8)
    for ln in APTUS_GUIA_LINHAS_CABECALHO:
        pdf.set_x(text_x)
        pdf.multi_cell(max_w, 4, _normalizar_travessoes_pdf(ln), align="L")

    pdf.set_y(max(logo_bottom, pdf.get_y()) + 5)


def _barra_pedido_escura(pdf: FPDF, texto_pedido: str) -> None:
    pdf.set_fill_color(88, 88, 88)
    pdf.set_text_color(255, 255, 255)
    _font(pdf, "B", 11)
    pdf.set_x(pdf.l_margin)
    pdf.cell(pdf.epw, 9, texto_pedido, ln=1, align="C", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(255, 255, 255)


def _barra_secao_clara(pdf: FPDF, titulo: str) -> None:
    pdf.ln(3)
    pdf.set_fill_color(228, 228, 228)
    _font(pdf, "B", 10)
    pdf.set_x(pdf.l_margin)
    pdf.cell(pdf.epw, 7, titulo, ln=1, align="L", fill=True)
    pdf.set_fill_color(255, 255, 255)


def _linha_local_data(pdf: FPDF, dt: datetime, cidade: str = "Porto Velho") -> None:
    pdf.ln(10)
    _font(pdf, "", 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        7,
        _normalizar_travessoes_pdf(f"{cidade}, {dt.strftime('%d/%m/%Y')}."),
        align="C",
    )


def _assinaturas_clinica_e_paciente(
    pdf: FPDF,
    *,
    nome_institucional_assinatura: str,
    nome_paciente: str,
) -> None:
    """Duas linhas de assinatura: clínica (esquerda) e paciente (direita)."""
    pdf.ln(8)
    gap = 6.0
    w_each = (pdf.epw - gap) / 2
    x_left = pdf.l_margin
    x_right = pdf.l_margin + w_each + gap
    y_line = pdf.get_y()
    pdf.line(x_left, y_line, x_left + w_each, y_line)
    pdf.line(x_right, y_line, x_right + w_each, y_line)
    y_txt = y_line + 3
    paciente_esc = _normalizar_travessoes_pdf((nome_paciente or "").strip())
    clinica_esc = _normalizar_travessoes_pdf((nome_institucional_assinatura or "").strip())
    _font(pdf, "", 9)
    pdf.set_xy(x_left, y_txt)
    pdf.multi_cell(w_each, 4, clinica_esc, align="C")
    y_end = pdf.get_y()
    pdf.set_xy(x_right, y_txt)
    pdf.multi_cell(w_each, 4, paciente_esc, align="C")
    pdf.set_y(max(y_end, pdf.get_y()) + 4)


def gerar_guia_exames_pdf(
    *,
    paciente_nome: str,
    numero_pedido: str,
    servicos_texto: str,
    informacoes_adicionais: str,
    data_pedido: datetime | None = None,
    cidade_data: str = "Porto Velho",
    nome_institucional_assinatura: str = "Aptus Medicina e Segurança do Trabalho",
) -> bytes:
    """Guia de exames — modelo com cabeçalho institucional, pedido, serviços e local."""

    dt = data_pedido or datetime.now()
    nome_cli = html.escape((paciente_nome or "").strip())
    pedido_esc = html.escape((numero_pedido or "").strip())
    serv_raw = (servicos_texto or "").strip()
    info_raw = (informacoes_adicionais or "").strip()

    linhas_serv = [ln.strip() for ln in serv_raw.splitlines() if ln.strip()]
    if not linhas_serv:
        # ASCII apenas: Helvetica (fallback sem DejaVu) não aceita U+2014 (travessão)
        linhas_serv = ["Nao indicado"]

    pdf = _nova_pagina_base()
    _cabecalho_guia_exames(pdf, dt)

    pedido_txt = pedido_esc.strip() if pedido_esc else ""
    _barra_pedido_escura(
        pdf,
        _normalizar_travessoes_pdf(f"Pedido {pedido_txt if pedido_txt else '-'}"),
    )

    pdf.ln(4)
    _font(pdf, "B", 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 7, f"Cliente: {nome_cli}", align="L")

    _barra_secao_clara(pdf, "Serviços")
    pdf.ln(1)
    _font(pdf, "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.set_x(pdf.l_margin)
    pdf.cell(0, 5, "Descrição", ln=1)
    pdf.set_text_color(0, 0, 0)
    _font(pdf, "", 11)
    for item in linhas_serv:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5.5, f"- {_normalizar_travessoes_pdf(item)}", align="L")

    # Rótulo pedido explicitamente no modelo impresso (evitar confusão com “informações adicionais”)
    _barra_secao_clara(pdf, "LOCAL DE REALIZAÇÃO")
    pdf.ln(2)
    _font(pdf, "", 11)
    if info_raw:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5.5, _normalizar_travessoes_pdf(info_raw), align="L")
    else:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, _normalizar_travessoes_pdf("\u2014"), align="L")

    _linha_local_data(pdf, dt, cidade=cidade_data)
    _assinaturas_clinica_e_paciente(
        pdf,
        nome_institucional_assinatura=nome_institucional_assinatura,
        nome_paciente=(paciente_nome or "").strip(),
    )

    return _output_pdf_bytes(pdf)


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


# --- ASO (modelo com caixas, alinhado ao impresso APTUS / NR-7) ---
APTUS_ASO_ENDERECO_FONE = (
    "Av. Jatuarana, n 5503 - Nova Floresta - Porto Velho - RO - "
    "(69) 3227-9015 / (69) 98500-0015"
)

# Textos longos dos grupos ERGONOMICO / ACIDENTE (modelo papel)
ASO_TEXTO_ERG_PADRAO = (
    "Exigencias de posturas inadequadas / Movimentos repetitivos / Situacoes de estresses / "
    "Levantamento e transportes manuais de cargas"
)

ASO_TEXTO_ACI_PADRAO = (
    "Quedas do mesmo nivel / Quedas de nivel diferenciado / Atropelamento de corpo inteiro / "
    "Esmagamento de corpo inteiro / Prensamento de membros (Superiores e inferiores) / "
    "Cortes e perfuracoes / Queda de materiais diversos / Projecoes de materiais diversos"
)

ASO_TIPOS_KEYS: tuple[str, ...] = (
    "ADMISSIONAL",
    "PERIODICO",
    "DEMISSIONAL",
    "MUDANCA_DE_RISCO_OCUPACIONAL",
    "RETORNO_AO TRABALHO",
)


def _aso_caixa_titulo(pdf: FPDF, titulo: str) -> None:
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    w = pdf.epw
    pdf.set_fill_color(228, 228, 228)
    _font(pdf, "B", 9)
    pdf.multi_cell(w, 6, _normalizar_travessoes_pdf(titulo), align="L", fill=True)
    pdf.set_fill_color(255, 255, 255)
    pdf.ln(1)


def _aso_chk(pdf: FPDF, marcado: bool, texto: str) -> None:
    m = "X" if marcado else " "
    _font(pdf, "", 7)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, 4, _normalizar_travessoes_pdf(f"({m}) {texto}"), align="L")


def _aso_header_aso(pdf: FPDF) -> None:
    """Cabeçalho ASO: exige x=l_margin e largura=epw (evita epw=0 após image/margens)."""
    w = pdf.epw
    if w < 10:
        w = max(pdf.w - pdf.l_margin - pdf.r_margin, 50)
    top = pdf.get_y()
    if _LOGO_PATH.is_file():
        try:
            x_img = pdf.l_margin + (w - 34) / 2
            pdf.image(str(_LOGO_PATH), x=x_img, y=top, w=34)
            pdf.set_xy(pdf.l_margin, top + 22)
        except Exception:
            pdf.set_xy(pdf.l_margin, top + 2)
    else:
        pdf.set_xy(pdf.l_margin, top + 2)
    _font(pdf, "B", 10)
    pdf.multi_cell(w, 5, _normalizar_travessoes_pdf("APTUS MEDICINA DO TRABALHO"), align="C")
    pdf.set_x(pdf.l_margin)
    _font(pdf, "", 7)
    pdf.multi_cell(
        w,
        4,
        _normalizar_travessoes_pdf("Saude Ocupacional e Seguranca do Trabalho"),
        align="C",
    )
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w, 4, _normalizar_travessoes_pdf(APTUS_ASO_ENDERECO_FONE), align="C")
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    pdf.set_fill_color(235, 235, 235)
    _font(pdf, "B", 11)
    pdf.multi_cell(
        w,
        7,
        _normalizar_travessoes_pdf("ATESTADO MEDICO DE SAUDE OCUPACIONAL (ASO)"),
        align="C",
        fill=True,
    )
    pdf.set_fill_color(255, 255, 255)
    pdf.ln(3)


def _aso_bloco_identificacao(
    pdf: FPDF,
    *,
    empresa: str,
    cnpj: str,
    nome: str,
    cpf_fmt: str,
    funcao: str,
    idade_txt: str,
) -> None:
    pdf.set_draw_color(80, 80, 80)
    pdf.set_line_width(0.2)
    x0 = pdf.l_margin
    w = pdf.epw
    w2 = w / 2
    y0 = pdf.get_y()
    h1 = 8
    _font(pdf, "", 7)
    pdf.rect(x0, y0, w, h1)
    pdf.set_xy(x0 + 1, y0 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"EMPRESA: {empresa or '-'}"), align="L")
    pdf.set_xy(x0 + w2 + 1, y0 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"CNPJ: {cnpj or '-'}"), align="L")
    y1 = y0 + h1
    pdf.rect(x0, y1, w, h1)
    pdf.set_xy(x0 + 1, y1 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"NOME: {nome or '-'}"), align="L")
    pdf.set_xy(x0 + w2 + 1, y1 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"CPF: {cpf_fmt}"), align="L")
    y2 = y1 + h1
    pdf.rect(x0, y2, w, h1)
    pdf.set_xy(x0 + 1, y2 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"FUNCAO: {funcao or '-'}"), align="L")
    pdf.set_xy(x0 + w2 + 1, y2 + 1)
    pdf.multi_cell(w2 - 2, 4, _normalizar_travessoes_pdf(f"IDADE: {idade_txt or '-'}"), align="L")
    pdf.set_y(y2 + h1 + 2)


def _aso_linha_medico(row: dict | None, extra_linha: str | None = None) -> str:
    if not row:
        return _normalizar_travessoes_pdf(extra_linha or "______________________________")
    n = (row.get("nome") or "").strip()
    crm = (row.get("crm") or "").strip()
    uf = (row.get("uf") or "").strip()
    base = f"Dr(a). {n}"
    if crm and uf:
        base += f". CRM/{uf} {crm}"
    elif crm:
        base += f". CRM {crm}"
    if extra_linha and str(extra_linha).strip():
        base += ". " + str(extra_linha).strip()
    return _normalizar_travessoes_pdf(base)


def gerar_aso_pdf(
    *,
    empresa_nome: str,
    empresa_cnpj: str,
    trabalhador_nome: str,
    trabalhador_cpf_digitos: str | None,
    funcao: str,
    idade_txt: str,
    tipo_aso: str,
    marcar_ausente: bool,
    marcar_fisico: bool,
    texto_fisico: str,
    marcar_quimico: bool,
    texto_quimico: str,
    marcar_biologico: bool,
    texto_biologico: str,
    marcar_ergonomico: bool,
    texto_ergonomico: str | None,
    marcar_acidente: bool,
    texto_acidente: str | None,
    data_exame_clinico_txt: str,
    exames_complementares_txt: str,
    observacao: str,
    apto: bool,
    data_conclusao: datetime | None,
    medico_avaliador_linha: str,
    medico_coordenador_row: dict | None,
    medico_coordenador_extra: str | None = None,
    cidade_data: str = "Porto Velho",
) -> bytes:
    """ASO ocupacional — layout em caixas semelhante ao modelo em papel."""

    tipo_norm = (tipo_aso or "").strip().upper()
    if tipo_norm not in ASO_TIPOS_KEYS:
        tipo_norm = "PERIODICO"

    cpf_fmt = _fmt_cpf_pdf(trabalhador_cpf_digitos)
    nome_txt = _normalizar_travessoes_pdf((trabalhador_nome or "").strip())
    emp_txt = _normalizar_travessoes_pdf((empresa_nome or "").strip())
    cnpj_txt = _normalizar_travessoes_pdf((empresa_cnpj or "").strip())
    func_txt = _normalizar_travessoes_pdf((funcao or "").strip())
    idade_v = _normalizar_travessoes_pdf((idade_txt or "").strip())

    pdf = _AptusPdf(format="A4")
    pdf.set_auto_page_break(auto=True, margin=max(_RODAPE_FIXO_MM + 8, 34))
    _registar_fontes(pdf)
    # Margens antes da primeira página — senão epw pode ficar inválido no cabeçalho ASO
    pdf.set_margins(left=11, top=10, right=11)
    pdf.add_page()
    pdf.set_xy(pdf.l_margin, pdf.t_margin)

    _aso_header_aso(pdf)

    labels_tipo = (
        ("ADMISSIONAL", "ADMISSIONAL"),
        ("PERIODICO", "PERIODICO"),
        ("DEMISSIONAL", "DEMISSIONAL"),
        ("MUDANCA_DE_RISCO_OCUPACIONAL", "MUDANCA DE RISCO OCUPACIONAL"),
        ("RETORNO_AO TRABALHO", "RETORNO AO TRABALHO"),
    )
    _aso_caixa_titulo(pdf, "TIPO DE EXAME")
    for key, rot in labels_tipo:
        _aso_chk(pdf, tipo_norm == key, rot)
    pdf.ln(2)

    _aso_bloco_identificacao(
        pdf,
        empresa=emp_txt,
        cnpj=cnpj_txt,
        nome=nome_txt,
        cpf_fmt=cpf_fmt,
        funcao=func_txt,
        idade_txt=idade_v,
    )

    _aso_caixa_titulo(pdf, "PROCEDIMENTOS MEDICOS REALIZADOS:")

    ew = pdf.epw
    _font(pdf, "B", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(ew, 4, _normalizar_travessoes_pdf("RISCOS:"), align="L")
    _font(pdf, "", 7)
    _aso_chk(pdf, marcar_ausente, "AUSENTE")
    _aso_chk(
        pdf,
        marcar_fisico,
        "FISICO: Ruido Ocupacional"
        + (f" | {texto_fisico.strip()}" if (texto_fisico or "").strip() else ""),
    )
    _aso_chk(
        pdf,
        marcar_quimico,
        "QUIMICO: Produtos quimicos de limpeza"
        + (f" ({texto_quimico.strip()})" if (texto_quimico or "").strip() else ""),
    )
    _aso_chk(
        pdf,
        marcar_biologico,
        "BIOLOGICO: Virus, Bacterias, Protozoarios, Fungos, Parasitas"
        + (f" | {texto_biologico.strip()}" if (texto_biologico or "").strip() else ""),
    )
    te = (texto_ergonomico or "").strip() or ASO_TEXTO_ERG_PADRAO
    _aso_chk(
        pdf,
        marcar_ergonomico,
        f"ERGONOMICO: {te}",
    )
    ta = (texto_acidente or "").strip() or ASO_TEXTO_ACI_PADRAO
    _aso_chk(
        pdf,
        marcar_acidente,
        f"ACIDENTE: {ta}",
    )

    pdf.ln(2)
    _font(pdf, "", 7)
    dex = _normalizar_travessoes_pdf((data_exame_clinico_txt or "").strip() or "__/__/__")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        ew,
        4,
        _normalizar_travessoes_pdf(f"EXAME CLINICO: _________________ Data: {dex}"),
        align="L",
    )
    pdf.ln(1)
    _font(pdf, "B", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(ew, 4, _normalizar_travessoes_pdf("EXAMES COMPLEMENTARES:"), align="L")
    _font(pdf, "", 7)
    comp_raw = (exames_complementares_txt or "").strip()
    if not comp_raw:
        comp_raw = "1. __________________________________ Data: __/__/__"
    for i, ln in enumerate(comp_raw.splitlines(), start=1):
        if not ln.strip():
            continue
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(ew, 4, _normalizar_travessoes_pdf(ln.strip()), align="L")

    pdf.ln(2)
    _font(pdf, "B", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(ew, 4, _normalizar_travessoes_pdf("OBSERVACAO:"), align="L")
    _font(pdf, "", 7)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        ew,
        4,
        _normalizar_travessoes_pdf((observacao or "").strip() or "-"),
        align="L",
    )

    pdf.ln(3)
    _font(pdf, "", 7)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        ew,
        4,
        _normalizar_travessoes_pdf(
            "DECLARAMOS QUE APOS INVESTIGACAO CLINICA, DE ACORDO COM A NR7 O CANDIDATO(A) "
            "A FUNCAO ACIMA DECLARADA FOI CONSIDERADO(A):"
        ),
        align="J",
    )
    pdf.ln(2)
    ma = "X" if apto else " "
    mi = "X" if not apto else " "
    _font(pdf, "B", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(ew, 5, f"({ma}) APTO(A).    ({mi}) INAPTO(A).", align="L")
    pdf.ln(5)

    dt_conc = data_conclusao or datetime.now()
    dstr = dt_conc.strftime("%d/%m/%Y")
    coord_txt = _aso_linha_medico(medico_coordenador_row, medico_coordenador_extra)
    aval_txt = _normalizar_travessoes_pdf((medico_avaliador_linha or "").strip() or "_________________________")

    wcol = (pdf.epw - 6) / 2
    y_sig = pdf.get_y()
    x_left = pdf.l_margin
    x_right = pdf.l_margin + wcol + 6

    _font(pdf, "B", 7)
    pdf.set_xy(x_left, y_sig)
    pdf.multi_cell(wcol, 4, _normalizar_travessoes_pdf("MEDICO AVALIADOR:"), align="L")
    _font(pdf, "", 7)
    pdf.set_x(x_left)
    pdf.multi_cell(wcol, 4, aval_txt, align="L")
    pdf.set_x(x_left)
    pdf.multi_cell(wcol, 4, _normalizar_travessoes_pdf("Recebi a 2 via do ASO em: ___/___/______"), align="L")
    y_left_end = pdf.get_y()

    _font(pdf, "B", 7)
    pdf.set_xy(x_right, y_sig)
    pdf.multi_cell(wcol, 4, _normalizar_travessoes_pdf(f"CONCLUSAO EM: {dstr}"), align="L")
    _font(pdf, "", 7)
    pdf.set_x(x_right)
    pdf.multi_cell(wcol, 4, _normalizar_travessoes_pdf("MEDICO COORDENADOR:"), align="L")
    pdf.set_x(x_right)
    pdf.multi_cell(wcol, 4, coord_txt, align="L")
    y_right_end = pdf.get_y()

    y_line = max(y_left_end, y_right_end) + 4
    pdf.set_y(y_line)
    pdf.line(x_left, y_line, x_left + wcol, y_line)
    pdf.line(x_right, y_line, x_right + wcol, y_line)
    pdf.ln(3)
    _font(pdf, "", 6)
    pdf.set_x(x_left)
    pdf.multi_cell(wcol, 3, _normalizar_travessoes_pdf("Carimbo / assinatura medica"), align="C")
    pdf.set_xy(x_right, y_line + 3)
    pdf.multi_cell(wcol, 3, _normalizar_travessoes_pdf("ASSINATURA DO EMPREGADO SUBMETIDO AO EXAME"), align="C")

    pdf.set_y(max(pdf.get_y(), y_line + 12))
    pdf.ln(6)
    _font(pdf, "", 7)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(ew, 4, _normalizar_travessoes_pdf(f"{cidade_data}, {dstr}."), align="L")

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
