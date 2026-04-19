"""
Tabela `public.lancamentos` — movimentos de caixa (Entrada / Saída).

Ajuste os literais de `tipo` se o desktop gravar variantes (ex.: «Saida» vs «Saída»).
"""

from __future__ import annotations

SCHEMA = "public"
TABELA = "lancamentos"

COL_ID = "id"
COL_DATA_TXT = "data"
COL_DATA_TS = "data_ts"
COL_TIPO = "tipo"
COL_VALOR = "valor"
COL_VALOR_NUM = "valor_num"
COL_DESCRICAO = "descricao"
COL_MES = "mes"
COL_ANO = "ano"
COL_EMPRESA_ID = "empresa_id"

# Valores de `tipo` observados no Supabase / desktop
TIPO_ENTRADA = "Entrada"
TIPO_SAIDA = "Saida"


def _fq_table() -> str:
    return f"{SCHEMA}.{TABELA}"


def build_insert_sql() -> str:
    cols = [
        COL_DATA_TXT,
        COL_DATA_TS,
        COL_TIPO,
        COL_VALOR,
        COL_VALOR_NUM,
        COL_DESCRICAO,
        COL_MES,
        COL_ANO,
        COL_EMPRESA_ID,
    ]
    ph = ",".join(["%s"] * len(cols))
    return f"INSERT INTO {_fq_table()} ({','.join(cols)}) VALUES ({ph})"


def build_lista_sql() -> str:
    """Todos os lançamentos do mesmo mês/ano que a data de referência (%s)."""
    t = _fq_table()
    return f"""
SELECT
    {COL_ID},
    ROW_NUMBER() OVER (ORDER BY {COL_ID} DESC)::integer AS n,
    COALESCE(
        NULLIF(trim({COL_DATA_TXT}::text), ''),
        to_char({COL_DATA_TS}, 'DD/MM/YYYY')
    ) AS data_mov,
    to_char({COL_DATA_TS}, 'HH24:MI') AS hora,
    {COL_TIPO} AS tipo,
    COALESCE({COL_VALOR_NUM}, {COL_VALOR}::numeric) AS valor,
    {COL_DESCRICAO} AS descricao,
    {COL_EMPRESA_ID} AS empresa_id
FROM {t}
WHERE EXTRACT(YEAR FROM ({COL_DATA_TS})::timestamp)::int
      = EXTRACT(YEAR FROM %s::date)::int
  AND EXTRACT(MONTH FROM ({COL_DATA_TS})::timestamp)::int
      = EXTRACT(MONTH FROM %s::date)::int
ORDER BY {COL_DATA_TS} DESC, {COL_ID} DESC
LIMIT 10000
"""


SQL_INSERT = build_insert_sql()
SQL_LISTA_MES = build_lista_sql()
# Nome antigo (lista já era por dia — mantém alias para não partir imports externos)
SQL_LISTA_DIA = SQL_LISTA_MES
