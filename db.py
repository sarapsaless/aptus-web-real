"""Ligação ao PostgreSQL (Supabase) usando secrets do Streamlit."""

import streamlit as st
import psycopg2
from contextlib import contextmanager


def get_db_url() -> str:
    if "DB_URL" not in st.secrets:
        raise KeyError(
            "Defina DB_URL em .streamlit/secrets.toml (local) ou em Secrets (Streamlit Cloud)."
        )
    return st.secrets["DB_URL"].strip()


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
