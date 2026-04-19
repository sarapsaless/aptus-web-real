"""Ligação ao PostgreSQL (Supabase) usando apenas Streamlit secrets — sem senhas no código."""

from contextlib import contextmanager
from urllib.parse import quote_plus

import psycopg2
import streamlit as st


def get_db_url() -> str:
    """Lê DB_URL ou monta a partir de DB_HOST, DB_USER, DB_PASS, etc."""
    if "DB_URL" in st.secrets:
        return str(st.secrets["DB_URL"]).strip()

    host = str(st.secrets.get("DB_HOST", "")).strip()
    password = str(st.secrets.get("DB_PASS", "")).strip()
    if not host or not password:
        raise KeyError(
            "Defina DB_URL ou (DB_HOST e DB_PASS) em .streamlit/secrets.toml "
            "ou em Secrets no Streamlit Cloud."
        )
    user = quote_plus(str(st.secrets.get("DB_USER", "postgres")).strip())
    pw = quote_plus(password)
    port = str(st.secrets.get("DB_PORT", "5432")).strip()
    dbn = str(st.secrets.get("DB_NAME", "postgres")).strip()
    sslmode = str(st.secrets.get("DB_SSLMODE", "require")).strip()
    return f"postgresql://{user}:{pw}@{host}:{port}/{dbn}?sslmode={sslmode}"


@contextmanager
def get_connection():
    conn = psycopg2.connect(get_db_url())
    try:
        yield conn
    finally:
        conn.close()


def test_connection() -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)
