from datetime import date

import pandas as pd
import streamlit as st

from auth_basic import require_login
from db import get_connection

st.set_page_config(page_title="Relatórios — APTUS", layout="wide")
require_login()

from caixa_config import SQL_LISTA_MES as SQL_CAIXA_MES
from recepcao_config import SQL_RELATORIO_RECEPCAO_MES
from relatorios_excel import (
    MESES_PT,
    excel_bytes_caixa,
    excel_bytes_recepcao,
    excel_bytes_toxic,
)
from toxic_config import SQL_RELATORIO_TOXICO_MES

st.markdown("### Relatórios Excel")
st.caption("Exportação mensal para Excel — mesmo critério das listas na base.")


@st.cache_data(ttl=120)
def _xlsx_recepcao(year: int, month: int) -> bytes:
    ref = date(year, month, 1)
    with get_connection() as conn:
        df = pd.read_sql(SQL_RELATORIO_RECEPCAO_MES, conn, params=[ref, ref])
    return excel_bytes_recepcao(df, ref)


@st.cache_data(ttl=120)
def _xlsx_caixa(year: int, month: int) -> bytes:
    ref = date(year, month, 1)
    with get_connection() as conn:
        df = pd.read_sql(SQL_CAIXA_MES, conn, params=[ref, ref])
    return excel_bytes_caixa(df, ref)


@st.cache_data(ttl=120)
def _xlsx_toxic(year: int, month: int) -> bytes:
    ref = date(year, month, 1)
    with get_connection() as conn:
        df = pd.read_sql(SQL_RELATORIO_TOXICO_MES, conn, params=[ref, ref])
    return excel_bytes_toxic(df, ref)


st.subheader("Seleccionar mês")
c1, c2 = st.columns([2, 1])
with c1:
    mes_idx = st.selectbox(
        "Mês",
        range(12),
        format_func=lambda i: MESES_PT[i],
        index=date.today().month - 1,
        key="rel_mes",
    )
with c2:
    ano_ref = st.number_input(
        "Ano",
        min_value=2000,
        max_value=2100,
        value=date.today().year,
        key="rel_ano",
    )

mes_nome = MESES_PT[mes_idx]
nome_ficheiro_base = f"{mes_nome}_{ano_ref}"

st.subheader("Relatórios disponíveis")

col_r, col_c, col_t = st.columns(3)

with col_r:
    st.markdown("##### Recepção")
    st.caption(
        "Lista de atendimentos do mês (data/hora, nome, tipo, empresa, exames, valor, pagamento, telefone, CPF)."
    )
    try:
        blob_r = _xlsx_recepcao(int(ano_ref), int(mes_idx) + 1)
        st.download_button(
            "GERAR EXCEL",
            data=blob_r,
            file_name=f"Relatorio_Recepcao_{nome_ficheiro_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_rec",
        )
    except Exception as e:
        st.error("Não foi possível preparar o Excel de Recepção.")
        st.exception(e)

with col_c:
    st.markdown("##### Caixa")
    st.caption("Movimentação do mês: data, descrição, entradas e saídas.")
    try:
        blob_c = _xlsx_caixa(int(ano_ref), int(mes_idx) + 1)
        st.download_button(
            "GERAR EXCEL",
            data=blob_c,
            file_name=f"Relatorio_Caixa_{nome_ficheiro_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_caixa",
        )
    except Exception as e:
        st.error("Não foi possível preparar o Excel de Caixa.")
        st.exception(e)

with col_t:
    st.markdown("##### Toxicológico")
    st.caption(
        "Exames do mês; status derivado de enviado/cobrado; linha de totais no fim."
    )
    try:
        blob_t = _xlsx_toxic(int(ano_ref), int(mes_idx) + 1)
        st.download_button(
            "GERAR EXCEL",
            data=blob_t,
            file_name=f"Relatorio_Toxicologico_{nome_ficheiro_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_tox",
        )
    except Exception as e:
        st.error("Não foi possível preparar o Excel Toxicológico.")
        st.exception(e)

st.caption(
    "Os botões descarregam o ficheiro **.xlsx**. Se alterar dados na base, espere até ~2 minutos "
    "ou mude o mês e volte — a cache dos relatórios renova-se automaticamente."
)
