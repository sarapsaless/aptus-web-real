import json
import os
import threading
import time
from datetime import datetime

import psycopg2
from psycopg2 import pool

# --- CONFIGURACOES SUPABASE ---
DB_HOST = "db.aybymdvowpjtpbkmdmjn.supabase.co"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "Eng_bol_hulk_afo2026"
DB_PORT = "5432"
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "20"))

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_OFFLINE_QUEUE_FILE = os.path.join(_BASE_DIR, "offline_queue.json")
_AUDIT_LOG_FILE = os.path.join(_BASE_DIR, "audit_sync.log")

_pool = None
_pool_lock = threading.Lock()
_queue_lock = threading.Lock()
_sync_lock = threading.Lock()

# Callback opcional: True = conectado, False = sem ligação (após falhas em get_conn)
_conn_ui_cb = None
_ui_showing_offline = False  # True = UI está em modo “sem ligação”


def _audit(msg, level="INFO", caller=None):
    """Auditoria com timestamp em milissegundos e nome da função/contexto opcional."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    linha = f"{ts} [{level}]"
    if caller:
        linha += f" [{caller}]"
    linha += f" {msg}"
    print(linha)
    try:
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def audit_db_failure(caller: str, exc: Exception, extra: str = ""):
    """Regista falha com timestamp exacto e nome da função — diagnóstico de rede/SQL."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, psycopg2.Error):
        pg = getattr(exc, "pgcode", None)
        diag = getattr(exc, "diag", None)
        if pg:
            detail += f" pgcode={pg}"
        if diag and getattr(diag, "message_primary", None):
            detail += f" | {diag.message_primary}"
    if extra:
        detail += f" | {extra}"
    linha = f"{ts} [ERROR] [{caller}] {detail}"
    print(linha)
    try:
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def set_connection_status_callback(cb):
    """Define callback (thread-safe) chamado quando deixa de haver ligação ou quando volta.

    cb(connected: bool) — connected=False após get_conn esgotar tentativas;
    connected=True quando uma ligação volta após período offline.
    """
    global _conn_ui_cb
    _conn_ui_cb = cb


def _emit_conn_ui_state(connected: bool):
    """Notifica UI apenas na transição online↔offline (evita spam)."""
    global _ui_showing_offline
    want_offline = not connected
    if want_offline == _ui_showing_offline:
        return
    _ui_showing_offline = want_offline
    _audit(f"transicao_estado_conexao={'OFFLINE' if want_offline else 'ONLINE'}", "INFO", caller="get_conn")
    if _conn_ui_cb:
        try:
            _conn_ui_cb(connected)
        except Exception:
            pass


def _is_write_statement(sql):
    if not sql:
        return False
    first = sql.strip().split(" ", 1)[0].upper()
    return first in {"INSERT", "UPDATE", "DELETE"}


def _serialize_params(params):
    if params is None:
        return []
    if isinstance(params, (list, tuple)):
        out = []
        for p in params:
            try:
                json.dumps(p)
                out.append(p)
            except Exception:
                out.append(str(p))
        return out
    return [str(params)]


def _load_queue():
    if not os.path.exists(_OFFLINE_QUEUE_FILE):
        return []
    try:
        with open(_OFFLINE_QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_queue(items):
    with open(_OFFLINE_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _enqueue_offline(sql, params):
    item = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sql": sql,
        "params": _serialize_params(params),
    }
    with _queue_lock:
        items = _load_queue()
        items.append(item)
        _save_queue(items)
    _audit(f"Fila offline: 1 operacao adicionada (pendentes={get_offline_queue_count()})", "WARN")


def get_offline_queue_count():
    with _queue_lock:
        return len(_load_queue())

def _criar_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            try:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20,
                    host=DB_HOST,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASS,
                    port=DB_PORT,
                    sslmode=DB_SSLMODE,
                    connect_timeout=DB_CONNECT_TIMEOUT,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                    application_name="APTUS_CLINICA",
                )
                _audit("Conexao com nuvem estabelecida (pool ativo).", caller="_criar_pool")
            except Exception as e:
                audit_db_failure("_criar_pool", e)
                raise e
    return _pool


