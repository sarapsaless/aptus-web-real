from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from db import get_connection

st.set_page_config(page_title="Caixa — APTUS", layout="wide")

from caixa_config import (
    SQL_INSERT,
    SQL_LISTA_MES,
    TIPO_ENTRADA,
    TIPO_SAIDA,
)

st.title("Caixa")
st.caption("Movimentos em **public.lancamentos** — entradas e saídas do **mês** seleccionado.")

TIPOS_MOV = (TIPO_ENTRADA, TIPO_SAIDA)


def _parse_valor(txt: str) -> Decimal:
    t = (txt or "").strip().replace(",", ".")
    if not t:
        return Decimal("0")
    return Decimal(t)


def _es_entrada(tipo: object) -> bool:
    return str(tipo).strip().casefold() == "entrada"


def _es_saida(tipo: object) -> bool:
    s = str(tipo).strip().casefold()
    return s == "saida" or s == "saída"


def _dataframe_caixa_destaque(df: pd.DataFrame) -> object:
    raw = df.copy().reset_index(drop=True)

    def _cores_linha(row: pd.Series):
        i = row.name
        tipo = raw.iloc[int(i)].get("tipo")
        n = len(row)
        if _es_entrada(tipo):
            return ["background-color: #d4edda; border-left: 4px solid #28a745"] * n
        if _es_saida(tipo):
            return ["background-color: #fde8e8; border-left: 4px solid #dc3545"] * n
        return [""] * n

    cab = {
        "id": "ID",
        "n": "N°",
        "data_mov": "Data",
        "hora": "Hora",
        "tipo": "Tipo",
        "valor": "Valor",
        "descricao": "Descrição",
        "empresa_id": "Empresa (ID)",
    }
    cols_ordem = [
        "id",
        "n",
        "data_mov",
        "hora",
        "tipo",
        "valor",
        "descricao",
        "empresa_id",
    ]
    df_view = raw[cols_ordem].rename(columns=cab)
    try:
        return df_view.style.apply(_cores_linha, axis=1)
    except Exception:
        return df_view


def _totais_dia(df: pd.DataFrame) -> tuple[float, float, float]:
    if df.empty:
        return 0.0, 0.0, 0.0
    v = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    ent = float(v[df["tipo"].map(_es_entrada)].sum())
    sai = float(v[df["tipo"].map(_es_saida)].sum())
    return ent, sai, ent - sai


def _fmt_real(x: float) -> str:
    return "R$ " + f"{x:.2f}".replace(".", ",")


with st.form("form_caixa", clear_on_submit=False):
    st.subheader("Novo lançamento")
    r1, r2, r3, r4 = st.columns([1.2, 1.4, 1.3, 3.5])
    with r1:
        d_mov = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
    with r2:
        tipo_mov = st.selectbox("Tipo", TIPOS_MOV, index=0)
    with r3:
        valor_txt = st.text_input("Valor", placeholder="0,00")
    with r4:
        descricao = st.text_input("Descrição", placeholder="Ex.: ASO — nome — empresa")

    gravar = st.form_submit_button("Gravar lançamento", type="primary")

if gravar:
    if not (descricao or "").strip():
        st.warning("Preencha a **descrição**.")
    else:
        try:
            valor_dec = _parse_valor(valor_txt)
        except (InvalidOperation, ValueError):
            st.error("Valor inválido. Use números (ex.: `120` ou `120,50`).")
            st.stop()

        agora = datetime.now()
        data_txt = d_mov.strftime("%d/%m/%Y")
        data_ts = datetime.combine(d_mov, agora.time())
        v_float = float(valor_dec)
        mes = d_mov.month
        ano = d_mov.year
        params = (
            data_txt,
            data_ts,
            tipo_mov,
            v_float,
            valor_dec,
            descricao.strip(),
            mes,
            ano,
            None,
        )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_INSERT, params)
                conn.commit()
            st.session_state["caixa_recarregar_lista"] = True
            st.success("Lançamento gravado.")
        except Exception as e:
            st.error(
                "Não foi possível gravar. Confirme em **Supabase → lancamentos** "
                "se os nomes das colunas coincidem com `caixa_config.py`."
            )
            st.exception(e)

st.divider()
st.subheader("Lançamentos do mês")

fc1, fc2, fc3 = st.columns([2, 2, 2])
with fc1:
    filtro_data = st.date_input(
        "Mês de referência (qualquer dia desse mês)",
        value=date.today(),
        format="DD/MM/YYYY",
        key="caixa_filtro",
    )
with fc2:
    auto_lista = st.checkbox("Carregar lista ao abrir esta página", value=False, key="caixa_auto")
with fc3:
    btn_lista = st.button("Carregar / atualizar lista", key="caixa_btn")

_rec = st.session_state.pop("caixa_recarregar_lista", False)
executar_lista = btn_lista or auto_lista or _rec

if executar_lista:
    try:
        with st.spinner("A consultar a base…"):
            with get_connection() as conn:
                df = pd.read_sql(SQL_LISTA_MES, conn, params=[filtro_data, filtro_data])
        if df.empty:
            st.info("Sem lançamentos neste mês.")
            ent, sai, saldo = 0.0, 0.0, 0.0
        else:
            ent, sai, saldo = _totais_dia(df)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Total entradas", _fmt_real(ent))
        with m2:
            st.metric("Total saídas", _fmt_real(sai))
        with m3:
            st.metric("Saldo do mês (E − S)", _fmt_real(saldo))

        if not df.empty:
            st.dataframe(
                _dataframe_caixa_destaque(df),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "**Legenda:** verde = entrada · vermelho claro = saída. "
                "Valores somados conforme o campo **Tipo** (Entrada / Saida)."
            )
    except Exception as e:
        st.warning(
            "Não foi possível carregar os lançamentos. Verifique a ligação à base "
            "e se a tabela **public.lancamentos** existe."
        )
        st.exception(e)
else:
    st.caption(
        "Marque **Carregar lista ao abrir** ou clique em **Carregar / atualizar lista** "
        "para ver **todos os lançamentos do mês** e totais."
    )
