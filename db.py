"""Ligação ao PostgreSQL (Supabase). Sem senhas no código-fonte."""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import quote_plus, urlparse

import psycopg2
import streamlit as st


def _norm(s: object) -> str:
    return str(s or "").strip()


def _is_placeholder_host(host: str) -> bool:
    h = host.lower()
    if not h:
        return True
    return "xxxxx" in h or "your-" in h or "abcdef" in h


def _is_placeholder_password(pw: str) -> bool:
    p = pw.lower()
    if not pw.strip():
        return True
    return "coloque" in p or "xxxx" in p or p.startswith("sua_senha")


def _is_placeholder_url(url: str) -> bool:
    if not url:
        return True
    u = url.lower()
    return (
        "xxxxx" in u
        or "[your-password]" in u
        or ":senha@" in u
        or "senha@" in u
        or "user:sua" in u
    )


def _url_from_parts() -> str | None:
    host = _norm(st.secrets.get("DB_HOST", ""))
    password = _norm(st.secrets.get("DB_PASS", ""))
    if not host or not password:
        return None
    if _is_placeholder_host(host):
        raise ValueError(
            'O **DB_HOST** ainda tem texto de exemplo (ex.: **xxxxx**). '
            "Abra o Supabase → **Connect** ou **Settings → Database**, copie o host real "
            "(formato `db.SEU_ID.supabase.co`) e grave `.streamlit/secrets.toml`."
        )
    if _is_placeholder_password(password):
        raise ValueError(
            "A **DB_PASS** ainda está vazia ou é texto de exemplo. "
            "Use a **senha da base PostgreSQL** (utilizador `postgres`), "
            "definida em **Project Settings → Database** no Supabase."
        )
    user = quote_plus(_norm(st.secrets.get("DB_USER", "postgres")))
    pw = quote_plus(password)
    port = _norm(st.secrets.get("DB_PORT", "5432"))
    dbn = _norm(st.secrets.get("DB_NAME", "postgres"))
    sslmode = _norm(st.secrets.get("DB_SSLMODE", "require"))
    return f"postgresql://{user}:{pw}@{host}:{port}/{dbn}?sslmode={sslmode}"


def get_db_url() -> str:
    """Ordem: variável de ambiente (testes) → DB_URL → campos DB_HOST/DB_PASS."""
    env_url = _norm(os.getenv("APTUS_DATABASE_URL") or os.getenv("DATABASE_URL"))
    if env_url and not _is_placeholder_url(env_url):
        return env_url

    url = _norm(st.secrets.get("DB_URL", "")) if hasattr(st, "secrets") else ""
    if url and not _is_placeholder_url(url):
        return url

    built = _url_from_parts()
    if built:
        return built

    raise KeyError(
        "Defina **DB_URL** ou **DB_HOST** + **DB_PASS** em `.streamlit/secrets.toml` "
        "(valores reais do Supabase, não o texto de exemplo)."
    )


def _connect_timeout_sec() -> int:
    try:
        if hasattr(st, "secrets") and "PG_CONNECT_TIMEOUT" in st.secrets:
            return int(_norm(st.secrets["PG_CONNECT_TIMEOUT"]))
    except (TypeError, ValueError):
        pass
    try:
        return int(os.getenv("PGCONNECT_TIMEOUT", "30"))
    except ValueError:
        return 30


@contextmanager
def get_connection():
    # Timeout em rede lenta; keepalives ajudam em ligações instáveis.
    conn = psycopg2.connect(
        get_db_url(),
        connect_timeout=_connect_timeout_sec(),
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    try:
        yield conn
    finally:
        conn.close()


def test_connection() -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)


def preview_host_masked() -> str:
    """Para diagnóstico na UI — nunca mostra senha nem chama get_db_url()."""
    try:
        h = _norm(st.secrets.get("DB_HOST", ""))
        if h:
            return h[:4] + "…" + h[-12:] if len(h) > 16 else h[:3] + "***"
        raw = _norm(st.secrets.get("DB_URL", ""))
        if raw:
            host = urlparse(raw).hostname or ""
            if host:
                return host[:4] + "…" + host[-12:] if len(host) > 16 else host[:3] + "***"
        return "(vazio — preencha DB_URL ou DB_HOST)"
    except Exception:
        return "(indisponível)"
