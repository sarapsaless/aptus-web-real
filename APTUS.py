"""
Entrada da aplicação Streamlit APTUS.

Executar: streamlit run APTUS.py

Abre diretamente a página **Recepção** — não existe página «Home» separada.
"""

import streamlit as st

st.set_page_config(page_title="APTUS", layout="wide", initial_sidebar_state="expanded")

st.switch_page("pages/1_Recepcao.py")
