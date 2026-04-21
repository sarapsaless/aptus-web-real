from datetime import date, datetime

import pandas as pd
import streamlit as st

from auth_basic import require_login
from db import get_connection

st.set_page_config(page_title="Toxicológico — APTUS", layout="wide")
require_login()

from toxic_config import (
    INSERT_COM_RECEPCAO_ID,
    SQL_INSERT,
    SQL_LISTA_MES,
    SQL_UPDATE_ENVIO_COBRADO,
)

st.markdown("### Controle toxicológico")
st.caption("Registos em **public.toxic** — lista completa do **mês** seleccionado.")

MESES = (
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
SIM_NAO = ("NÃO", "SIM")


def _etiqueta_registo_toxic(df: pd.DataFrame, rid: int) -> str:
    row = df.loc[df["id"] == rid]
    if row.empty:
        return str(rid)
    nome = row.iloc[0].get("nome") or ""
    dm = row.iloc[0].get("data_mov") or ""
    s = str(nome).strip()
    curto = (s[:38] + "…") if len(s) > 38 else s
    return f"{rid} — {dm} — {curto}"


def _digits_cpf(s: str, max_len: int = 11) -> str:
    out = "".join(c for c in (s or "") if c.isdigit())
    return out[:max_len]


def _fmt_cpf_exib(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    d = _digits_cpf(str(v), 11)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return str(v).strip()


def _bool_enviado_faturado(v: object) -> bool:
    if v is True or v == 1:
        return True
    if v is False or v == 0:
        return False
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    s = str(v).strip().casefold()
    return s in ("sim", "true", "t", "1", "s")


def _rotulo_sim_nao(v: object) -> str:
    return "Sim" if _bool_enviado_faturado(v) else "Não"


def _pendentes_nao_enviados(df: pd.DataFrame) -> int:
    if df.empty or "enviado" not in df.columns:
        return 0
    return int((~df["enviado"].map(_bool_enviado_faturado)).sum())


def _data_mov_para_date(v: object) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "date") and callable(getattr(v, "date")):
        try:
            return v.date()
        except Exception:
            pass
    s = str(v).strip()
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        try:
            return pd.to_datetime(v, dayfirst=True).date()
        except Exception:
            return None


def _situacao_row(row: pd.Series) -> str:
    if _bool_enviado_faturado(row.get("enviado")):
        return "Enviado"
    d0 = _data_mov_para_date(row.get("data_mov"))
    if d0 is None:
        return "—"
    limite = date.fromordinal(d0.toordinal() + 7)
    if date.today() > limite:
        return "Atrasado"
    return "7d"


def _dataframe_toxic_destaque(df: pd.DataFrame) -> object:
    raw = df.copy().reset_index(drop=True)
    raw["env_txt"] = raw["enviado"].map(_rotulo_sim_nao)
    raw["fat_txt"] = raw["faturado"].map(_rotulo_sim_nao)
    raw["cpf_fmt"] = raw["cpf"].map(_fmt_cpf_exib)
    raw["sit"] = raw.apply(_situacao_row, axis=1)

    cab = {
        "id": "ID",
        "n": "N°",
        "data_mov": "Data",
        "nome": "Nome",
        "empresa": "Empresa",
        "cpf_fmt": "CPF",
        "env_txt": "Env.",
        "fat_txt": "Fat.",
        "prazo_7d": "Prazo 7d",
        "sit": "Situação",
    }
    cols_ordem = [
        "id",
        "n",
        "data_mov",
        "nome",
        "empresa",
        "cpf_fmt",
        "env_txt",
        "fat_txt",
        "prazo_7d",
        "sit",
    ]
    df_view = raw[cols_ordem].rename(columns=cab)

    pend = raw["enviado"].map(lambda x: not _bool_enviado_faturado(x))

    def _cores_linha(row: pd.Series):
        i = row.name
        n = len(row)
        if pend.iloc[int(i)]:
            return ["background-color: #fde8e8"] * n
        return [""] * n

    try:
        return df_view.style.apply(_cores_linha, axis=1)
    except Exception:
        return df_view


_orig_id = st.session_state.get("toxic_origem_recepcao_id")
_orig_nome = st.session_state.get("toxic_origem_recepcao_nome")

if _orig_id is not None:
    nome_txt = (_orig_nome or "").strip()
    bloco = f"**#{_orig_id}**"
    if nome_txt:
        bloco += f" — {nome_txt}"
    st.success(
        f"Veio da **Recepção**: registo de recepção {bloco}. "
        "Pode gravar novo toxicológico ligado a esse ID (se a coluna existir na base)."
    )
    if st.button("Limpar esta indicação", key="toxic_limpar_origem"):
        st.session_state.pop("toxic_origem_recepcao_id", None)
        st.session_state.pop("toxic_origem_recepcao_nome", None)
        st.rerun()

st.divider()
st.subheader("Cadastro")

with st.form("form_toxic", clear_on_submit=False):
    c1, c2, c3 = st.columns([1.2, 2.2, 2.2])
    with c1:
        d_coleta = st.date_input(
            "Data coleta",
            value=date.today(),
            format="DD/MM/YYYY",
            key="toxic_data_coleta",
        )
    with c2:
        nome_col = st.text_input("Nome colaborador", key="toxic_nome")
    with c3:
        cpf_in = st.text_input("CPF", placeholder="Somente números", key="toxic_cpf")

    c4, c5, c6 = st.columns([2.2, 1.2, 1.2])
    with c4:
        empresa_in = st.text_input("Empresa", key="toxic_empresa")
    with c5:
        env_in = st.selectbox("Enviado", SIM_NAO, index=0, key="toxic_env")
    with c6:
        fat_in = st.selectbox("Faturado", SIM_NAO, index=0, key="toxic_fat")

    salvar = st.form_submit_button("Salvar", type="primary")

if salvar:
    if not (nome_col or "").strip():
        st.warning("Preencha o **nome** do colaborador.")
    else:
        cpf_ok = _digits_cpf(cpf_in, 11) or None
        env_b = SIM_NAO.index(env_in) == 1
        fat_b = SIM_NAO.index(fat_in) == 1
        ts = datetime.combine(d_coleta, datetime.now().time())
        mes_v = int(d_coleta.month)
        ano_v = int(d_coleta.year)
        rec_id = st.session_state.get("toxic_origem_recepcao_id")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if INSERT_COM_RECEPCAO_ID:
                        cur.execute(
                            SQL_INSERT,
                            (
                                d_coleta,
                                ts,
                                nome_col.strip(),
                                cpf_ok,
                                empresa_in.strip(),
                                env_b,
                                fat_b,
                                mes_v,
                                ano_v,
                                rec_id,
                            ),
                        )
                    else:
                        cur.execute(
                            SQL_INSERT,
                            (
                                d_coleta,
                                ts,
                                nome_col.strip(),
                                cpf_ok,
                                empresa_in.strip(),
                                env_b,
                                fat_b,
                                mes_v,
                                ano_v,
                            ),
                        )
                conn.commit()
            st.session_state["toxic_recarregar_lista"] = True
            st.success("Registo toxicológico gravado.")
        except Exception as e:
            st.error(
                "Não foi possível gravar. No **Supabase → toxic**, confirme colunas "
                "(`data_coleta`, `data_coleta_ts`, `nome_colaborador`, `cpf`, `empresa`, "
                "`enviado`, `cobrado`, `mes`, `ano`). Ajuste **toxic_config.py** se necessário."
            )
            st.exception(e)

st.divider()
st.subheader("Registos do mês")

f1, f2, f3, f4 = st.columns([1.5, 1.2, 1.2, 2])
with f1:
    mes_idx = st.selectbox(
        "Mês",
        range(12),
        format_func=lambda i: MESES[i],
        index=date.today().month - 1,
        key="toxic_mes",
    )
with f2:
    ano_ref = st.number_input(
        "Ano",
        min_value=2000,
        max_value=2100,
        value=date.today().year,
        key="toxic_ano",
    )
with f3:
    auto_lista = st.checkbox(
        "Carregar ao abrir",
        value=False,
        key="toxic_auto_lista",
    )
with f4:
    btn_filtro = st.button("Filtrar / atualizar", type="primary", key="toxic_filtrar")

ref_mes = date(int(ano_ref), int(mes_idx) + 1, 1)
_rec = st.session_state.pop("toxic_recarregar_lista", False)
executar = btn_filtro or auto_lista or _rec

if executar:
    try:
        with st.spinner("A consultar a base…"):
            with get_connection() as conn:
                df = pd.read_sql(SQL_LISTA_MES, conn, params=[ref_mes, ref_mes])
        if df.empty:
            st.session_state.pop("toxic_lista_df", None)
            st.info("Sem registos toxicológicos neste mês.")
        else:
            st.session_state["toxic_lista_df"] = df.copy()
            npend = _pendentes_nao_enviados(df)
            if npend > 0:
                st.warning(f"**{npend}** pendente(s) não enviado(s).")
            st.dataframe(
                _dataframe_toxic_destaque(df),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Fundo rosado = ainda **não enviado**. **Situação:** «7d» dentro do prazo de 7 dias, "
                "**Atrasado** após o prazo, **Enviado** quando **Env.** = Sim."
            )

            st.subheader("Alterar enviado / faturado")
            st.caption(
                "**Faturado** na grelha corresponde à coluna **`cobrado`** na base de dados."
            )
            lista_ed = st.session_state["toxic_lista_df"]
            ids_ed = [int(x) for x in lista_ed["id"].tolist()]
            sel_ed = st.selectbox(
                "Escolha o registo",
                options=ids_ed,
                format_func=lambda i: _etiqueta_registo_toxic(lista_ed, i),
                key="toxic_edit_sel",
            )
            row_ed = lista_ed.loc[lista_ed["id"] == sel_ed].iloc[0]
            idx_env = 1 if _bool_enviado_faturado(row_ed.get("enviado")) else 0
            idx_fat = 1 if _bool_enviado_faturado(row_ed.get("faturado")) else 0

            ek = f"_{int(sel_ed)}"
            with st.form("form_toxic_editar_flags"):
                e1, e2 = st.columns(2)
                with e1:
                    env_ed = st.selectbox(
                        "Enviado",
                        SIM_NAO,
                        index=idx_env,
                        key=f"toxic_edit_env{ek}",
                    )
                with e2:
                    fat_ed = st.selectbox(
                        "Faturado (cobrado)",
                        SIM_NAO,
                        index=idx_fat,
                        key=f"toxic_edit_fat{ek}",
                    )
                guardar_flags = st.form_submit_button(
                    "Guardar envio / faturação", type="primary"
                )

                if guardar_flags:
                    env_b = SIM_NAO.index(env_ed) == 1
                    cob_b = SIM_NAO.index(fat_ed) == 1
                    try:
                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    SQL_UPDATE_ENVIO_COBRADO,
                                    (env_b, cob_b, int(sel_ed)),
                                )
                            conn.commit()
                        st.success("Estado actualizado.")
                        st.session_state["toxic_recarregar_lista"] = True
                        st.rerun()
                    except Exception as e:
                        st.error("Não foi possível actualizar o registo.")
                        st.exception(e)
    except Exception as e:
        st.error(
            "Não foi possível carregar a lista. Verifique **public.toxic** e **toxic_config.py** "
            "(ex.: coluna `data_coleta` vs `data_ts`, `empresa` vs `empresa_id`)."
        )
        st.exception(e)
else:
    st.caption("Escolha **mês** e **ano** e clique em **Filtrar / atualizar** (ou marque **Carregar ao abrir**).")
