from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from auth_basic import require_login
from db import get_connection

st.set_page_config(page_title="Recepção — APTUS", layout="wide")
require_login()

from recepcao_config import (
    SQL_INSERT,
    SQL_LISTA_DIA,
    SQL_SELECT_BY_ID,
    SQL_SOFT_DELETE,
    SQL_SET_STATUS,
    SQL_UPDATE_ROW,
    STATUS_ATENDIDO,
    STATUS_PENDENTE,
    STATUS_TOXICOLOGICO,
)

st.title("Recepção")
st.caption("Registo rápido — mesmo fluxo que o desktop (campos numa linha).")

# Opções alinhadas ao desktop (dropdowns)
TIPOS = (
    "ADM",
    "PERIO",
    "DEM",
    "MF",
    "RT",
    "ATES. SAN. FIS.",
    "CONSULTA",
    "AV. MEDICA",
    "PERICIA",
)
PAGAMENTOS = ("DIN", "PIX", "DÉBITO", "CRÉDITO", "BOLETO", "PEND")


def _parse_valor(txt: str) -> Decimal:
    t = (txt or "").strip().replace(",", ".")
    if not t:
        return Decimal("0")
    return Decimal(t)


def _digits_only(s: str, max_len: int | None = None) -> str:
    out = "".join(c for c in (s or "") if c.isdigit())
    if max_len is not None:
        out = out[:max_len]
    return out


def _nome_linha_lista(df: pd.DataFrame, rid: int) -> str:
    row = df.loc[df["id"] == rid]
    if row.empty:
        return ""
    v = row.iloc[0].get("nome")
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return (s[:52] + "…") if len(s) > 52 else s


def _carregar_linha_editar(conn, rid: int) -> pd.Series | None:
    one = pd.read_sql(SQL_SELECT_BY_ID, conn, params=[rid])
    if one.empty:
        return None
    return one.iloc[0]


