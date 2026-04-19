"""Painel opcional para verificar ligação ao PostgreSQL (Supabase)."""

from __future__ import annotations

import streamlit as st


def render_verificar_ligacao_supabase(*, button_key: str = "btn_ligacao_supabase") -> None:
    try:
        from db import get_connection, preview_host_masked, test_connection
    except ImportError as e:
        st.error(
            "Não foi possível carregar `psycopg2`. Na pasta do projeto:\n\n"
            "`pip install -r requirements.txt`"
        )
        st.exception(e)
        return

    st.caption(
        "A ligação à base **não** é testada automaticamente — assim o formulário abre logo, "
        "mesmo com rede lenta ou timeout."
    )

    if st.button("Verificar ligação ao PostgreSQL (Supabase)", key=button_key):
        try:
            with st.spinner("A ligar…"):
                ok = test_connection()
            if ok:
                st.success("Ligação ao PostgreSQL (Supabase) está OK.")
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT version()")
                        row = cur.fetchone()
                        if row:
                            st.info(row[0])
        except KeyError as e:
            st.error(str(e))
            st.markdown(
                "1. Abra **`.streamlit/secrets.toml`**.\n"
                "2. Cole **`DB_URL`** do **pooler** do Supabase se tiver timeout na porta 5432.\n"
                "3. Grave o ficheiro e volte a clicar em **Verificar ligação**."
            )
        except FileNotFoundError:
            st.error(
                "Falta o ficheiro **`.streamlit/secrets.toml`**. Copie `secrets.toml.example`, "
                "renomeie para `secrets.toml` e preencha."
            )
        except ValueError as e:
            st.error(str(e))
            with st.expander("Diagnóstico (sem mostrar senha)"):
                st.code(
                    "Host (mascarado): " + preview_host_masked()
                )
        except Exception as e:
            st.error("Falha ao ligar à base de dados (timeout = rede ou URI errada).")
            st.exception(e)
