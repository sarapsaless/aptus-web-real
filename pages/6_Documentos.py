import re
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Documentos — APTUS", layout="wide")

from documentos_config import (
    carregar_medicos_df,
    medico_row_com_crm,
    rotulos_medicos_unicos,
    texto_medico_select,
)
from documentos_guias_presets import (
    LAB_NENHUM,
    LABORATORIOS_PARCEIROS,
    PACOTE_NENHUM,
    PACOTES_EXAMES,
    lista_opcoes_laboratorios,
    lista_opcoes_pacotes,
)
from documentos_pdf import (
    gerar_acuidade_ishihara_pdf,
    gerar_acuidade_visual_pdf,
    gerar_atestado_fisico_mental_pdf,
    gerar_declaracao_comparecimento_pdf,
    gerar_guia_exames_pdf,
    gerar_romberg_pdf,
)


def _aplicar_pacote_guia() -> None:
    sel = st.session_state.get("doc_guia_pacote_sel")
    if sel and sel != PACOTE_NENHUM and sel in PACOTES_EXAMES:
        st.session_state.doc_guia_servicos = PACOTES_EXAMES[sel]


def _aplicar_lab_guia() -> None:
    sel = st.session_state.get("doc_guia_lab_sel")
    if sel and sel != LAB_NENHUM and sel in LABORATORIOS_PARCEIROS:
        st.session_state.doc_guia_local = LABORATORIOS_PARCEIROS[sel]

_COR_DOC = {
    "decl_comp": "#1a237e",
    "acuidade": "#3949ab",
    "acuidade_ishi": "#00838f",
    "romberg": "#2e7d32",
    "atestado": "#6a1b9a",
    "guia_exames": "#01579b",
}

_DOC_TITLES = (
    ("Declaração de Comparecimento", "decl_comp"),
    ("Acuidade Visual", "acuidade"),
    ("Acuidade + Ishihara", "acuidade_ishi"),
    ("Teste de Romberg", "romberg"),
    ("Atestado Físico e Mental", "atestado"),
    ("Guia de Exames", "guia_exames"),
)


def _digits_cpf(s: str, max_len: int = 11) -> str:
    return "".join(c for c in (s or "") if c.isdigit())[:max_len]


