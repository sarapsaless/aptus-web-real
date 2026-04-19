"""

Tabela `public.toxic` — controlo toxicológico.



Esquema observado no Supabase: `data_coleta_ts`, `data_coleta`, `nome_colaborador`,

`empresa`, `cpf`, `enviado`, `cobrado` (não `faturado`), `mes`, `ano`.

"""



from __future__ import annotations



SCHEMA = "public"

TABELA = "toxic"



COL_ID = "id"

# Texto/data da coleta (ex.: DD/MM/YYYY). Mantém-se no INSERT.

COL_REF_DATE = "data_coleta"

# Timestamp principal — filtro mensal e ordenação.

COL_DATA_TS = "data_coleta_ts"

COL_NOME = "nome_colaborador"

COL_CPF = "cpf"

COL_EMPRESA = "empresa"

COL_ENVIADO = "enviado"

# Na base chama-se `cobrado`; na UI mantemos o alias `faturado` na lista.

COL_COBRADO = "cobrado"

COL_MES = "mes"

COL_ANO = "ano"

COL_RECEPCAO_ID = "recepcao_id"



# A tabela pode não ter `recepcao_id`; se o INSERT falhar, ponha False.

INSERT_COM_RECEPCAO_ID = False





def _fq_table() -> str:

    return f"{SCHEMA}.{TABELA}"





def _ts_expr() -> str:

    return f"({COL_DATA_TS})::timestamp"





def build_insert_sql() -> str:

    cols = [

        COL_REF_DATE,

        COL_DATA_TS,

        COL_NOME,

        COL_CPF,

        COL_EMPRESA,

        COL_ENVIADO,

        COL_COBRADO,

        COL_MES,

        COL_ANO,

    ]

    if INSERT_COM_RECEPCAO_ID:

        cols.append(COL_RECEPCAO_ID)

    ph = ",".join(["%s"] * len(cols))

    return f"INSERT INTO {_fq_table()} ({','.join(cols)}) VALUES ({ph})"





def build_lista_sql() -> str:

    """Todos os registos do mês/ano da data de referência (%s, %s)."""

    t = _fq_table()

    ts = _ts_expr()

    return f"""

SELECT

    {COL_ID},

    ROW_NUMBER() OVER (ORDER BY {COL_DATA_TS} DESC, {COL_ID} DESC)::integer AS n,

    to_char({ts}, 'DD/MM/YYYY') AS data_mov,

    {COL_NOME} AS nome,

    {COL_CPF} AS cpf,

    COALESCE(NULLIF(trim({COL_EMPRESA}::text), ''), '') AS empresa,

    {COL_ENVIADO} AS enviado,

    {COL_COBRADO} AS faturado,

    to_char({ts} + interval '7 days', 'DD/MM/YYYY') AS prazo_7d

FROM {t}

WHERE EXTRACT(YEAR FROM {ts})::int = EXTRACT(YEAR FROM %s::date)::int

  AND EXTRACT(MONTH FROM {ts})::int = EXTRACT(MONTH FROM %s::date)::int

ORDER BY {COL_DATA_TS} DESC, {COL_ID} DESC

LIMIT 10000

"""





SQL_LISTA_CUSTOM: str | None = None





def _resolve_lista_sql() -> str:

    if SQL_LISTA_CUSTOM and str(SQL_LISTA_CUSTOM).strip():

        return str(SQL_LISTA_CUSTOM).strip()

    return build_lista_sql()





SQL_INSERT = build_insert_sql()

SQL_LISTA_MES = _resolve_lista_sql()


def build_update_envio_cobrado_sql() -> str:
    """Atualiza apenas enviado + cobrado (na UI: Enviado / Faturado)."""

    return (
        f"UPDATE {_fq_table()} SET {COL_ENVIADO} = %s, {COL_COBRADO} = %s "
        f"WHERE {COL_ID} = %s"
    )


SQL_UPDATE_ENVIO_COBRADO = build_update_envio_cobrado_sql()


def build_relatorio_mes_sql() -> str:
    """Relatório mensal toxicológico (Excel). Status derivado de enviado/cobrado."""

    t = _fq_table()
    ts = _ts_expr()
    return f"""
SELECT
    to_char({ts}, 'DD/MM/YYYY HH24:MI') AS data_hora,
    {COL_NOME} AS nome,
    COALESCE(NULLIF(trim({COL_EMPRESA}::text), ''), '') AS empresa,
    {COL_CPF} AS cpf,
    CASE
        WHEN {COL_ENVIADO} IS TRUE AND {COL_COBRADO} IS TRUE THEN 'COMPLETO'
        WHEN {COL_ENVIADO} IS TRUE THEN 'PARCIAL'
        ELSE 'PENDENTE'
    END AS status_exame,
    {COL_ENVIADO} AS enviado,
    {COL_COBRADO} AS cobrado
FROM {t}
WHERE EXTRACT(YEAR FROM {ts})::int = EXTRACT(YEAR FROM %s::date)::int
  AND EXTRACT(MONTH FROM {ts})::int = EXTRACT(MONTH FROM %s::date)::int
ORDER BY {COL_DATA_TS} ASC, {COL_ID} ASC
"""


SQL_RELATORIO_TOXICO_MES = build_relatorio_mes_sql()

