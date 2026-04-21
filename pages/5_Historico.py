import re

import pandas as pd
import streamlit as st

from auth_basic import require_login
from db import get_connection

st.set_page_config(page_title="Histórico — APTUS", layout="wide")
require_login()

from historico_config import SQL_HISTORICO_RECEPCAO, SQL_HISTORICO_TOXIC

st.markdown("### Histórico do paciente / colaborador")
st.caption(
    "Pesquisa por **nome** ou **CPF** na **Recepção** e no **Toxicológico**. "
    "Mostra se há registos e o estado (ex.: atendido / pendente)."
)


def _normalizar_busca(txt: str) -> tuple[str, str]:
    termo = (txt or "").strip()
    digitos = re.sub(r"\D", "", termo)
    return termo, digitos


def _params_sql(termo: str, digitos: str) -> tuple[str, str, str]:
    like_nome = f"%{termo}%"
    flag = digitos if digitos else ""
    like_cpf = f"%{digitos}%" if digitos else ""
    return like_nome, flag, like_cpf


st.markdown("#### Pesquisar")
c_in, c_b1, c_b2 = st.columns([4, 1, 1])
with c_in:
    q = st.text_input(
        "Nome ou CPF",
        placeholder="Digite nome ou CPF e carregue em Buscar…",
        key="hist_query",
    )
with c_b1:
    buscar = st.button("Buscar", type="primary", use_container_width=True, key="hist_buscar")
with c_b2:
    limpar = st.button("Limpar", use_container_width=True, key="hist_limpar")

if limpar:
    st.session_state["hist_query"] = ""
    st.session_state.pop("hist_resultado_rec", None)
    st.session_state.pop("hist_resultado_tox", None)
    st.rerun()

if buscar:
    termo, digitos = _normalizar_busca(q)
    if not termo:
        st.warning("Escreva um **nome** ou **CPF** para pesquisar.")
    else:
        like_nome, flag, like_cpf = _params_sql(termo, digitos)
        params = (like_nome, flag, like_cpf)
        try:
            with get_connection() as conn:
                df_rec = pd.read_sql(SQL_HISTORICO_RECEPCAO, conn, params=params)
                df_tox = pd.read_sql(SQL_HISTORICO_TOXIC, conn, params=params)
            st.session_state["hist_resultado_rec"] = df_rec
            st.session_state["hist_resultado_tox"] = df_tox
            st.session_state["hist_ultimo_termo"] = termo
        except Exception as e:
            st.error("Não foi possível consultar a base.")
            st.exception(e)

df_rec = st.session_state.get("hist_resultado_rec")
df_tox = st.session_state.get("hist_resultado_tox")

if df_rec is not None and df_tox is not None:
    ultimo = st.session_state.get("hist_ultimo_termo", "")
    st.success(f"Resultados para: **{ultimo}**")

    st.subheader("Recepção")
    if df_rec.empty:
        st.info("Sem registos na **recepção** para este critério.")
    else:
        ver_rec = df_rec.rename(
            columns={
                "id": "ID",
                "quando": "Data / hora",
                "nome": "Nome",
                "tipo": "Tipo",
                "empresa": "Empresa",
                "exames": "Exames",
                "valor": "Valor",
                "pagamento": "Pagamento",
                "telefone": "Telefone",
                "cpf": "CPF",
                "situacao": "Situação",
            }
        )
        st.dataframe(ver_rec, use_container_width=True, hide_index=True)
        st.caption(
            "**Situação** na recepção usa `status_atendimento` (ex.: ATENDIDO, PENDENTE, TOXICOLOGICO)."
        )

    st.subheader("Toxicológico")
    if df_tox.empty:
        st.info("Sem registos em **toxicológico** para este critério.")
    else:
        ver_tox = df_tox.rename(
            columns={
                "id": "ID",
                "quando": "Data / hora",
                "nome": "Nome",
                "empresa": "Empresa",
                "cpf": "CPF",
                "situacao": "Status",
                "enviado": "Enviado",
                "cobrado": "Cobrado",
            }
        )
        st.dataframe(ver_tox, use_container_width=True, hide_index=True)

    if not df_rec.empty or not df_tox.empty:
        st.caption(
            "Se aparecer linhas em **Recepção** com situação **ATENDIDO** (ou similar), "
            "houve atendimento registado. Em **Toxicológico** vês exames/controlo associados ao mesmo nome/CPF."
        )
elif buscar is False:
    st.caption("Use **Buscar** depois de escrever nome ou CPF. **Limpar** reinicia a pesquisa.")
