"""
Entrada da aplicação Streamlit APTUS.

Executar: streamlit run APTUS.py

Abre diretamente a página **Recepção** — não existe página «Home» separada.
"""

import streamlit as st
from auth_basic import is_authenticated, render_login_form

st.set_page_config(page_title="APTUS", layout="wide", initial_sidebar_state="expanded")

if not is_authenticated():
    render_login_form()
    st.stop()

st.switch_page("pages/1_Recepcao.py")
