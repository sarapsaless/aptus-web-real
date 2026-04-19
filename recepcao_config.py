"""
Tabela `recepcao` — inserções.
Lista: tabela `recepcao` OU vista `v_recepcao_*` (colunas tipo desktop).

No Table Editor o nome da vista pode ser `v_recepcao_lookup`, `v_recepcao_local`, etc.
Se não existir vista no Supabase, mantenha **USAR_VISTA_NA_LISTA = False** (lista pela tabela).
Se der erro «relation does not exist», ou crie a vista ou ponha USAR_VISTA_NA_LISTA = False.
"""

from __future__ import annotations

SCHEMA = "public"
TABELA = "recepcao"

# Lista: False = tabela `recepcao` (funciona sem vista). True = usa VISTA_RECEPCAO no Supabase.
USAR_VISTA_NA_LISTA = False
# Só usado se USAR_VISTA_NA_LISTA = True — nome exacto da vista no Table Editor
VISTA_RECEPCAO = "v_recepcao_lookup"

COL_ID = "id"
COL_DATA_TXT = "data"
COL_DATA_TS = "data_ts"
COL_NOME = "nome"
COL_TIPO = "tipo"
COL_EMPRESA = "empresa"
COL_EXAMES = "exames"
COL_VALOR = "valor"
COL_VALOR_NUM = "valor_num"
COL_PAGAMENTO = "pagamento"
COL_TELEFONE = "telefone"
COL_CPF = "cpf"
COL_EXCLUIDO = "excluido"
COL_PACIENTE_ID = "paciente_id"
COL_EMPRESA_ID = "empresa_id"
COL_STATUS_ATENDIMENTO = "status_atendimento"


def _fq_table() -> str:
    return f"{SCHEMA}.{TABELA}"


def _fq_view() -> str:
    return f"{SCHEMA}.{VISTA_RECEPCAO}"


def build_insert_sql() -> str:
    cols = [
        COL_DATA_TXT,
        COL_DATA_TS,
        COL_NOME,
        COL_TIPO,
        COL_EMPRESA,
        COL_EXAMES,
        COL_VALOR,
        COL_VALOR_NUM,
        COL_PAGAMENTO,
        COL_TELEFONE,
        COL_CPF,
        COL_EXCLUIDO,
        COL_PACIENTE_ID,
        COL_EMPRESA_ID,
        COL_STATUS_ATENDIMENTO,
    ]
    ph = ",".join(["%s"] * len(cols))
    return f"INSERT INTO {_fq_table()} ({','.join(cols)}) VALUES ({ph})"


def build_lista_sql_tabela() -> str:
    """Lista a partir da tabela recepcao (inclui id para ações na web)."""
    t = _fq_table()
    return f"""
SELECT
    {COL_ID},
    ROW_NUMBER() OVER (ORDER BY {COL_ID} DESC)::integer AS n,
    COALESCE(
        NULLIF(trim({COL_DATA_TXT}::text), ''),
        to_char({COL_DATA_TS}, 'DD/MM/YYYY HH24:MI')
    ) AS data_hora,
    {COL_NOME} AS nome,
    {COL_CPF} AS cpf,
    COALESCE(
        NULLIF(trim({COL_STATUS_ATENDIMENTO}::text), ''),
        'PENDENTE'
    ) AS status_atendimento,
    {COL_TIPO} AS tipo,
    {COL_EMPRESA} AS empresa,
    {COL_EXAMES} AS exames,
    COALESCE({COL_VALOR_NUM}, {COL_VALOR}::numeric) AS valor,
    {COL_PAGAMENTO} AS pag,
    {COL_TELEFONE} AS telefone
FROM {t}
WHERE ({COL_DATA_TS})::date = %s::date
  AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)
ORDER BY {COL_ID} DESC
LIMIT 500
"""


def build_lista_sql_vista() -> str:
    """
    Vista v_recepcao_* (data_local, data_hora_local, nome, tipo, empresa, exames).
    Inclui `id` para ações (Editar / Atendido / Toxicológico / Excluir).

    Se na vista também existirem cpf, valor, pagamento, telefone, defina SQL_LISTA_CUSTOM.
    """
    v = _fq_view()
    return f"""
SELECT
    id,
    ROW_NUMBER() OVER (ORDER BY id DESC)::integer AS n,
    to_char(data_hora_local, 'DD/MM/YYYY HH24:MI') AS data_hora,
    nome,
    ''::text AS cpf,
    'PENDENTE'::text AS status_atendimento,
    tipo,
    empresa,
    exames,
    0::numeric AS valor,
    ''::text AS pag,
    ''::text AS telefone
FROM {v}
WHERE data_local = %s::date
ORDER BY id DESC
LIMIT 500
"""