def _rotulo_atendimento(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "Pendente"
    s = str(val).strip().upper()
    if s == STATUS_ATENDIDO:
        return "Atendido"
    if s == STATUS_TOXICOLOGICO:
        return "Toxicológico"
    if s in ("", STATUS_PENDENTE, "PENDENTE"):
        return "Pendente"
    return str(val).strip()


def _dataframe_lista_com_destaque(df: pd.DataFrame) -> object:
    """Devolve DataFrame ou Styler com cores por estado de atendimento."""
    raw = df.copy().reset_index(drop=True)
    if "status_atendimento" not in raw.columns:
        raw["status_atendimento"] = ""
    raw["__atend"] = raw["status_atendimento"].map(_rotulo_atendimento)
    cab = {
        "id": "ID",
        "n": "N°",
        "data_hora": "Data / hora",
        "nome": "Nome",
        "cpf": "CPF",
        "__atend": "Atendimento",
        "tipo": "Tipo",
        "empresa": "Empresa",
        "exames": "Exames",
        "valor": "Valor",
        "pag": "Pag.",
        "telefone": "Telefone",
    }
    cols_ordem = [
        "id",
        "n",
        "data_hora",
        "nome",
        "cpf",
        "__atend",
        "tipo",
        "empresa",
        "exames",
        "valor",
        "pag",
        "telefone",
    ]
    df_view = raw[cols_ordem].rename(columns=cab)
    st_norm = (
        raw["status_atendimento"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    def _cores_linha(row: pd.Series):
        i = row.name
        st_val = st_norm.iloc[int(i)]
        n = len(row)
        if st_val == STATUS_ATENDIDO:
            return ["background-color: #d4edda; border-left: 4px solid #28a745"] * n
        if st_val == STATUS_TOXICOLOGICO:
            return ["background-color: #fff3cd; border-left: 4px solid #f0ad4e"] * n
        return [""] * n

    try:
        return df_view.style.apply(_cores_linha, axis=1)
    except Exception:
        return df_view


with st.form("form_recepcao", clear_on_submit=False):
    st.subheader("Novo atendimento")
    c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([1.1, 2.2, 1.2, 2.0, 2.2, 1.2, 1.2, 1.4, 2.2])
    with c1:
        d_reg = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
    with c2:
        nome = st.text_input("Nome", placeholder="Nome completo")
    with c3:
        tipo = st.selectbox("Tipo", TIPOS, index=0)
    with c4:
        empresa = st.text_input("Empresa", placeholder="Empresa / convénio")
    with c5:
        exames = st.text_input("Exames", placeholder="Ex.: ASO, toxicológico…")
    with c6:
        valor_txt = st.text_input("Valor", placeholder="0,00")
    with c7:
        pagamento = st.selectbox("Pagamento", PAGAMENTOS, index=0)
    with c8:
        fone = st.text_input("Fone", placeholder="Telefone")
    with c9:
        cpf = st.text_input("CPF", placeholder="Somente números")

    salvar = st.form_submit_button("Salvar", type="primary", use_container_width=False)

if salvar:
    if not (nome or "").strip():
        st.warning("Preencha pelo menos o **nome**.")
    else:
        cpf_limpo = _digits_only(cpf, 11)
        try:
            valor_dec = _parse_valor(valor_txt)
        except (InvalidOperation, ValueError):
            st.error("Valor inválido. Use números (ex.: `120` ou `120,50`).")
            st.stop()

        agora = datetime.now()
        data_txt = d_reg.strftime("%d/%m/%Y") + " " + agora.strftime("%H:%M")
        data_ts = datetime.combine(d_reg, agora.time())

        # valor: float4 na base | valor_num: numeric — mesmo valor em ambos
        v_float = float(valor_dec)
        cpf_txt = cpf_limpo or None
        # paciente_id / empresa_id: NULL até haver busca como no desktop (FK NOT NULL?)
        params = (
            data_txt,
            data_ts,
            nome.strip(),
            tipo,
            empresa.strip(),
            exames.strip(),
            v_float,
            valor_dec,
            pagamento,
            _digits_only(fone, 15) or None,
            cpf_txt,
            False,
            None,
            None,
            "PENDENTE",
        )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_INSERT, params)
                conn.commit()
            st.session_state["apos_salvar_lista"] = True
            st.success("Registo guardado.")
        except Exception as e:
            st.error(
                "Não foi possível gravar. Confirme em **Supabase → Table Editor** "
                "se a tabela e os nomes das colunas coincidem com `recepcao_config.py`."
            )
            st.exception(e)

st.divider()
st.subheader("Lista do dia")

fc1, fc2, fc3 = st.columns([2, 2, 2])
with fc1:
    filtro_data = st.date_input(
        "Filtrar por data", value=date.today(), format="DD/MM/YYYY", key="filtro_lista"
    )
with fc2:
    auto_lista = st.checkbox("Carregar lista ao abrir esta página", value=False)
with fc3:
    btn_lista = st.button("Carregar / atualizar lista")

# Evita bloquear a página à espera da base (timeout): só consulta quando pedir.
_após_salvar = st.session_state.get("apos_salvar_lista", False)
if _após_salvar:
    st.session_state["apos_salvar_lista"] = False
executar_lista = btn_lista or auto_lista or _após_salvar

if executar_lista:
    try:
        with st.spinner("A consultar a base…"):
            with get_connection() as conn:
                df = pd.read_sql(SQL_LISTA_DIA, conn, params=[filtro_data])
        if df.empty:
            st.info("Sem registos para esta data.")
            st.session_state.pop("recepcao_lista_df", None)
        else:
            st.session_state["recepcao_lista_df"] = df.copy()
            st.dataframe(
                _dataframe_lista_com_destaque(df),
                use_container_width=True,
                hide_index=True,
            )
            # —— Ações (menu tipo desktop) ——
            st.subheader("Ações sobre o registo")
            lista_df = st.session_state["recepcao_lista_df"]
            ids = [int(x) for x in lista_df["id"].tolist()]
            sel_id = st.selectbox(
                "Escolha o registo",
                options=ids,
                format_func=lambda i: f"{i} — {_nome_linha_lista(lista_df, i)}",
                key="recepcao_acao_sel",
            )

            a1, a2, a3, a4, a5 = st.columns(5)
            with a1:
                abrir_editar = st.button("Editar", key="acao_editar", use_container_width=True)
            with a2:
                btn_atendido = st.button("Atendido", key="acao_atendido", use_container_width=True)
            with a3:
                btn_tox = st.button("Toxicológico", key="acao_tox", use_container_width=True)
            with a4:
                btn_excluir = st.button("Excluir", key="acao_excluir", use_container_width=True)
            with a5:
                if st.button("Fechar edição", key="acao_fechar_edit", use_container_width=True):
                    st.session_state.pop("recepcao_edit_id", None)

            if abrir_editar:
                st.session_state["recepcao_edit_id"] = sel_id

            if btn_atendido:
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(SQL_SET_STATUS, (STATUS_ATENDIDO, sel_id))
                        conn.commit()
                    st.success("Marcado como **Atendido**.")
                    st.session_state["apos_salvar_lista"] = True
                    st.rerun()
                except Exception as e:
                    st.error("Não foi possível atualizar o estado.")
                    st.exception(e)

            if btn_tox:
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(SQL_SET_STATUS, (STATUS_TOXICOLOGICO, sel_id))
                        conn.commit()
                    st.session_state["toxic_origem_recepcao_id"] = int(sel_id)
                    st.session_state["toxic_origem_recepcao_nome"] = _nome_linha_lista(
                        lista_df, sel_id
                    )
                    st.session_state["apos_salvar_lista"] = True
                except Exception as e:
                    st.error("Não foi possível atualizar o estado.")
                    st.exception(e)
                else:
                    # Abre a página Toxicológico no browser (multipage Streamlit).
                    st.switch_page("pages/3_Toxicologico.py")

            excluir_key = f"excluir_confirm_{sel_id}"
            if btn_excluir:
                st.session_state[excluir_key] = True
            if st.session_state.get(excluir_key):
                st.warning("Confirma a exclusão deste registo? (marca como excluído na base.)")
                c_y, c_n = st.columns(2)
                with c_y:
                    if st.button("Confirmar exclusão", key=f"conf_excluir_y_{sel_id}"):
                        try:
                            with get_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute(SQL_SOFT_DELETE, (sel_id,))
                                conn.commit()
                            st.session_state.pop(excluir_key, None)
                            st.success("Registo excluído da lista ativa.")
                            st.session_state.pop("recepcao_edit_id", None)
                            st.session_state["apos_salvar_lista"] = True
                            st.rerun()
                        except Exception as e:
                            st.error("Não foi possível excluir.")
                            st.exception(e)
                with c_n:
                    if st.button("Cancelar", key=f"conf_excluir_n_{sel_id}"):
                        st.session_state.pop(excluir_key, None)
                        st.rerun()

            edit_id = st.session_state.get("recepcao_edit_id")
            if edit_id is not None:
                if int(edit_id) not in ids:
                    st.session_state.pop("recepcao_edit_id", None)
                else:
                    with st.expander("Editar registo", expanded=True):
                        try:
                            with get_connection() as conn:
                                row = _carregar_linha_editar(conn, int(edit_id))
                            if row is None:
                                st.error("Registo não encontrado ou já excluído.")
                            else:
                                ts = row.get("data_ts")
                                if hasattr(ts, "date"):
                                    d_ed = ts.date()
                                    hora_ed = ts.time()
                                else:
                                    d_ed = date.today()
                                    hora_ed = datetime.now().time()
                                vn = row.get("valor_num")
                                if vn is not None and not (
                                    isinstance(vn, float) and pd.isna(vn)
                                ):
                                    valor_es = str(vn).replace(".", ",")
                                else:
                                    vf = row.get("valor")
                                    valor_es = (
                                        ""
                                        if vf is None or (isinstance(vf, float) and pd.isna(vf))
                                        else str(vf)
                                    )

                                ek = f"_{int(edit_id)}"
                                with st.form("form_edit_recepcao"):
                                    st.caption(f"A editar ID **{edit_id}**")
                                    e1, e2 = st.columns(2)
                                    with e1:
                                        d_ed_in = st.date_input(
                                            "Data",
                                            value=d_ed,
                                            format="DD/MM/YYYY",
                                            key=f"edit_data{ek}",
                                        )
                                    with e2:
                                        hora_ed_in = st.time_input(
                                            "Hora",
                                            value=hora_ed,
                                            step=60,
                                            key=f"edit_hora{ek}",
                                        )
                                    ee1, ee2, ee3, ee4 = st.columns([2, 1.2, 2, 2])
                                    with ee1:
                                        nome_ed = st.text_input(
                                            "Nome",
                                            value=str(row.get("nome") or ""),
                                            key=f"edit_nome{ek}",
                                        )
                                    with ee2:
                                        tipo_ix = (
                                            TIPOS.index(row["tipo"])
                                            if row.get("tipo") in TIPOS
                                            else 0
                                        )
                                        tipo_ed = st.selectbox(
                                            "Tipo", TIPOS, index=tipo_ix, key=f"edit_tipo{ek}"
                                        )
                                    with ee3:
                                        empresa_ed = st.text_input(
                                            "Empresa",
                                            value=str(row.get("empresa") or ""),
                                            key=f"edit_empresa{ek}",
                                        )
                                    with ee4:
                                        exames_ed = st.text_input(
                                            "Exames",
                                            value=str(row.get("exames") or ""),
                                            key=f"edit_exames{ek}",
                                        )
                                    ee5, ee6, ee7, ee8 = st.columns([1.2, 1.2, 1.4, 2])
                                    with ee5:
                                        valor_ed = st.text_input(
                                            "Valor",
                                            value=valor_es,
                                            key=f"edit_valor{ek}",
                                        )
                                    with ee6:
                                        pag_ix = (
                                            PAGAMENTOS.index(row["pagamento"])
                                            if row.get("pagamento") in PAGAMENTOS
                                            else 0
                                        )
                                        pag_ed = st.selectbox(
                                            "Pagamento",
                                            PAGAMENTOS,
                                            index=pag_ix,
                                            key=f"edit_pag{ek}",
                                        )
                                    with ee7:
                                        fone_ed = st.text_input(
                                            "Fone",
                                            value=str(row.get("telefone") or ""),
                                            key=f"edit_fone{ek}",
                                        )
                                    with ee8:
                                        cpf_ed = st.text_input(
                                            "CPF",
                                            value=str(row.get("cpf") or ""),
                                            key=f"edit_cpf{ek}",
                                        )

                                    guardar_ed = st.form_submit_button(
                                        "Guardar alterações", type="primary"
                                    )

                                    if guardar_ed:
                                        if not (nome_ed or "").strip():
                                            st.warning("O **nome** é obrigatório.")
                                        else:
                                            cpf_l = _digits_only(cpf_ed, 11)
                                            try:
                                                valor_dec = _parse_valor(valor_ed)
                                            except (InvalidOperation, ValueError):
                                                st.error(
                                                    "Valor inválido. Use números (ex.: `120` ou `120,50`)."
                                                )
                                            else:
                                                data_txt_ed = (
                                                    d_ed_in.strftime("%d/%m/%Y")
                                                    + " "
                                                    + hora_ed_in.strftime("%H:%M")
                                                )
                                                data_ts_ed = datetime.combine(
                                                    d_ed_in, hora_ed_in
                                                )
                                                v_float = float(valor_dec)
                                                params_ed = (
                                                    data_txt_ed,
                                                    data_ts_ed,
                                                    nome_ed.strip(),
                                                    tipo_ed,
                                                    empresa_ed.strip(),
                                                    exames_ed.strip(),
                                                    v_float,
                                                    valor_dec,
                                                    pag_ed,
                                                    _digits_only(fone_ed, 15) or None,
                                                    cpf_l or None,
                                                    int(edit_id),
                                                )
                                                try:
                                                    with get_connection() as conn:
                                                        with conn.cursor() as cur:
                                                            cur.execute(
                                                                SQL_UPDATE_ROW, params_ed
                                                            )
                                                        conn.commit()
                                                    st.success("Alterações guardadas.")
                                                    st.session_state["apos_salvar_lista"] = True
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(
                                                        "Não foi possível guardar as alterações."
                                                    )
                                                    st.exception(e)
                        except Exception as e:
                            st.error("Não foi possível carregar o registo para edição.")
                            st.exception(e)
    except Exception as e:
        st.warning(
            "Não foi possível carregar a lista. Se ficar «a pensar» muito tempo, "
            "use no **secrets** a URI do **pooler** do Supabase (não a porta 5432 directa). "
            "Ajuste também **recepcao_config.py** se o esquema mudou."
        )
        st.exception(e)
