"""Consultas para a página Histórico (pesquisa paciente/colaborador)."""

from __future__ import annotations

SCHEMA = "public"
REC = "recepcao"
TOX = "toxic"


def sql_historico_recepcao() -> str:
    """Parâmetros: like_nome, like_cpf_digits (use '' para não filtrar por CPF)."""
    return f"""
SELECT
    id,
    to_char(data_ts, 'DD/MM/YYYY HH24:MI') AS quando,
    nome,
    tipo,
    empresa,
    exames,
    COALESCE(valor_num, valor::numeric)::numeric AS valor,
    pagamento,
    telefone,
    cpf,
    COALESCE(NULLIF(trim(status_atendimento::text), ''), 'PENDENTE') AS situacao
FROM {SCHEMA}.{REC}
WHERE (excluido IS DISTINCT FROM TRUE)
  AND (
    nome ILIKE %s
    OR (%s <> '' AND regexp_replace(coalesce(cpf::text, ''), '[^0-9]', '', 'g') LIKE %s)
  )
ORDER BY data_ts DESC
LIMIT 500
"""


def sql_historico_toxic() -> str:
    """Parâmetros: like_nome, flag_digits, like_cpf_digits — mesmo critério que recepção."""
    return f"""
SELECT
    id,
    to_char(data_coleta_ts, 'DD/MM/YYYY HH24:MI') AS quando,
    nome_colaborador AS nome,
    empresa,
    cpf,
    CASE
        WHEN enviado IS TRUE AND cobrado IS TRUE THEN 'COMPLETO'
        WHEN enviado IS TRUE THEN 'PARCIAL'
        ELSE 'PENDENTE'
    END AS situacao,
    enviado,
    cobrado
FROM {SCHEMA}.{TOX}
WHERE (
    nome_colaborador ILIKE %s
    OR (%s <> '' AND regexp_replace(coalesce(cpf::text, ''), '[^0-9]', '', 'g') LIKE %s)
  )
ORDER BY data_coleta_ts DESC
LIMIT 500
"""


SQL_HISTORICO_RECEPCAO = sql_historico_recepcao()
SQL_HISTORICO_TOXIC = sql_historico_toxic()