# Se preencher isto, ignora USAR_VISTA_NA_LISTA e build_lista_sql_*.
# Um único %s = data do filtro (date).
SQL_LISTA_CUSTOM: str | None = None


def _resolve_lista_sql() -> str:
    if SQL_LISTA_CUSTOM and str(SQL_LISTA_CUSTOM).strip():
        return str(SQL_LISTA_CUSTOM).strip()
    if USAR_VISTA_NA_LISTA:
        return build_lista_sql_vista()
    return build_lista_sql_tabela()


SQL_INSERT = build_insert_sql()
SQL_LISTA_DIA = _resolve_lista_sql()

# Ações por linha (paridade com menu do desktop)
SQL_SELECT_BY_ID = f"""
SELECT
    {COL_ID},
    {COL_DATA_TXT},
    {COL_DATA_TS},
    {COL_NOME},
    {COL_TIPO},
    {COL_EMPRESA},
    {COL_EXAMES},
    {COL_VALOR},
    {COL_VALOR_NUM},
    {COL_PAGAMENTO},
    {COL_TELEFONE},
    {COL_CPF},
    {COL_STATUS_ATENDIMENTO}
FROM {_fq_table()}
WHERE {COL_ID} = %s
  AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)
"""


def build_update_sql() -> str:
    """Atualiza registo existente (mesmos campos editáveis que o formulário novo)."""
    sets = ", ".join(
        [
            f"{COL_DATA_TXT} = %s",
            f"{COL_DATA_TS} = %s",
            f"{COL_NOME} = %s",
            f"{COL_TIPO} = %s",
            f"{COL_EMPRESA} = %s",
            f"{COL_EXAMES} = %s",
            f"{COL_VALOR} = %s",
            f"{COL_VALOR_NUM} = %s",
            f"{COL_PAGAMENTO} = %s",
            f"{COL_TELEFONE} = %s",
            f"{COL_CPF} = %s",
        ]
    )
    return f"UPDATE {_fq_table()} SET {sets} WHERE {COL_ID} = %s AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)"


SQL_UPDATE_ROW = build_update_sql()

SQL_SET_STATUS = f"""
UPDATE {_fq_table()}
SET {COL_STATUS_ATENDIMENTO} = %s
WHERE {COL_ID} = %s AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)
"""

SQL_SOFT_DELETE = f"""
UPDATE {_fq_table()}
SET {COL_EXCLUIDO} = TRUE
WHERE {COL_ID} = %s AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)
"""


def build_relatorio_recepcao_sql() -> str:
    """Todos os atendimentos do mês (para Excel). Dois placeholders %s = mesmo dia (mês/ano)."""
    t = _fq_table()
    ts = COL_DATA_TS
    return f"""
SELECT
    to_char(({ts})::timestamp, 'DD/MM/YYYY HH24:MI') AS data_hora,
    {COL_NOME} AS nome,
    {COL_TIPO} AS tipo,
    {COL_EMPRESA} AS empresa,
    {COL_EXAMES} AS exames,
    COALESCE({COL_VALOR_NUM}, {COL_VALOR}::numeric)::numeric AS valor,
    {COL_PAGAMENTO} AS pagamento,
    {COL_TELEFONE} AS telefone,
    {COL_CPF} AS cpf
FROM {t}
WHERE EXTRACT(YEAR FROM ({ts})::timestamp)::int = EXTRACT(YEAR FROM %s::date)::int
  AND EXTRACT(MONTH FROM ({ts})::timestamp)::int = EXTRACT(MONTH FROM %s::date)::int
  AND ({COL_EXCLUIDO} IS DISTINCT FROM TRUE)
ORDER BY ({ts})::timestamp ASC, {COL_ID} ASC
"""


SQL_RELATORIO_RECEPCAO_MES = build_relatorio_recepcao_sql()


# Valores de status alinhados ao fluxo típico (ajuste se o desktop usar outros literais)
STATUS_PENDENTE = "PENDENTE"
STATUS_ATENDIDO = "ATENDIDO"
STATUS_TOXICOLOGICO = "TOXICOLOGICO"

SQL_DIAG_COLUNAS = """
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
"""
