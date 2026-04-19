"""
Documentos clínicos — médicos na base.

`DISTINCT ON (id)` evita linhas repetidas no dropdown. Se a sua tabela não tiver `id`,
ajuste **SQL_MEDICOS_FALLBACK** ou os nomes das colunas no Table Editor.
"""

from __future__ import annotations

import re
import unicodedata

# Lista principal (ajuste nomes de colunas ao Supabase)
SQL_MEDICOS_ROTULO = """
SELECT DISTINCT ON (id)
    id,
    COALESCE(NULLIF(trim(nome::text), ''), 'Sem nome') AS nome,
    NULLIF(trim(COALESCE(crm::text, '')), '') AS crm,
    NULLIF(trim(COALESCE(uf::text, '')), '') AS uf
FROM public.medicos
ORDER BY id ASC, nome ASC NULLS LAST
LIMIT 500
"""

# Se a query acima falhar (colunas diferentes), tenta só o mínimo.
SQL_MEDICOS_FALLBACK = """
SELECT DISTINCT ON (id)
    id,
    COALESCE(NULLIF(trim(nome::text), ''), 'Sem nome') AS nome,
    NULL::text AS crm,
    NULL::text AS uf
FROM public.medicos
ORDER BY id ASC
LIMIT 500
"""


def _chave_nome_medico(nome: object) -> str:
    """Normaliza nome para deduplicar (maiúsculas, espaços, acentos)."""
    s = "" if nome is None else str(nome)
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s


# CRM/UF usados nos PDFs quando a linha em `public.medicos` vem sem CRM ou sem UF
_CRM_UF_FALLBACK: dict[str, tuple[str, str]] = {
    _chave_nome_medico("DIANA SAYÚRI B. ONO"): ("9311", "RO"),
    _chave_nome_medico("JESSICA NORIKO B. ONO"): ("5879", "RO"),
    _chave_nome_medico("VICTOR HUGO FINI JUNIOR"): ("2480", "RO"),
}


def enriquecer_crm_uf_na_linha(row: dict) -> dict:
    """Preenche CRM e UF a partir do mapa APTUS se vierem vazios na base."""
    out = dict(row)
    nome = out.get("nome")
    crm = str(out.get("crm") or "").strip()
    uf = str(out.get("uf") or "").strip()
    key = _chave_nome_medico(nome)
    fb = _CRM_UF_FALLBACK.get(key)
    if fb:
        if not crm:
            out["crm"] = fb[0]
        if not uf:
            out["uf"] = fb[1]
    return out


def medico_row_com_crm(row: dict | None) -> dict | None:
    """Cópia do médico com CRM/UF garantidos para gerar documento."""
    if not row:
        return row
    return enriquecer_crm_uf_na_linha(row)


def deduplicar_medicos_por_nome(df):
    """
    Um registo por médico no dropdown: a tabela pode ter vários `id` para o mesmo nome.
    Fica a linha com CRM/UF preenchidos; senão a de maior `id`.
    """
    import pandas as pd

    if df is None or df.empty:
        return df
    work = df.copy()
    work["_kn"] = work["nome"].map(_chave_nome_medico)
    crm_s = work["crm"].fillna("").astype(str).str.strip()
    uf_s = work["uf"].fillna("").astype(str).str.strip()
    work["_crm_ok"] = crm_s.ne("").astype(int)
    work["_uf_ok"] = uf_s.ne("").astype(int)
    work["_score"] = work["_crm_ok"] * 2 + work["_uf_ok"]
    id_col = work["id"] if "id" in work.columns else work.index
    work["_idnum"] = pd.to_numeric(id_col, errors="coerce").fillna(0)
    work = work.sort_values(by=["_kn", "_score", "_idnum"], ascending=[True, False, False])
    work = work.drop_duplicates(subset=["_kn"], keep="first")
    work = work.drop(columns=["_kn", "_crm_ok", "_uf_ok", "_score", "_idnum"], errors="ignore")
    return work.sort_values("nome").reset_index(drop=True)


def texto_medico_select(row: dict) -> str:
    nome = row.get("nome") or ""
    crm = row.get("crm") or ""
    uf = row.get("uf") or ""
    if crm:
        suf = f"CRM {crm}" + (f"/{uf}" if uf else "")
        return f"{nome} — {suf}"
    return str(nome)


def rotulos_medicos_unicos(df) -> list[str]:
    """Se o mesmo texto aparecer para mais do que um registo, acrescenta #(id)."""
    from collections import Counter

    brutos = [texto_medico_select(r.to_dict()) for _, r in df.iterrows()]
    freq = Counter(brutos)
    out: list[str] = []
    for i, lab in enumerate(brutos):
        rid = df.iloc[i].get("id")
        if freq[lab] > 1:
            out.append(f"{lab}  (#{rid})")
        else:
            out.append(lab)
    return out


def carregar_medicos_df():
    """Devolve DataFrame ou None se ambas as queries falharem."""
    import pandas as pd

    from db import get_connection

    for sql in (SQL_MEDICOS_ROTULO, SQL_MEDICOS_FALLBACK):
        try:
            with get_connection() as conn:
                df = pd.read_sql(sql, conn)
            if df is None or df.empty:
                continue
            if "id" in df.columns:
                df = df.drop_duplicates(subset=["id"], keep="first")
            else:
                df = df.drop_duplicates(
                    subset=[c for c in ("nome", "crm", "uf") if c in df.columns],
                    keep="first",
                )
            df = deduplicar_medicos_por_nome(df)
            records = [enriquecer_crm_uf_na_linha(r.to_dict()) for _, r in df.iterrows()]
            return pd.DataFrame(records)
        except Exception:
            continue
    return None
