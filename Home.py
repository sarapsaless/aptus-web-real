import streamlit as st

from db import get_connection, test_connection

st.set_page_config(page_title="APTUS", layout="wide", initial_sidebar_state="expanded")

st.sidebar.title("APTUS")
st.sidebar.caption("App com dados reais")

st.title("APTUS — arranque")
st.caption("Confirme a ligação ao Supabase antes de acrescentar páginas e consultas.")

try:
    if test_connection():
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
        "1. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`.\n"
        "2. Preencha `DB_URL` com a URI do Supabase (Database → URI).\n"
        "3. Volte a correr: `streamlit run Home.py`"
    )
except Exception as e:
    st.error("Falha ao ligar à base de dados.")
    st.exception(e)
