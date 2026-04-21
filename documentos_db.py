from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg2 import Binary

from db import get_connection


@dataclass
class PacoteExame:
    id: int | None
    empresa: str
    nome_pacote: str
    servicos_texto: str


def _digits_only(value: str, max_len: int = 11) -> str:
    return "".join(c for c in (value or "") if c.isdigit())[:max_len]


def ensure_documentos_schema() -> None:
    sqls = (
        """
        CREATE TABLE IF NOT EXISTS public.doc_pacotes_exames (
            id BIGSERIAL PRIMARY KEY,
            empresa TEXT NOT NULL,
            nome_pacote TEXT NOT NULL,
            servicos_texto TEXT NOT NULL,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.doc_guias_exames (
            id BIGSERIAL PRIMARY KEY,
            numero_pedido TEXT NOT NULL UNIQUE,
            numero_seq INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            data_pedido DATE,
            paciente_nome TEXT NOT NULL,
            paciente_cpf TEXT,
            empresa TEXT,
            servicos_texto TEXT NOT NULL,
            local_texto TEXT,
            pdf_bytes BYTEA,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_doc_guias_exames_seq_ano ON public.doc_guias_exames (ano, numero_seq DESC)",
        "CREATE INDEX IF NOT EXISTS idx_doc_guias_exames_cpf ON public.doc_guias_exames (paciente_cpf)",
        "CREATE INDEX IF NOT EXISTS idx_doc_guias_exames_nome ON public.doc_guias_exames (paciente_nome)",
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            for sql in sqls:
                cur.execute(sql)
        conn.commit()
    # Evita duplicar pacote ativo (empresa + nome). Pode falhar se já houver duplicados — apague duplicados no Table Editor.
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_pacotes_empresa_nome_ativos
                    ON public.doc_pacotes_exames (
                        lower(trim(empresa)),
                        lower(trim(nome_pacote))
                    )
                    WHERE ativo IS TRUE
                    """
                )
            conn.commit()
    except Exception:
        pass


def listar_pacotes_salvos() -> list[PacoteExame]:
    sql = """
    SELECT id, empresa, nome_pacote, servicos_texto
    FROM public.doc_pacotes_exames
    WHERE ativo IS TRUE
    ORDER BY empresa ASC, nome_pacote ASC
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [
        PacoteExame(int(r[0]), str(r[1] or "").strip(), str(r[2] or "").strip(), str(r[3] or ""))
        for r in rows
    ]


def salvar_pacote_exames(empresa: str, nome_pacote: str, servicos_texto: str) -> str:
    """Insere ou atualiza serviços se já existir pacote ativo com mesma empresa+nome."""
    emp = empresa.strip()
    nom = nome_pacote.strip()
    srv = servicos_texto.strip()
    sql_upd = """
    UPDATE public.doc_pacotes_exames
    SET servicos_texto = %s,
        empresa = %s,
        nome_pacote = %s,
        updated_at = NOW()
    WHERE lower(trim(empresa)) = lower(trim(%s))
      AND lower(trim(nome_pacote)) = lower(trim(%s))
      AND ativo IS TRUE
    """
    sql_ins = """
    INSERT INTO public.doc_pacotes_exames (empresa, nome_pacote, servicos_texto, ativo, updated_at)
    VALUES (%s, %s, %s, TRUE, NOW())
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_upd, (srv, emp, nom, emp, nom))
            if cur.rowcount and cur.rowcount > 0:
                conn.commit()
                return "updated"
            cur.execute(sql_ins, (emp, nom, srv))
        conn.commit()
    return "inserted"


def atualizar_pacote_por_id(
    pacote_id: int,
    empresa: str,
    nome_pacote: str,
    servicos_texto: str,
) -> None:
    """Atualiza linha; falha se outro pacote ativo já usa o mesmo par empresa+nome."""
    emp = empresa.strip()
    nom = nome_pacote.strip()
    srv = servicos_texto.strip()
    sql_clash = """
    SELECT id FROM public.doc_pacotes_exames
    WHERE ativo IS TRUE
      AND id <> %s
      AND lower(trim(empresa)) = lower(trim(%s))
      AND lower(trim(nome_pacote)) = lower(trim(%s))
    LIMIT 1
    """
    sql_upd = """
    UPDATE public.doc_pacotes_exames
    SET empresa = %s,
        nome_pacote = %s,
        servicos_texto = %s,
        updated_at = NOW()
    WHERE id = %s AND ativo IS TRUE
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_clash, (int(pacote_id), emp, nom))
            if cur.fetchone():
                raise ValueError(
                    "Já existe outro pacote ativo com a mesma empresa e nome. "
                    "Altere o nome ou desative o outro."
                )
            cur.execute(sql_upd, (emp, nom, srv, int(pacote_id)))
            if cur.rowcount == 0:
                raise ValueError("Pacote não encontrado ou já foi desativado.")
        conn.commit()


def desativar_pacote(pacote_id: int) -> None:
    sql = """
    UPDATE public.doc_pacotes_exames
    SET ativo = FALSE, updated_at = NOW()
    WHERE id = %s AND ativo IS TRUE
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(pacote_id),))
            if cur.rowcount == 0:
                raise ValueError("Pacote não encontrado ou já estava desativado.")
        conn.commit()