def _nome_ficheiro_pdf(titulo: str, slug: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", titulo, flags=re.UNICODE).strip("_")[:50] or slug
    return f"{base}.pdf"


st.markdown(
    """
<style>
.doc-bar { background:#5e35b1;color:white;padding:14px 18px;border-radius:8px;
font-weight:700;font-size:1.2rem;margin-bottom:18px;display:flex;align-items:center;gap:10px;}
</style>
<div class="doc-bar">DOCUMENTOS CLÍNICOS</div>
""",
    unsafe_allow_html=True,
)

st.caption(
    "Preencha paciente/colaborador e médico. **Gerar documento** produz um **PDF** alinhado aos modelos APTUS."
)

st.markdown("##### Paciente / colaborador (nome e CPF)")
h1, h2 = st.columns([3.2, 1.3])
with h1:
    st.caption("Nome / Buscar")
with h2:
    st.caption("CPF")
r1, r2 = st.columns([3.2, 1.3])
with r1:
    nome_busca = st.text_input(
        "Nome / Buscar",
        placeholder="Nome conforme recepção ou cadastro…",
        key="doc_nome",
        label_visibility="collapsed",
    )
with r2:
    cpf_doc = st.text_input(
        "CPF",
        placeholder="000.000.000-00",
        key="doc_cpf",
        label_visibility="collapsed",
    )

st.markdown("##### Médico (quem assina o documento)")
df_med = carregar_medicos_df()

if df_med is not None and not df_med.empty:
    rotulos = rotulos_medicos_unicos(df_med)
    # Após deduplicar médicos, o nº de opções mudou — evitar índice antigo inválido
    if rotulos and "doc_med_idx" in st.session_state:
        try:
            cur = int(st.session_state.doc_med_idx)
            if cur < 0 or cur >= len(rotulos):
                st.session_state.doc_med_idx = 0
        except (TypeError, ValueError):
            st.session_state.doc_med_idx = 0
    ix = st.selectbox(
        "Médico",
        range(len(rotulos)),
        format_func=lambda i: rotulos[i],
        key="doc_med_idx",
        label_visibility="collapsed",
    )
    med_row = df_med.iloc[int(ix)].to_dict()
    med_id = med_row.get("id")
else:
    st.warning(
        "Não foi possível carregar **public.medicos** — use o campo abaixo ou "
        "ajuste **documentos_config.py** ao seu Table Editor."
    )
    med_manual = st.text_input("Nome e CRM do médico (livre)", key="doc_med_manual")
    med_row = {"nome": med_manual or "", "crm": "", "uf": ""}
    med_id = None

st.markdown("##### Período do atendimento")
st.caption(
    "Usado na **Declaração de Comparecimento** (Matutino / Vespertino no PDF)."
)
periodo = st.radio(
    "Período",
    ["Matutino", "Vespertino"],
    horizontal=True,
    key="doc_periodo",
    label_visibility="collapsed",
)

st.markdown("##### Guia de exames (pedido, serviços e local)")
st.caption(
    "Preencha ao gerar **Guia de Exames**: nº do pedido, lista de exames/consultas e "
    "local do laboratório parceiro. **Pacotes** e **laboratórios** preenchem os campos "
    "de texto abaixo (pode editar depois)."
)

g1, g2 = st.columns([1.2, 1])
with g1:
    guia_numero_pedido = st.text_input(
        "Nº do pedido",
        placeholder="Ex.: 596-2026",
        key="doc_guia_pedido",
    )
with g2:
    guia_data_pedido = st.date_input(
        "Data do pedido",
        key="doc_guia_data",
    )

st.selectbox(
    "Pacote de exames (predefinido)",
    options=lista_opcoes_pacotes(),
    key="doc_guia_pacote_sel",
    on_change=_aplicar_pacote_guia,
    help="Substitui o texto em «Serviços». Os modelos editam-se em documentos_guias_presets.py.",
)

guia_servicos = st.text_area(
    "Serviços (um por linha)",
    placeholder="Hemograma\nGlicemia\nConsulta ocupacional…",
    height=110,
    key="doc_guia_servicos",
)

st.selectbox(
    "Laboratório parceiro",
    options=lista_opcoes_laboratorios(),
    key="doc_guia_lab_sel",
    on_change=_aplicar_lab_guia,
    help="Substitui o texto em «Local». Lista editável em documentos_guias_presets.py.",
)

guia_info_extra = st.text_area(
    "Local de realização / laboratório parceiro",
    placeholder="Nome do laboratório, endereço completo e horário de atendimento…",
    height=120,
    key="doc_guia_local",
)

st.markdown("##### Tipo de documento")

cols = st.columns(6)
btn_hit = None
for col, (titulo, slug) in zip(cols, _DOC_TITLES):
    hexcol = _COR_DOC[slug]
    with col:
        st.markdown(
            f"<div style=\"background:{hexcol};color:white;padding:14px;border-radius:10px;"
            f"text-align:center;font-weight:600;font-size:0.85rem;min-height:76px;"
            f"display:flex;align-items:center;justify-content:center;line-height:1.25;\">"
            f"{titulo}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Gerar documento", key=f"doc_btn_{slug}", use_container_width=True):
            btn_hit = (titulo, slug)


def _gerar_pdf(btn: tuple[str, str]) -> None:
    titulo, slug = btn
    nome = (nome_busca or "").strip()
    if not nome:
        st.warning("Indique pelo menos o **nome** do paciente/colaborador.")
        return

    cpf_limpo = _digits_cpf(cpf_doc, 11) or None
    mr = medico_row_com_crm(med_row) if med_row else None

    if slug == "guia_exames":
        pedido_txt = (guia_numero_pedido or "").strip()
        serv_txt = (guia_servicos or "").strip()
        if not pedido_txt:
            st.warning("Indique o **nº do pedido** para a guia de exames.")
            return
        if not serv_txt:
            st.warning("Indique pelo menos um **serviço / exame** (um por linha).")
            return

    try:
        if slug == "decl_comp":
            pdf_bytes = gerar_declaracao_comparecimento_pdf(
                paciente_nome=nome,
                paciente_cpf_digitos=cpf_limpo,
                periodo=periodo,
            )
        elif slug == "acuidade":
            pdf_bytes = gerar_acuidade_visual_pdf(
                paciente_nome=nome,
                paciente_cpf_digitos=cpf_limpo,
                medico_row=mr,
            )
        elif slug == "acuidade_ishi":
            pdf_bytes = gerar_acuidade_ishihara_pdf(
                paciente_nome=nome,
                paciente_cpf_digitos=cpf_limpo,
                medico_row=mr,
            )
        elif slug == "romberg":
            pdf_bytes = gerar_romberg_pdf(
                paciente_nome=nome,
                paciente_cpf_digitos=cpf_limpo,
                medico_row=mr,
            )
        elif slug == "atestado":
            pdf_bytes = gerar_atestado_fisico_mental_pdf(
                paciente_nome=nome,
                paciente_cpf_digitos=cpf_limpo,
                medico_row=mr,
            )
        elif slug == "guia_exames":
            d = guia_data_pedido
            data_ped = datetime(d.year, d.month, d.day) if d is not None else None
            pdf_bytes = gerar_guia_exames_pdf(
                paciente_nome=nome,
                numero_pedido=pedido_txt,
                servicos_texto=serv_txt,
                informacoes_adicionais=(guia_info_extra or "").strip(),
                data_pedido=data_ped,
            )
        else:
            st.error("Tipo de documento desconhecido.")
            return
    except Exception as e:
        st.error("Não foi possível gerar o PDF. Confirme se **fpdf2** está instalado (`pip install fpdf2`).")
        st.exception(e)
        return

    fname = _nome_ficheiro_pdf(titulo, slug)
    st.session_state["doc_pdf_bytes"] = pdf_bytes
    st.session_state["doc_pdf_fname"] = fname
    st.session_state["doc_pdf_meta"] = {
        "documento": titulo,
        "paciente": nome,
        "medico_id": med_id,
        "medico_rotulo": texto_medico_select(mr) if mr else None,
    }
    st.success("PDF gerado. Use **Descarregar PDF** abaixo.")
    st.rerun()


if btn_hit:
    _gerar_pdf(btn_hit)

pdf_bytes = st.session_state.get("doc_pdf_bytes")
pdf_fname = st.session_state.get("doc_pdf_fname")
if pdf_bytes:
    st.download_button(
        label="Descarregar PDF",
        data=bytes(pdf_bytes),
        file_name=pdf_fname or "documento.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=False,
        key="doc_dl_pdf",
    )
    if st.button("Limpar PDF gerado", key="doc_clear_pdf"):
        st.session_state.pop("doc_pdf_bytes", None)
        st.session_state.pop("doc_pdf_fname", None)
        st.session_state.pop("doc_pdf_meta", None)
        st.rerun()
