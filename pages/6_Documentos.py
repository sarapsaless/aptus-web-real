import re
from datetime import datetime

import streamlit as st

from auth_basic import require_login

st.set_page_config(page_title="Documentos — APTUS", layout="wide")
require_login()

from documentos_config import (
    carregar_medicos_df,
    medico_row_com_crm,
    rotulos_medicos_unicos,
    texto_medico_select,
)
from documentos_guias_presets import (
    LAB_NENHUM,
    LABORATORIOS_PARCEIROS,
    lista_opcoes_laboratorios,
)
from documentos_db import (
    buscar_pacientes_nuvem,
    ensure_documentos_schema,
    listar_guias_recentes,
    listar_pacotes_salvos,
    obter_pdf_guia_por_id,
    proximo_numero_pedido,
    salvar_guia_exames,
    salvar_pacote_exames,
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
    db_map = st.session_state.get("doc_pacotes_db_map", {})
    if sel and sel in db_map:
        st.session_state.doc_guia_servicos = db_map[sel]


def _aplicar_lab_guia() -> None:
    sel = st.session_state.get("doc_guia_lab_sel")
    if sel and sel != LAB_NENHUM and sel in LABORATORIOS_PARCEIROS:
        st.session_state.doc_guia_local = LABORATORIOS_PARCEIROS[sel]


def _busca_nuvem_auto() -> None:
    """Disparado ao editar o campo de busca (mín. 3 caracteres)."""
    term = (st.session_state.get("doc_busca_nuvem") or "").strip()
    if len(term) < 3:
        st.session_state["doc_pacientes_sugestoes"] = []
        return
    try:
        st.session_state["doc_pacientes_sugestoes"] = buscar_pacientes_nuvem(term)
    except Exception:
        st.session_state["doc_pacientes_sugestoes"] = []


_COR_DOC = {
    "decl_comp": "#1a237e",
    "acuidade": "#3949ab",
    "acuidade_ishi": "#00838f",
    "romberg": "#2e7d32",
    "atestado": "#6a1b9a",
    "guia_exames": "#01579b",
    "aso": "#4a148c",
}

_DOC_TITLES = (
    ("Declaração de Comparecimento", "decl_comp"),
    ("Acuidade Visual", "acuidade"),
    ("Acuidade + Ishihara", "acuidade_ishi"),
    ("Teste de Romberg", "romberg"),
    ("Atestado Físico e Mental", "atestado"),
    ("Guia de Exames", "guia_exames"),
    ("ASO (Saúde Ocupacional)", "aso"),
)


def _digits_cpf(s: str, max_len: int = 11) -> str:
    return "".join(c for c in (s or "") if c.isdigit())[:max_len]


def _nome_ficheiro_pdf(titulo: str, slug: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", titulo, flags=re.UNICODE).strip("_")[:50] or slug
    return f"{base}.pdf"


def _fmt_cpf_11(cpf: str) -> str:
    d = _digits_cpf(cpf, 11)
    if len(d) != 11:
        return d
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"


if "doc_schema_ready" not in st.session_state:
    try:
        ensure_documentos_schema()
        st.session_state["doc_schema_ready"] = True
    except Exception:
        st.session_state["doc_schema_ready"] = False


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

if not st.session_state.get("doc_schema_ready"):
    st.error(
        "**Base de dados indisponível** — pacotes na nuvem, histórico de guias e busca de paciente "
        "não funcionam até corrigir `.streamlit/secrets.toml` (DB_URL ou DB_HOST + DB_PASS)."
    )

st.markdown("##### Paciente / colaborador")
hbus1, hbus2 = st.columns([3.5, 1.3])
with hbus1:
    filtro_paciente = st.text_input(
        "Nome / CPF",
        key="doc_busca_nuvem",
        placeholder="Digite nome ou CPF",
        on_change=_busca_nuvem_auto,
    )
with hbus2:
    if st.button("Buscar agora", key="doc_buscar_nuvem", use_container_width=True):
        try:
            st.session_state["doc_pacientes_sugestoes"] = buscar_pacientes_nuvem(filtro_paciente)
        except Exception:
            st.session_state["doc_pacientes_sugestoes"] = []
            st.warning("Não consegui buscar pacientes na nuvem agora.")

sugestoes = st.session_state.get("doc_pacientes_sugestoes", [])
if sugestoes:
    rotulos = ["— Nomes encontrados —"] + [
        f"{p['nome']} — CPF {_fmt_cpf_11(p['cpf']) if p['cpf'] else 'sem CPF'}" for p in sugestoes
    ]
    sel_sug = st.selectbox("Nomes encontrados", options=rotulos, key="doc_sel_sug_paciente")
    if sel_sug != rotulos[0]:
        idx = rotulos.index(sel_sug) - 1
        escolhido = sugestoes[idx]
        st.session_state["doc_nome"] = escolhido.get("nome", "")
        st.session_state["doc_cpf"] = escolhido.get("cpf", "")

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

st.markdown("##### Médico")
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

btn_hit = None

tab_decl, tab_guia = st.tabs(["Declarações e atestados", "Guia de exames"])

with tab_decl:
    st.markdown("##### Período do atendimento")
    periodo = st.radio(
        "Período",
        ["Matutino", "Vespertino"],
        horizontal=True,
        key="doc_periodo",
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("##### Escolha o documento e gere o PDF")
    _dc = (
        ("Declaração de Comparecimento", "decl_comp"),
        ("Acuidade Visual", "acuidade"),
        ("Acuidade + Ishihara", "acuidade_ishi"),
        ("Teste de Romberg", "romberg"),
        ("Atestado Físico e Mental", "atestado"),
    )
    r1, r2, r3 = st.columns(3)
    r4, r5 = st.columns(2)
    _cols_btn = [r1, r2, r3, r4, r5]
    for col, (titulo, slug) in zip(_cols_btn, _dc):
        hexcol = _COR_DOC[slug]
        with col:
            st.markdown(
                f"<div style=\"background:{hexcol};color:white;padding:12px;border-radius:10px;"
                f"text-align:center;font-weight:600;font-size:0.82rem;min-height:68px;"
                f"display:flex;align-items:center;justify-content:center;line-height:1.2;\">"
                f"{titulo}</div>",
                unsafe_allow_html=True,
            )
            if st.button("Gerar PDF", key=f"doc_btn_{slug}", use_container_width=True):
                btn_hit = (titulo, slug)

with tab_guia:
    st.markdown("##### Guia de exames")

    g1, g2, g3 = st.columns([1.25, 1.0, 1.0])
    with g1:
        if "doc_guia_pedido" not in st.session_state:
            try:
                ano_corrente = datetime.now().year
                prox, _ = proximo_numero_pedido(ano_corrente)
                st.session_state["doc_guia_pedido"] = prox
                st.session_state["doc_guia_seq"] = int(prox.split("-")[0])
            except Exception:
                st.session_state["doc_guia_pedido"] = ""
                st.session_state["doc_guia_seq"] = None
        guia_numero_pedido = st.text_input(
            "Nº do pedido (automático se a base ligar)",
            placeholder="Ex.: 001-2026",
            key="doc_guia_pedido",
        )
    with g2:
        guia_data_pedido = st.date_input(
            "Data do pedido",
            key="doc_guia_data",
        )
    with g3:
        if st.button(
            "Próximo nº automático",
            key="doc_guia_btn_proximo_pedido",
            use_container_width=True,
        ):
            try:
                dpd = st.session_state.get("doc_guia_data")
                ano_use = dpd.year if hasattr(dpd, "year") else datetime.now().year
                prox, seq = proximo_numero_pedido(int(ano_use))
                st.session_state["doc_guia_pedido"] = prox
                st.session_state["doc_guia_seq"] = seq
                st.rerun()
            except Exception:
                st.warning("Não foi possível ler a sequência na base — confira o `secrets` e a tabela de guias.")

    if not (st.session_state.get("doc_guia_pedido") or "").strip() and st.session_state.get("doc_schema_ready"):
        st.warning("Campo **Nº do pedido** vazio — clique em **Próximo nº automático** ou ligue a base.")

    guia_empresa = st.text_input(
        "Nome do combo",
        key="doc_guia_empresa",
        placeholder="Ex.: Planalto",
    )

    pacotes_db_opts = []
    pacotes_db_map: dict[str, str] = {}
    try:
        pacotes_db = listar_pacotes_salvos()
        for p in pacotes_db:
            label = f"{p.empresa} — {p.nome_pacote}"
            pacotes_db_opts.append(label)
            pacotes_db_map[label] = p.servicos_texto
    except Exception:
        pacotes_db = []
    st.session_state["doc_pacotes_db_map"] = pacotes_db_map
    st.session_state["doc_pacotes_db_objs"] = (
        {f"{p.empresa} — {p.nome_pacote}": p for p in pacotes_db} if pacotes_db else {}
    )

    st.selectbox(
        "Pacote de exames",
        options=["Editar"] + pacotes_db_opts,
        key="doc_guia_pacote_sel",
        on_change=_aplicar_pacote_guia,
    )

    guia_servicos = st.text_area(
        "Serviços (um por linha)",
        placeholder="Hemograma\nGlicemia\nConsulta ocupacional…",
        height=110,
        key="doc_guia_servicos",
    )

    st.markdown("###### Guardar combo por nome")
    if st.button(
        "Guardar combo",
        key="doc_salvar_pacote",
        type="primary",
    ):
        if not (guia_empresa or "").strip():
            st.warning("Informe a empresa.")
        elif not (guia_servicos or "").strip():
            st.warning("Preencha **Serviços (um por linha)** antes de guardar o pacote.")
        else:
            srv = (guia_servicos or "").strip()
            try:
                como = salvar_pacote_exames(guia_empresa, "COMBO", srv)
                if como == "updated":
                    st.success("Combo atualizado.")
                else:
                    st.success("Combo guardado.")
                st.rerun()
            except Exception as e:
                st.error("Não foi possível guardar o combo.")
                st.exception(e)

    st.selectbox(
        "Laboratório parceiro",
        options=lista_opcoes_laboratorios(),
        format_func=lambda x: "Editar" if x == LAB_NENHUM else x,
        key="doc_guia_lab_sel",
        on_change=_aplicar_lab_guia,
    )

    guia_info_extra = st.text_area(
        "Local de realização",
        placeholder="Ex.: BIOLAB — endereço completo e horário…",
        height=120,
        key="doc_guia_local",
    )

    st.divider()
    if st.button(
        "Gerar PDF — Guia de exames",
        key="doc_btn_guia_exames_main",
        type="primary",
        use_container_width=True,
    ):
        btn_hit = ("Guia de Exames", "guia_exames")

    with st.expander("Guias salvas", expanded=False):
        f1, f2 = st.columns([2, 1])
        with f1:
            filtro_emp_hist = st.text_input(
                "Filtrar por empresa (contém)",
                key="doc_guia_hist_filtro_empresa",
                placeholder="Ex.: Planalto — deixe vazio para todas",
            )
        with f2:
            lim_hist = st.number_input(
                "Máx. linhas",
                min_value=10,
                max_value=200,
                value=50,
                step=10,
                key="doc_guia_hist_lim",
            )

        try:
            guias = listar_guias_recentes(limite=int(lim_hist), empresa_filtro=filtro_emp_hist)
        except Exception:
            guias = []
            st.warning("Não consegui carregar guias salvas — confirme a ligação à base.")

        if not guias:
            st.write("Sem guias guardadas ainda.")
        else:
            opcoes = {
                f"{g['numero_pedido']} — {g['paciente_nome']} ({g['empresa'] or 'sem empresa'}) #{g['id']}": g
                for g in guias
            }
            escolha = st.selectbox(
                "Guia guardada",
                options=list(opcoes.keys()),
                key="doc_guia_historico_sel",
            )
            guia_sel = opcoes[escolha]
            st.write(
                f"Paciente: **{guia_sel['paciente_nome']}** | CPF: "
                f"{_fmt_cpf_11(guia_sel['paciente_cpf']) if guia_sel['paciente_cpf'] else 'sem CPF'} | "
                f"Empresa: **{guia_sel['empresa'] or '—'}**"
            )
            sid = int(guia_sel["id"])
            cache_sel = st.session_state.get("doc_hist_pdf_sel_id")
            cache_pdf = st.session_state.get("doc_hist_pdf_bytes")
            if cache_sel != sid:
                st.session_state["doc_hist_pdf_sel_id"] = sid
                try:
                    st.session_state["doc_hist_pdf_bytes"] = obter_pdf_guia_por_id(sid)
                except Exception:
                    st.session_state["doc_hist_pdf_bytes"] = None
                cache_pdf = st.session_state.get("doc_hist_pdf_bytes")

            if cache_pdf:
                st.download_button(
                    label="Descarregar PDF desta guia",
                    data=cache_pdf,
                    file_name=f"guia_{guia_sel['numero_pedido']}.pdf",
                    mime="application/pdf",
                    key=f"doc_btn_dl_hist_{sid}",
                    type="primary",
                )
            else:
                st.warning("Esta linha não tem PDF na base (guia antiga ou falha ao guardar).")



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
            try:
                pedido_manual = (guia_numero_pedido or "").strip()
                ano_pedido = datetime.now().year
                seq_pedido = st.session_state.get("doc_guia_seq")
                if "-" in pedido_manual:
                    pseq, pano = pedido_manual.split("-", 1)
                    if pseq.isdigit():
                        seq_pedido = int(pseq)
                    if pano.strip().isdigit():
                        ano_pedido = int(pano.strip())
                if seq_pedido is None:
                    try:
                        seq_pedido = int(pedido_manual.split("-", 1)[0])
                    except Exception:
                        seq_pedido = 0
                salvar_guia_exames(
                    numero_pedido=pedido_manual,
                    numero_seq=seq_pedido,
                    ano=ano_pedido,
                    data_pedido=d,
                    paciente_nome=nome,
                    paciente_cpf=cpf_limpo,
                    empresa=(guia_empresa or "").strip() or None,
                    servicos_texto=serv_txt,
                    local_texto=(guia_info_extra or "").strip(),
                    pdf_bytes=pdf_bytes,
                )
                try:
                    ano_prox = d.year if d is not None else datetime.now().year
                    prox_txt, prox_seq = proximo_numero_pedido(int(ano_prox))
                    st.session_state["doc_guia_pedido"] = prox_txt
                    st.session_state["doc_guia_seq"] = prox_seq
                except Exception:
                    pass
            except Exception as e:
                st.warning("PDF gerado, mas não consegui salvar a guia na nuvem.")
                st.exception(e)
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
    ok_msg = "PDF gerado. Use **Descarregar PDF** abaixo."
    if slug == "guia_exames":
        ok_msg += (
            " Quando a base PostgreSQL está ligada, esta guia fica também registada na tabela "
            "**`public.doc_guias_exames`** (histórico na aba **Guia de exames**, expander «Guias salvas»)."
        )
    st.success(ok_msg)
    st.rerun()


if btn_hit is not None:
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