def _reset_pool():
    """Força recriação do pool em caso de queda de rede/DNS/SSL."""
    global _pool
    with _pool_lock:
        try:
            if _pool is not None:
                _pool.closeall()
        except Exception:
            pass
        _pool = None

def get_conn():
    """Obtém conexão do pool com retries. Notifica UI em falha/recuperação total."""
    for attempt in range(1, 4):
        try:
            conn = _criar_pool().getconn()
            if conn is None or conn.closed:
                _reset_pool()
                continue
            # Força o fuso horário de Porto Velho para os dados aparecerem à noite
            with conn.cursor() as cur:
                cur.execute("SET TIME ZONE 'America/Porto_Velho'")
            _emit_conn_ui_state(True)
            return conn
        except Exception as e:
            _audit(f"tentativa {attempt}/3: {e}", "WARN", caller="get_conn")
            _reset_pool()
            time.sleep(0.6 * attempt)
    _emit_conn_ui_state(False)
    return None

def release_conn(conn):
    if _pool and conn:
        try:
            _pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def sincronizar_pendencias(max_items=200):
    """Tenta enviar pendencias locais para nuvem quando conexao voltar."""
    if not _sync_lock.acquire(blocking=False):
        return 0
    try:
        with _queue_lock:
            pending = _load_queue()
        if not pending:
            return 0

        conn = get_conn()
        if not conn:
            return 0

        enviados = 0
        restantes = pending[:]
        try:
            with conn.cursor() as cur:
                for item in pending[:max_items]:
                    try:
                        cur.execute(item.get("sql") or "", item.get("params") or ())
                        conn.commit()
                        enviados += 1
                        restantes.pop(0)
                    except Exception as e:
                        conn.rollback()
                        audit_db_failure("sincronizar_pendencias", e, extra="item_offline")
                        break
        finally:
            release_conn(conn)

        with _queue_lock:
            _save_queue(restantes)
        if enviados:
            _audit(f"Sincronizacao concluida: {enviados} item(ns) enviados; pendentes={len(restantes)}")
        return enviados
    finally:
        _sync_lock.release()

# --- FUNÇÕES QUE O SISTEMA CHAMA (COM SUPORTE A TODOS OS NOMES) ---

def executar_query(sql, params=None, fetch=True, audit_caller=None, **kwargs):
    """Função principal que aceita argumentos extras para não dar erro.

    audit_caller: nome da função de negócio (ex.: salvar_rec) para audit_sync.log em falhas.
    """
    is_write = _is_write_statement(sql)
    for attempt in range(1, 4):
        conn = get_conn()
        if not conn:
            if not fetch and is_write:
                _enqueue_offline(sql, params)
                return True
            time.sleep(0.5 * attempt)
            continue
        try:
            # Sempre que houver conexao, tenta drenar fila local primeiro
            sincronizar_pendencias()
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                # INSERT/UPDATE/DELETE sem RETURNING não têm linhas
                if fetch:
                    if cur.description is not None:
                        out = cur.fetchall()
                        conn.commit()
                        return out
                    conn.commit()
                    return []
                conn.commit()
                return True
        except psycopg2.OperationalError as e:
            try:
                conn.rollback()
            except Exception:
                pass
            ac = audit_caller or "executar_query"
            _audit(f"OperationalError tentativa {attempt}/3: {e}", "WARN", caller=ac)
            _reset_pool()
            if not fetch and is_write:
                _enqueue_offline(sql, params)
                return True
            time.sleep(0.8 * attempt)
        except psycopg2.Error as e:
            try:
                conn.rollback()
            except Exception:
                pass
            ac = audit_caller or "executar_query"
            audit_db_failure(ac, e, extra="psycopg2")
            return [] if fetch else False
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            ac = audit_caller or "executar_query"
            audit_db_failure(ac, e)
            return [] if fetch else False
        finally:
            release_conn(conn)
    if not fetch and is_write:
        _enqueue_offline(sql, params)
        return True
    return [] if fetch else False