def proximo_numero_pedido(ano: int) -> tuple[str, int]:
    sql = """
    SELECT COALESCE(MAX(numero_seq), 0)
    FROM public.doc_guias_exames
    WHERE ano = %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ano,))
            cur_max = cur.fetchone()
    seq = int(cur_max[0] or 0) + 1
    numero = f"{seq:03d}-{ano}"
    return numero, seq


def salvar_guia_exames(
    *,
    numero_pedido: str,
    numero_seq: int,
    ano: int,
    data_pedido: date | None,
    paciente_nome: str,
    paciente_cpf: str | None,
    empresa: str | None,
    servicos_texto: str,
    local_texto: str | None,
    pdf_bytes: bytes | bytearray | memoryview | None,
) -> None:
    sql = """
    INSERT INTO public.doc_guias_exames (
        numero_pedido, numero_seq, ano, data_pedido, paciente_nome, paciente_cpf,
        empresa, servicos_texto, local_texto, pdf_bytes
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (numero_pedido) DO UPDATE SET
        numero_seq = EXCLUDED.numero_seq,
        ano = EXCLUDED.ano,
        data_pedido = EXCLUDED.data_pedido,
        paciente_nome = EXCLUDED.paciente_nome,
        paciente_cpf = EXCLUDED.paciente_cpf,
        empresa = EXCLUDED.empresa,
        servicos_texto = EXCLUDED.servicos_texto,
        local_texto = EXCLUDED.local_texto,
        pdf_bytes = EXCLUDED.pdf_bytes
    """
    cpf_limpo = _digits_only(paciente_cpf or "", 11) or None
    payload = Binary(bytes(pdf_bytes)) if pdf_bytes else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    numero_pedido.strip(),
                    int(numero_seq),
                    int(ano),
                    data_pedido,
                    paciente_nome.strip(),
                    cpf_limpo,
                    (empresa or "").strip() or None,
                    servicos_texto.strip(),
                    (local_texto or "").strip() or None,
                    payload,
                ),
            )
        conn.commit()


def buscar_pacientes_nuvem(term: str, limite: int = 15) -> list[dict[str, Any]]:
    like = f"%{(term or '').strip()}%"
    sql = """
    WITH candidatos AS (
        SELECT
            TRIM(COALESCE(nome::text, '')) AS nome,
            regexp_replace(COALESCE(cpf::text, ''), '[^0-9]', '', 'g') AS cpf,
            MAX(data_ts) AS data_ref
        FROM public.recepcao
        WHERE (nome ILIKE %s OR cpf::text ILIKE %s)
          AND (excluido IS DISTINCT FROM TRUE)
        GROUP BY 1, 2

        UNION ALL

        SELECT
            TRIM(COALESCE(paciente_nome::text, '')) AS nome,
            regexp_replace(COALESCE(paciente_cpf::text, ''), '[^0-9]', '', 'g') AS cpf,
            MAX(created_at) AS data_ref
        FROM public.doc_guias_exames
        WHERE (paciente_nome ILIKE %s OR paciente_cpf::text ILIKE %s)
        GROUP BY 1, 2
    )
    SELECT nome, cpf, MAX(data_ref) AS data_ref
    FROM candidatos
    WHERE nome <> ''
    GROUP BY nome, cpf
    ORDER BY data_ref DESC NULLS LAST, nome ASC
    LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (like, like, like, like, int(limite)))
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for nome, cpf, _ in rows:
        cpf_txt = _digits_only(str(cpf or ""), 11)
        out.append({"nome": str(nome or "").strip(), "cpf": cpf_txt})
    return out


def listar_guias_recentes(
    limite: int = 30,
    empresa_filtro: str | None = None,
) -> list[dict[str, Any]]:
    filtro = (empresa_filtro or "").strip()
    sql = """
    SELECT id, numero_pedido, paciente_nome, paciente_cpf, empresa, created_at
    FROM public.doc_guias_exames
    WHERE length(trim(coalesce(%s::text, ''))) = 0 OR empresa ILIKE %s
    ORDER BY created_at DESC
    LIMIT %s
    """
    like_val = f"%{filtro}%" if filtro else "%"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (filtro, like_val, int(limite)))
            rows = cur.fetchall()
    return [
        {
            "id": int(r[0]),
            "numero_pedido": str(r[1] or ""),
            "paciente_nome": str(r[2] or ""),
            "paciente_cpf": _digits_only(str(r[3] or ""), 11),
            "empresa": str(r[4] or ""),
            "created_at": r[5],
        }
        for r in rows
    ]


def obter_pdf_guia_por_id(guia_id: int) -> bytes | None:
    sql = "SELECT pdf_bytes FROM public.doc_guias_exames WHERE id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(guia_id),))
            one = cur.fetchone()
    if not one or one[0] is None:
        return None
    return bytes(one[0])