# Criando apelidos (aliases) para o sistema não dar erro de "not defined"
def executa(sql, params=None, fetch=False, audit_caller=None, **kwargs):
    """Aceita o argumento 'fetch' que o seu sistema está enviando."""
    return executar_query(sql, params, fetch=fetch, audit_caller=audit_caller, **kwargs)

def executar(sql, params=None, fetch=True, audit_caller=None, **kwargs):
    """Resolve o erro 'name executar is not defined'."""
    return executar_query(sql, params, fetch=fetch, audit_caller=audit_caller, **kwargs)

# --- OUTRAS FUNÇÕES OBRIGATÓRIAS ---

def inicializar_banco():
    print("🗄️ Verificando tabelas...")
    executar_query("SET TIME ZONE 'America/Porto_Velho'", fetch=False)
    # Garante que as tabelas existam
    executar_query("CREATE TABLE IF NOT EXISTS pacientes (id SERIAL PRIMARY KEY, nome VARCHAR(255), cpf VARCHAR(20) UNIQUE)", fetch=False)
    executar_query("CREATE TABLE IF NOT EXISTS empresas (id SERIAL PRIMARY KEY, nome VARCHAR(255) UNIQUE, ativo BOOLEAN DEFAULT TRUE)", fetch=False)
    executar_query("""
        CREATE TABLE IF NOT EXISTS medicos (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(255) NOT NULL,
            crm VARCHAR(20),
            uf_crm CHAR(2),
            especialidade VARCHAR(120),
            rqe VARCHAR(20),
            ativo BOOLEAN DEFAULT TRUE
        )
    """, fetch=False)
    # Migração: tabelas antigas no Supabase podem ter só id/nome/crm
    for _ddl in (
        "ALTER TABLE medicos ADD COLUMN IF NOT EXISTS uf_crm CHAR(2)",
        "ALTER TABLE medicos ADD COLUMN IF NOT EXISTS especialidade VARCHAR(120)",
        "ALTER TABLE medicos ADD COLUMN IF NOT EXISTS rqe VARCHAR(20)",
        "ALTER TABLE medicos ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE",
    ):
        try:
            executar_query(_ddl, fetch=False)
        except Exception as e:
            print(f"⚠️ ALTER medicos: {e}")
    # Garante empresa padrão
    res = executar_query("SELECT COUNT(*) FROM empresas")
    if res and res[0][0] == 0:
        executar_query("INSERT INTO empresas (nome) VALUES ('AVULSO')", fetch=False)
    # Médicos APTUS — insere ou atualiza CRM/RQE pelo nome (UF RO)
    _medicos_padrao = [
        ("DIANA SAYÚRI B. ONO", "9311", "RO", None),
        ("JESSICA NORIKO B. ONO", "5879", "RO", "3380"),
        ("VICTOR HUGO FINI JUNIOR", "2480", "RO", "1285"),
    ]
    for nome_m, crm_m, uf_m, rqe_m in _medicos_padrao:
        try:
            ex = executar_query(
                "SELECT id FROM medicos WHERE UPPER(TRIM(nome)) = UPPER(TRIM(%s))",
                (nome_m,),
                fetch=True,
            )
            if ex and ex[0][0]:
                executar_query(
                    "UPDATE medicos SET crm=%s, uf_crm=%s, rqe=%s WHERE id=%s",
                    (crm_m, uf_m, rqe_m, ex[0][0]),
                    fetch=False,
                )
            else:
                executar_query(
                    """INSERT INTO medicos (nome, crm, uf_crm, rqe, especialidade)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (nome_m, crm_m, uf_m, rqe_m, "Medicina do Trabalho"),
                    fetch=False,
                )
        except Exception as e:
            print(f"⚠️ médico {nome_m}: {e}")

    try:
        executar_query(
            "DELETE FROM medicos WHERE nome LIKE %s",
            ("Dr(a).%",),
            fetch=False,
        )
    except Exception:
        pass

def inserir_dados_basicos(): pass
def buscar_ou_criar_paciente(n, c=None): return None
def buscar_paciente_por_cpf(c): return None
