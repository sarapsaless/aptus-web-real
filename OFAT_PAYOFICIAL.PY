# =============================================================================
# aptus_sistema.py — SISTEMA UNIFICADO APTUS
# Recepção + Caixa + Toxicológico + Relatórios + Documentos (módulos FATURAMENTO/CADASTROS OFAT retirados da UI)
# Banco: PostgreSQL (Supabase) — Relacional Unificado
# =============================================================================

import sys, os, re, threading, traceback, subprocess, tempfile, logging, queue
from datetime import datetime, date, time, timedelta
from decimal import Decimal


def _diretorio_app():
    """Pasta do .exe (PyInstaller) ou da pasta do script — logs, backups e assets."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# ── Verificar e instalar dependências ─────────────────────────────────────────
def _instalar_deps():
    if getattr(sys, "frozen", False):
        return
    deps = {"customtkinter": "customtkinter", "openpyxl": "openpyxl",
            "psycopg2": "psycopg2-binary", "reportlab": "reportlab"}
    for mod, pip in deps.items():
        try:
            __import__(mod)
        except ImportError:
            print(f"📦 Instalando {pip}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip, "-q"])

print("🔧 Verificando dependências...")
_instalar_deps()

# ── Importações ────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import customtkinter as ctk
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

# ── Banco de dados ─────────────────────────────────────────────────────────────
import psycopg2

from db_config import (
    get_conn,
    release_conn,
    sincronizar_pendencias,
    get_offline_queue_count,
    executar_query,
    executa,
    executar,
    inicializar_banco,
    inserir_dados_basicos,
    buscar_ou_criar_paciente,
    buscar_paciente_por_cpf,
    audit_db_failure,
    set_connection_status_callback,
)

# ── Configuração da interface ──────────────────────────────────────────────────
ctk.set_appearance_mode("light")
app = ctk.CTk()
try:
    app.iconbitmap(os.path.join(_diretorio_app(), "assets", "logo_aptus.ico"))
except Exception:
    pass
app.title("APTUS MEDICINA DO TRABALHO")
app.withdraw()
# Maximização/tamanho aplicados ao final de criar_interface() para evitar janela minúscula e “piscar”

# ── Fila thread-safe → Tkinter só pode atualizar a UI na thread principal ─────
# Evita: RuntimeError: main thread is not in main loop (Python 3.12+ / workers)
_gui_queue = queue.Queue()


def _poll_gui_queue():
    try:
        while True:
            fn = _gui_queue.get_nowait()
            try:
                fn()
            except Exception:
                traceback.print_exc()
    except queue.Empty:
        pass
    try:
        app.after(50, _poll_gui_queue)
    except Exception:
        pass


def gui_safe(fn):
    """Agenda execução na thread principal (use em callbacks vindos de threading.Thread)."""
    _gui_queue.put(fn)


def msg_erro_db_amigavel():
    """Quando executa(fetch=False) falha — mensagem única para o utilizador."""
    messagebox.showerror(
        "Ligação à base de dados",
        "Não foi possível concluir a operação no servidor (Supabase).\n\n"
        "Verifique a internet e tente novamente.\n\n"
        "Se o problema continuar, contacte o suporte.",
    )


def executa_com_feedback(sql, params=None, *, audit_caller: str):
    """executa(fetch=False) com messagebox se o servidor devolver falha."""
    ok = executa(sql, params, fetch=False, audit_caller=audit_caller)
    if ok is False:
        msg_erro_db_amigavel()
        return False
    return True


app.after(0, _poll_gui_queue)

# ── Constantes ─────────────────────────────────────────────────────────────────
DADOS_EMPRESA = {
    "nome":     "APTUS MEDICINA E SEGURANÇA DO TRABALHO",
    "nome_curto": "APTUS MEDICINA DO TRABALHO",
    "tagline":  "Saúde Ocupacional e Segurança do Trabalho",
    "endereco": "Avenida Jatuarana nº 5316 – Cohab – Porto Velho/RO",
    "email":    "aptusclinica@hotmail.com",
    "contato":  "(69) 3227-9015 / 98500-0015",
    # Rodapé documentos HTML — 3 linhas (maiúsculas via CSS; fonte 8pt)
    "rodape_l1": "DR. VICTOR HUGO FINI JUNIOR - CRM 2480 RQE 1285",
    "rodape_l2": "Avenida Jatuarana nº 5316 – Cohab – Porto Velho/RO",
    "rodape_l3": "Telefone: (69) 3227-9015 | 98500-0015",
}
MESES_NOMES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
               "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
def _prazo_uteis(data_inicio, n=7):
    """Retorna a data limite adicionando N dias úteis (seg–sex)."""
    from datetime import timedelta
    d = data_inicio if hasattr(data_inicio, "date") else data_inicio
    if hasattr(d, "date"): d = d.date()
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d

def _dias_uteis_restantes(data_inicio):
    """Dias úteis restantes até o prazo de 7 dias úteis. Negativo = vencido."""
    from datetime import date, timedelta
    hoje = date.today()
    prazo = _prazo_uteis(data_inicio)
    if hoje >= prazo:
        # contar dias úteis vencidos (negativo)
        count = 0; d = prazo
        while d < hoje:
            if d.weekday() < 5: count += 1
            d += timedelta(days=1)
        return -count
    count = 0; d = hoje
    while d < prazo:
        d += timedelta(days=1)
        if d.weekday() < 5: count += 1
    return count

TIPOS_ATENDIMENTO = [
    "ADM", "PERIO", "DEM", "MF", "RT",
    "ATES. SAN. FIS.", "CONSULTA", "AV. MEDICA", "PERICIA"
]
FORMAS_PAG_REC  = ["DIN","PIX","DÉBITO","CRÉDITO","BOLETO","PEND"]
FORMAS_PAG_FAT  = ["PIX","DINHEIRO","TRANSFERÊNCIA","BOLETO","CARTÃO","CHEQUE"]

# ── Variáveis globais de estado ────────────────────────────────────────────────
id_em_edicao        = None
id_toxic_em_edicao  = None
ultimo_job_busca    = None
sidebar_visible     = False
_status_job         = None

# ── Cache de colaboradores ─────────────────────────────────────────────────────
_cache_nomes_colaboradores = []
_cache_dados_colaboradores = {}
_cache_ts                  = 0.0   # timestamp do último carregamento

# ── Referências de widgets (preenchidas em criar_interface) ────────────────────
# Recepção
ent_data_r = ent_n_r = cb_t_r = ent_e_r = ent_ex_r = None
ent_v_r = cb_p_r = ent_t_r = ent_cpf_r = btn_salvar = None
scroll_rec = ent_busca_menu = None
# Caixa
scroll_fin = lbl_saldo_caixa = ent_desc_c = ent_val_c = None
# Toxic
ent_data_toxic = ent_nome_toxic = ent_cpf_toxic = ent_empresa_toxic = None
cb_enviado_toxic = cb_cobrado_toxic = btn_salvar_toxic = tree_toxic = None
# Faturamento
tree_atendimentos = cb_empresa_filtro = cb_mes_filtro = lbl_total_empresa = None
# Faturas
tree_faturas = None
_rec_frames  = {}   # {reg_id: frame_widget} — para update in-place
# Exames
tree_exames = None
# Empresas
tree_empresas = None
# Vencimentos
scroll_vencimentos = None
frame_dashboard = None
btn_dashboard = None
# Relatórios
cb_mes_relatorios = None
# Status
lbl_status = None
# Frames das abas
frame_recepcao = frame_caixa = frame_toxic = frame_faturamento = None
frame_faturas = frame_exames = frame_empresas = frame_vencimentos = frame_dashboard = None
frame_relatorios = frame_documentos = None
# Sidebar e área principal
sidebar = area_main = btn_hamburger = None
# Botões do menu
btn_recepcao = btn_caixa = btn_toxic = btn_faturamento = None
btn_faturas = btn_exames = btn_empresas = btn_vencimentos = btn_relatorios = None
btn_documentos = None
# Atendimento OFAT
_ent_nome_atend = _ent_cpf_atend = _cb_modo_atend = _cb_empresa_atend = None
_ent_data_atend = _lbl_total_atend = _lbl_total_geral_atend = None
_frame_resumo_custos = None
_exames_vars_atend = {}
# Documentos clínicos
_ent_nome_doc = _ent_cpf_doc = _cb_medico_doc = None
_medicos_doc_lookup = {}
_var_periodo_doc = None  # matutino | vespertino (Declaração de Comparecimento)

# =============================================================================
# UTILITÁRIOS
# =============================================================================

# ── Logging em arquivo ────────────────────────────────────────────────────────
_log_file = os.path.join(_diretorio_app(), "aptus_errors.log")
logging.basicConfig(
    filename=_log_file,
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)

def log(msg, exc=False):
    """Log no console (debug) e em arquivo se for erro."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if exc:
        logging.error(msg, exc_info=True)
    elif any(w in str(msg).lower() for w in ("erro", "error", "exception", "falha", "traceback")):
        logging.error(msg)

def show_status(msg, timeout=2000):
    global _status_job
    try:
        if lbl_status:
            lbl_status.configure(text=msg)
        if _status_job:
            app.after_cancel(_status_job)
        _status_job = app.after(timeout, lambda: lbl_status.configure(text="") if lbl_status else None)
    except:
        pass

_loading_job  = [None]
_loading_frame = [0]
_SPINNER = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

def _start_loading(msg="Carregando..."):
    """Mostra spinner animado na barra de status e cursor de espera."""
    _loading_frame[0] = 0
    try:
        app.config(cursor="watch")
    except: pass
    def _tick():
        try:
            if lbl_status:
                f = _SPINNER[_loading_frame[0] % len(_SPINNER)]
                lbl_status.configure(text=f"{f} {msg}")
            _loading_frame[0] += 1
            _loading_job[0] = app.after(100, _tick)
        except: pass
    _tick()

def _stop_loading(msg_ok=""):
    """Para o spinner e restaura cursor normal."""
    if _loading_job[0]:
        try: app.after_cancel(_loading_job[0])
        except: pass
        _loading_job[0] = None
    try:
        app.config(cursor="")
    except: pass
    if msg_ok:
        show_status(msg_ok)
    else:
        try:
            if lbl_status: lbl_status.configure(text="")
        except: pass

# ── Máscara de CPF em tempo real ─────────────────────────────────────────────
def _mascara_cpf(event):
    """Formata CPF enquanto digita: 000.000.000-00. Bloqueia letras."""
    if event.keysym in ("BackSpace", "Delete", "Left", "Right", "Tab",
                        "Home", "End", "Escape", "Return"):
        return
    entry = event.widget
    # Posição do cursor antes de reformatar
    pos = entry.index("insert")
    # Extrai só dígitos
    raw = "".join(c for c in entry.get() if c.isdigit())
    if len(raw) > 11:
        raw = raw[:11]
    # Formata
    fmt = ""
    for i, c in enumerate(raw):
        if i == 3 or i == 6:
            fmt += "."
        elif i == 9:
            fmt += "-"
        fmt += c
    entry.delete(0, "end")
    entry.insert(0, fmt)
    # Reposiciona cursor de forma aproximada
    try:
        entry.icursor(min(pos + 1, len(fmt)))
    except:
        pass

def limpar_valor(v):
    if not v:
        return 0.0
    try:
        if isinstance(v, (int, float, Decimal)):
            return float(v)
        return float(re.sub(r'[^\d,.-]', '', str(v)).replace(',', '.') or '0')
    except:
        return 0.0

def extrair_valor_seguro(reg, idx):
    try:
        v = reg[idx] if len(reg) > idx else None
        if v is None or v == '':
            return 0.0
        return float(v) if isinstance(v, (int, float, Decimal)) else limpar_valor(v)
    except:
        return 0.0

def formatar_cpf(cpf):
    if not cpf:
        return ""
    c = re.sub(r'[^\d]', '', str(cpf))
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else cpf

def mes_intervalo(mes, ano):
    s = date(ano, mes, 1)
    e = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return datetime.combine(s, time.min), datetime.combine(e, time.min)

def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s[:len(fmt)], fmt).date()
            except:
                pass
    return None

def _to_date_str(v, fmt="%d/%m/%Y"):
    d = _to_date(v)
    return d.strftime(fmt) if d else str(v or "")

def limpar_nome_arquivo(nome):
    return re.sub(r'[-\s]+', '_', re.sub(r'[<>:"/\\|?*]', '_', nome)).strip('_')

def copy_to_clipboard(text):
    try:
        app.clipboard_clear()
        app.clipboard_append(str(text))
        show_status(f"Copiado: {str(text)[:50]}")
    except:
        pass

def obter_mes_num(nome_mes):
    try:
        return MESES_NOMES.index(nome_mes) + 1
    except:
        return datetime.now().month

# =============================================================================
# EXCEL — ESTILOS
# =============================================================================

class ES:
    HDR  = "1F4E79"; SUB = "5B9BD5"; D1 = "F2F2F2"; D2 = "FFFFFF"
    TOT  = "D9E2F3"; OK  = "C6EFCE"; WRN = "FFEB9C"; ERR = "FFC7CE"
    FH   = Font(name='Calibri', size=14, bold=True, color="FFFFFF")
    SH   = Font(name='Calibri', size=12, bold=True, color="FFFFFF")
    DF   = Font(name='Calibri', size=11)
    TF   = Font(name='Calibri', size=12, bold=True)
    BRD  = Border(left=Side(style='thin'), right=Side(style='thin'),
                  top=Side(style='thin'), bottom=Side(style='thin'))
    CA   = Alignment(horizontal='center', vertical='center')
    LA   = Alignment(horizontal='left',   vertical='center')
    RA   = Alignment(horizontal='right',  vertical='center')

def _fmt(ws, r1, r2, c1, c2, tipo="data"):
    cores = {"header": ES.HDR, "subheader": ES.SUB, "total": ES.TOT,
             "success": ES.OK, "warning": ES.WRN, "error": ES.ERR}
    for r in range(r1, r2+1):
        for c in range(c1, c2+1):
            cell = ws.cell(row=r, column=c)
            cell.border = ES.BRD
            if tipo in cores:
                cell.fill = PatternFill(start_color=cores[tipo], end_color=cores[tipo], fill_type="solid")
                cell.font = ES.FH if tipo == "header" else (ES.SH if tipo == "subheader" else (ES.TF if tipo == "total" else ES.DF))
                cell.alignment = ES.CA
            else:
                cell.fill = PatternFill(start_color=ES.D1 if r%2==0 else ES.D2,
                                        end_color=ES.D1 if r%2==0 else ES.D2, fill_type="solid")
                cell.font = ES.DF
                cell.alignment = ES.RA if isinstance(cell.value, (int, float)) else ES.LA

def _ajustar_colunas(ws):
    for col in range(1, ws.max_column+1):
        ml = max((len(str(ws.cell(r, col).value or "")) for r in range(1, ws.max_row+1)), default=8)
        ws.column_dimensions[get_column_letter(col)].width = min(max(ml+2, 10), 50)

def _titulo(ws, row, txt, c1=1, c2=10):
    ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
    cell = ws.cell(row=row, column=c1)
    cell.value = txt
    cell.fill = PatternFill(start_color=ES.HDR, end_color=ES.HDR, fill_type="solid")
    cell.font = ES.FH; cell.alignment = ES.CA; cell.border = ES.BRD
    return row + 2

def _salvar_abrir(wb, nome):
    caminhos = [
        os.path.join(os.path.expanduser("~"), "Desktop", nome),
        os.path.join(tempfile.gettempdir(), nome),
        os.path.join(os.getcwd(), nome),
    ]
    for c in caminhos:
        try:
            wb.save(c)
            try:
                if os.name == "nt":
                    os.startfile(c)
                else:
                    os.system(f'xdg-open "{c}"')
            except:
                pass
            return c
        except:
            continue
    return None

# =============================================================================
# NAVEGAÇÃO
# =============================================================================

_ABAS = {}

def mostrar_aba(nome):
    global btn_recepcao, btn_caixa, btn_toxic, btn_relatorios, btn_documentos

    for frame in [frame_recepcao, frame_caixa, frame_toxic,
                  frame_relatorios, frame_documentos]:
        try:
            frame.pack_forget()
        except:
            pass

    btns = {
        "recepcao":    btn_recepcao,
        "caixa":       btn_caixa,
        "toxic":       btn_toxic,
        "relatorios":  btn_relatorios,
        "documentos":  btn_documentos,
    }
    for b in btns.values():
        try:
            b.configure(fg_color="#34495E")
        except:
            pass
    try:
        btns[nome].configure(fg_color="#1A5276")
    except:
        pass

    mapa = {
        # Recarrega dados ao trocar de aba sem overlay "Atualizando..." (reduz sensação de “fica sempre a atualizar”).
        "recepcao":    (frame_recepcao,    lambda: atualizar_tabelas(silent=True)),
        "caixa":       (frame_caixa,       lambda: atualizar_tabelas(silent=True)),
        "toxic":       (frame_toxic,       atualizar_tabela_toxic),
        "relatorios":  (frame_relatorios,  lambda: None),
        "documentos":  (frame_documentos,  atualizar_aba_documentos),
    }
    if nome in mapa:
        frame, fn = mapa[nome]
        frame.pack(fill="both", expand=True)
        try:
            fn()
        except Exception as e:
            log(f"Erro ao carregar aba {nome}: {e}")

def toggle_sidebar():
    global sidebar_visible
    if sidebar_visible:
        sidebar.pack_forget()
        sidebar_visible = False
        btn_hamburger.configure(text="☰")
    else:
        sidebar.pack(side="left", fill="y", padx=(0, 8), before=area_main)
        sidebar_visible = True
        btn_hamburger.configure(text="✕")

# =============================================================================
# ABA RECEPÇÃO
# =============================================================================

def salvar_rec():
    global id_em_edicao
    try:
        v = limpar_valor(ent_v_r.get())
        data_str = ent_data_r.get().strip()
        try:
            data_dt = datetime.combine(datetime.strptime(data_str, "%d/%m/%Y").date(), datetime.now().time())
        except ValueError:
            messagebox.showwarning("Data inválida", "Use o formato DD/MM/AAAA.")
            return

        nome = ent_n_r.get().upper().strip()
        if not nome:
            messagebox.showwarning("Aviso", "Digite o nome do paciente!")
            return

        tipo_pag     = cb_p_r.get()
        tipo_cons    = cb_t_r.get()
        empresa_txt  = ent_e_r.get().upper().strip()
        # Verificar se bate com empresa cadastrada (normalização automática)
        emp_cad = executar_query(
            "SELECT nome FROM empresas WHERE UPPER(TRIM(nome))=UPPER(TRIM(%s)) AND ativo=TRUE LIMIT 1",
            (empresa_txt,), fetch=True, audit_caller="salvar_rec")
        if emp_cad:
            empresa_txt = emp_cad[0][0]  # usa o nome exato do cadastro
        exames_txt   = ent_ex_r.get().upper().strip()
        telefone_txt = ent_t_r.get().strip()
        cpf_txt      = ent_cpf_r.get().strip()

        # Buscar/criar paciente e empresa no banco relacional
        paciente_id = buscar_ou_criar_paciente(nome, cpf_txt if cpf_txt else None)
        empresa_id  = None
        if empresa_txt:
            r = executar_query(
                "SELECT id FROM empresas WHERE UPPER(nome)=UPPER(%s)",
                (empresa_txt,), fetch=True, audit_caller="salvar_rec",
            )
            if r:
                empresa_id = r[0][0]
            else:
                r2 = executar_query(
                    "INSERT INTO empresas (nome, ativo) VALUES (%s, TRUE) RETURNING id",
                    (empresa_txt,), fetch=True, audit_caller="salvar_rec",
                )
                empresa_id = r2[0][0] if r2 else None

        if id_em_edicao:
            if not executa_com_feedback(
                """UPDATE recepcao SET data=%s, data_ts=%s, nome=%s, tipo=%s, empresa=%s,
                        exames=%s, valor=%s, valor_num=%s, pagamento=%s, telefone=%s, cpf=%s,
                        paciente_id=%s, empresa_id=%s WHERE id=%s""",
                (f"{data_str} {datetime.now().strftime('%H:%M')}", data_dt, nome, tipo_cons,
                 empresa_txt, exames_txt, v, v, tipo_pag, telefone_txt, cpf_txt,
                 paciente_id, empresa_id, id_em_edicao),
                audit_caller="salvar_rec",
            ):
                return
            id_em_edicao = None
            btn_salvar.configure(text="SALVAR", fg_color="#1A5276")
            show_status("✅ Registro atualizado!")
        else:
            if not executa_com_feedback(
                """INSERT INTO recepcao
                        (data, data_ts, nome, tipo, empresa, exames, valor, valor_num, pagamento,
                         telefone, cpf, status_atendimento, mes, ano, excluido, atendido_visual,
                         paciente_id, empresa_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (f"{data_str} {datetime.now().strftime('%H:%M')}", data_dt, nome, tipo_cons,
                 empresa_txt, exames_txt, v, v, tipo_pag, telefone_txt, cpf_txt,
                 "AGUARDANDO", data_dt.month, data_dt.year, False, False,
                 paciente_id, empresa_id),
                audit_caller="salvar_rec",
            ):
                return
            show_status(f"✅ {nome} adicionado à fila!")

        # Auto-lançamento no caixa se pagamento = DIN
        if tipo_pag and tipo_pag.upper() == "DIN" and v > 0:
            if not executa_com_feedback(
                """INSERT INTO lancamentos (data, data_ts, tipo, valor, valor_num, descricao, mes, ano, paciente_id, empresa_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (data_str, data_dt, "Entrada", v, v, f"DIN: {nome}",
                 data_dt.month, data_dt.year, paciente_id, empresa_id),
                audit_caller="salvar_rec",
            ):
                return

        if not id_em_edicao:
            for w in [ent_n_r, ent_e_r, ent_ex_r, ent_v_r, ent_t_r, ent_cpf_r]:
                w.delete(0, 'end')

        # Se pagamento DIN, atualiza caixa também; senão só recepção
        if tipo_pag and tipo_pag.upper() == "DIN":
            atualizar_tabelas()
        else:
            atualizar_so_recepcao()

    except psycopg2.Error as e:
        audit_db_failure("salvar_rec", e)
        msg_erro_db_amigavel()
        traceback.print_exc()
    except Exception as e:
        audit_db_failure("salvar_rec", e)
        messagebox.showerror(
            "Erro",
            "Não foi possível guardar o registo. Tente novamente.\n\n"
            "Se o problema continuar, anote a hora e contacte o suporte.",
        )
        traceback.print_exc()

def toggle_atendido_visual(reg_id):
    try:
        r = executa("SELECT atendido_visual FROM recepcao WHERE id=%s", (reg_id,), fetch=True)
        if r:
            novo = not (r[0][0] or False)
            executa("UPDATE recepcao SET atendido_visual=%s WHERE id=%s", (novo, reg_id))
            if reg_id in _rec_frames:
                try:
                    _rec_frames[reg_id].configure(fg_color="#D5F5E3" if novo else "white")
                except: pass
            else:
                atualizar_so_recepcao()
            show_status("✅ OK marcado!" if novo else "Desmarcado")
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def acao_selecionada(escolha, registro):
    global id_em_edicao
    try:
        if escolha == "Editar":
            id_em_edicao = registro[0]
            ent_data_r.delete(0, 'end')
            ent_data_r.insert(0, registro[1].strftime("%d/%m/%Y") if isinstance(registro[1], datetime) else (registro[1] or ""))
            ent_n_r.delete(0, 'end');   ent_n_r.insert(0, registro[2] or "")
            cb_t_r.set(registro[3] or "ADM")
            ent_e_r.delete(0, 'end');   ent_e_r.insert(0, registro[4] or "")
            ent_ex_r.delete(0, 'end');  ent_ex_r.insert(0, registro[5] or "")
            ent_v_r.delete(0, 'end');   ent_v_r.insert(0, str(extrair_valor_seguro(registro, 6)))
            cb_p_r.set(registro[7] or "DIN")
            ent_t_r.delete(0, 'end');   ent_t_r.insert(0, registro[8] or "")
            ent_cpf_r.delete(0, 'end'); ent_cpf_r.insert(0, registro[9] or "")
            btn_salvar.configure(text="ATUALIZAR", fg_color="#D4AC0D")
            show_status("✏️ Modo edição")

        elif escolha == "Toxicológico":
            # Navega para aba Toxicológico e pré-preenche os campos com dados da recepção
            mostrar_aba("toxic")
            try:
                app.after(100, lambda: _preencher_toxic_da_recepcao(registro))
            except Exception as ex:
                log(f"Erro ao navegar para Toxic: {ex}")

        elif escolha == "Atendido":
            executa("UPDATE recepcao SET status_atendimento='ATENDIDO', atendido_visual=TRUE WHERE id=%s", (registro[0],))
            # Update in-place: só muda a cor da linha, sem recriar tudo
            reg_id = registro[0]
            if reg_id in _rec_frames:
                try:
                    _rec_frames[reg_id].configure(fg_color="#D5F5E3")
                    # Atualizar botão de ações para verde
                    for w in _rec_frames[reg_id].winfo_children():
                        if isinstance(w, ctk.CTkOptionMenu):
                            w.configure(fg_color="#27AE60")
                except: pass
            else:
                atualizar_so_recepcao()
            show_status("✅ Marcado como Atendido!")

        elif escolha == "Excluir":
            if messagebox.askyesno("Excluir", f"Excluir {registro[2]}?"):
                executa("UPDATE recepcao SET excluido=TRUE WHERE id=%s", (registro[0],))
                # Update in-place: remove só aquela linha da tela
                reg_id = registro[0]
                if reg_id in _rec_frames:
                    try:
                        _rec_frames[reg_id].destroy()
                        del _rec_frames[reg_id]
                    except: pass
                else:
                    atualizar_so_recepcao()
                show_status("🗑️ Excluído!")

    except Exception as e:
        messagebox.showerror("Erro", str(e))

def _preencher_toxic_da_recepcao(registro):
    """Pré-preenche o formulário de Toxicológico com dados da Recepção."""
    try:
        nome    = registro[2] or ""
        cpf     = registro[9] or ""
        empresa = registro[4] or ""
        # Limpar campos e preencher
        if ent_nome_toxic:
            ent_nome_toxic.delete(0, "end")
            ent_nome_toxic.insert(0, nome.upper())
        if ent_cpf_toxic:
            ent_cpf_toxic.delete(0, "end")
            ent_cpf_toxic.insert(0, cpf)
        if ent_empresa_toxic:
            ent_empresa_toxic.delete(0, "end")
            ent_empresa_toxic.insert(0, empresa.upper())
        if ent_data_toxic:
            ent_data_toxic.delete(0, "end")
            ent_data_toxic.insert(0, datetime.now().strftime("%d/%m/%Y"))
        show_status(f"🧪 Toxicológico pré-preenchido para {nome.split()[0] if nome else ''}!")
    except Exception as e:
        log(f"Erro preencher toxic: {e}")

def render_recepcao_list(registros):
    _rec_frames.clear()
    for w in scroll_rec.winfo_children():
        w.destroy()

    if not registros:
        ctk.CTkLabel(scroll_rec, text="Nenhum registro encontrado",
                     font=("Arial", 16, "bold"), text_color="#adb5bd").pack(pady=50)
        return

    # ── Colunas: Nº e AÇÕES fixos, NOME maior, demais expandem igualmente ──────
    # (col_i, título, minsize, weight, anchor)
    COLS = [
        (0, "Nº",        40,  0, "center"),  # fixo
        (1, "DATA/HORA", 120, 1, "w"),       # expande
        (2, "NOME / CPF",220, 3, "w"),       # expande 3x (maior)
        (3, "TIPO",       60, 1, "w"),       # expande
        (4, "EMPRESA",    80, 1, "w"),       # expande
        (5, "EXAMES",     80, 1, "w"),       # expande
        (6, "VALOR",      70, 1, "e"),       # expande
        (7, "PAG.",       60, 1, "w"),       # expande
        (8, "TELEFONE",   90, 1, "w"),       # expande
        (9, "AÇÕES",     155, 0, "center"),  # fixo
    ]

    def _cfg_grid(frame):
        """Configura colunas com weight para usar toda a largura da tela"""
        for col_i, _, minsz, wt, _ in COLS:
            frame.grid_columnconfigure(col_i, minsize=minsz, weight=wt)

    # ── CABEÇALHO ─────────────────────────────────────────────────────────────
    hdr = ctk.CTkFrame(scroll_rec, fg_color="#001F3F", height=44)
    hdr.pack(fill="x", pady=(0, 4), padx=4)
    hdr.pack_propagate(False)
    _cfg_grid(hdr)
    for col_i, titulo, _, _, anc in COLS:
        ctk.CTkLabel(hdr, text=titulo, font=("Arial", 11, "bold"),
                     text_color="white", anchor=anc).grid(
            row=0, column=col_i, sticky="nsew", padx=6, pady=12)

    # ── LINHAS DE DADOS ───────────────────────────────────────────────────────
    for idx, r in enumerate(registros, 1):
        try:
            data_f   = r[1]; nome = r[2] or ""; tipo = r[3] or ""
            empresa  = r[4] or ""; exames = r[5] or ""
            valor    = extrair_valor_seguro(r, 6); pag = r[7] or ""
            telefone = r[8] or ""; cpf = r[9] or ""
            status   = r[10] or ""; excluido = r[11] or False
            atendido = r[12] or False

            dt_str = data_f.strftime("%d/%m/%Y %H:%M") if isinstance(data_f, datetime) else str(data_f or "")

            if atendido or status == "ATENDIDO":
                cor_bg = "#D5F5E3"
            else:
                cor_bg = "white"

            linha = ctk.CTkFrame(scroll_rec, fg_color=cor_bg, height=68)
            linha.pack(fill="x", pady=2, padx=4)
            linha.pack_propagate(False)
            _cfg_grid(linha)
            _rec_frames[r[0]] = linha   # registrar para update in-place

            def trunc(s, n): return (s[:n-2]+"..") if s and len(s)>n else (s or "")

            # col 0 — Nº
            ctk.CTkLabel(linha, text=str(idx), font=("Arial", 11, "bold"),
                         text_color="#2C3E50", anchor="center").grid(
                row=0, column=0, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 1 — DATA/HORA
            ctk.CTkLabel(linha, text=dt_str, font=("Arial", 10), anchor="w").grid(
                row=0, column=1, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 2 — NOME (linha 0) + CPF (linha 1)
            lbl_n = ctk.CTkLabel(linha, text=trunc(nome, 28),
                                  font=("Arial", 11, "bold"), anchor="w")
            lbl_n.grid(row=0, column=2, sticky="sw", padx=4, pady=(8, 0))
            lbl_n.bind("<Double-Button-1>", lambda e, t=nome: copy_to_clipboard(t))

            cpf_txt = f"CPF: {formatar_cpf(cpf)}" if cpf else ""
            lbl_c = ctk.CTkLabel(linha, text=cpf_txt, font=("Arial", 9),
                                  text_color="#666", anchor="w")
            lbl_c.grid(row=1, column=2, sticky="nw", padx=4, pady=(0, 6))
            if cpf:
                lbl_c.bind("<Double-Button-1>", lambda e, t=cpf: copy_to_clipboard(t))

            # col 3 — TIPO
            ctk.CTkLabel(linha, text=trunc(tipo, 10), font=("Arial", 10), anchor="w").grid(
                row=0, column=3, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 4 — EMPRESA
            ctk.CTkLabel(linha, text=trunc(empresa, 17), font=("Arial", 10), anchor="w").grid(
                row=0, column=4, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 5 — EXAMES
            ctk.CTkLabel(linha, text=trunc(exames, 16), font=("Arial", 10), anchor="w").grid(
                row=0, column=5, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 6 — VALOR
            ctk.CTkLabel(linha, text=f"R$ {valor:.2f}", font=("Arial", 10, "bold"),
                         text_color="#27AE60", anchor="e").grid(
                row=0, column=6, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 7 — PAGAMENTO
            ctk.CTkLabel(linha, text=trunc(pag, 10), font=("Arial", 10), anchor="w").grid(
                row=0, column=7, rowspan=2, sticky="nsew", padx=4, pady=4)

            # col 8 — TELEFONE
            tel_txt = telefone if telefone else "—"
            lbl_tel = ctk.CTkLabel(linha, text=tel_txt, font=("Arial", 10),
                                   text_color="#1A5276" if telefone else "#adb5bd", anchor="w")
            lbl_tel.grid(row=0, column=8, rowspan=2, sticky="nsew", padx=4, pady=4)
            if telefone:
                lbl_tel.bind("<Double-Button-1>", lambda e, t=telefone: copy_to_clipboard(t))

            # col 9 — AÇÕES
            opts = ["Ações", "Editar", "Atendido", "Toxicológico", "Excluir"]
            cor_btn = "#27AE60" if atendido else "#1A5276"
            ctk.CTkOptionMenu(linha, values=opts, width=140, height=32,
                              fg_color=cor_btn,
                              command=lambda v, reg=r: acao_selecionada(
                                  v.replace("✓ ", ""), reg)
                              ).grid(row=0, column=9, rowspan=2, padx=4, pady=4)
        except:
            continue

    show_status(f"{len(registros)} registro(s) encontrado(s)")

# =============================================================================
# ABA CAIXA
# =============================================================================

def lancar_caixa(tipo):
    try:
        v = limpar_valor(ent_val_c.get())
        if v <= 0:
            messagebox.showerror("Erro", "Valor inválido!")
            return
        now = datetime.now()
        desc = ent_desc_c.get().upper()
        tipo_norm = "Entrada" if tipo.upper() in ["ENTRADA", "ENTRADAS"] else "Saída"
        if not executa_com_feedback(
            "INSERT INTO lancamentos (data, data_ts, tipo, valor, valor_num, descricao, mes, ano) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (now.strftime("%d/%m/%Y"), now, tipo_norm, v, v, desc, now.month, now.year),
            audit_caller="lancar_caixa",
        ):
            return
        atualizar_tabelas()
        ent_desc_c.delete(0, 'end'); ent_val_c.delete(0, 'end')
        show_status(f"✅ {tipo_norm} lançada: R$ {v:.2f}")
    except psycopg2.Error as e:
        audit_db_failure("lancar_caixa", e)
        msg_erro_db_amigavel()
        traceback.print_exc()
    except Exception as e:
        audit_db_failure("lancar_caixa", e)
        messagebox.showerror(
            "Caixa",
            "Não foi possível registar o lançamento. Tente novamente.",
        )
        traceback.print_exc()

def excluir_lancamento(lid):
    try:
        if not executa_com_feedback(
            "DELETE FROM lancamentos WHERE id=%s",
            (lid,),
            audit_caller="excluir_lancamento",
        ):
            return
        atualizar_tabelas()
    except psycopg2.Error as e:
        audit_db_failure("excluir_lancamento", e)
        msg_erro_db_amigavel()
    except Exception as e:
        audit_db_failure("excluir_lancamento", e)
        messagebox.showerror(
            "Caixa",
            "Não foi possível eliminar o lançamento. Tente novamente.",
        )

# =============================================================================
# ABA TOXICOLÓGICO
# =============================================================================

def salvar_toxic():
    global id_toxic_em_edicao
    try:
        data_str = ent_data_toxic.get().strip()
        nome     = ent_nome_toxic.get().strip().upper()
        cpf      = ent_cpf_toxic.get().strip()
        empresa  = ent_empresa_toxic.get().strip().upper()
        enviado  = cb_enviado_toxic.get() == "SIM"
        cobrado  = cb_cobrado_toxic.get() == "SIM"

        if not nome:
            messagebox.showwarning("Aviso", "Digite o nome!")
            return

        try:
            data_dt = datetime.strptime(data_str, "%d/%m/%Y")
        except:
            data_dt = datetime.now()
            data_str = data_dt.strftime("%d/%m/%Y")

        # Buscar empresa_id e paciente_id
        empresa_id  = None
        paciente_id = buscar_ou_criar_paciente(nome, cpf if cpf else None)
        if empresa:
            r = executar_query("SELECT id FROM empresas WHERE UPPER(nome)=UPPER(%s)", (empresa,), fetch=True)
            empresa_id = r[0][0] if r else None

        if id_toxic_em_edicao:
            executa("""UPDATE toxic SET data_coleta=%s, data_coleta_ts=%s, nome_colaborador=%s,
                        cpf=%s, empresa=%s, enviado=%s, cobrado=%s, mes=%s, ano=%s,
                        empresa_id=%s, paciente_id=%s WHERE id=%s""",
                    (data_str, data_dt, nome, cpf, empresa, enviado, cobrado,
                     data_dt.month, data_dt.year, empresa_id, paciente_id, id_toxic_em_edicao))
            id_toxic_em_edicao = None
            btn_salvar_toxic.configure(text="💾 SALVAR", fg_color="#27AE60")
            show_status("✅ Registro atualizado!")
        else:
            executa("""INSERT INTO toxic (data_coleta, data_coleta_ts, nome_colaborador, empresa, cpf,
                        enviado, cobrado, mes, ano, empresa_id, paciente_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (data_str, data_dt, nome, empresa, cpf, enviado, cobrado,
                     data_dt.month, data_dt.year, empresa_id, paciente_id))
            show_status("✅ Toxicológico salvo!")

        for w in [ent_nome_toxic, ent_cpf_toxic, ent_empresa_toxic]:
            w.delete(0, 'end')
        cb_enviado_toxic.set("NÃO"); cb_cobrado_toxic.set("NÃO")
        atualizar_tabela_toxic()

    except Exception as e:
        messagebox.showerror("Erro", str(e))

def toggle_checkbox_toxic(item_id, coluna):
    try:
        r = executa("SELECT enviado, cobrado FROM toxic WHERE id=%s", (item_id,), fetch=True)
        if r:
            env, cob = r[0]
            if coluna == "enviado":
                executa("UPDATE toxic SET enviado=%s WHERE id=%s", (not env, item_id))
                show_status("📤 Enviado atualizado!")
            else:
                executa("UPDATE toxic SET cobrado=%s WHERE id=%s", (not cob, item_id))
                show_status("💰 Cobrado atualizado!")
            atualizar_tabela_toxic()
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def on_treeview_click_toxic(event):
    try:
        item = tree_toxic.selection()[0]
        col  = tree_toxic.identify_column(event.x)
        iid  = tree_toxic.item(item)['values'][0]
        if col == "#6":
            toggle_checkbox_toxic(iid, "enviado")
        elif col == "#7":
            toggle_checkbox_toxic(iid, "cobrado")
    except:
        pass

def acao_toxic(escolha, item_id):
    global id_toxic_em_edicao
    try:
        if escolha == "Editar":
            r = executa("SELECT id, data_coleta_ts, data_coleta, nome_colaborador, empresa, cpf, enviado, cobrado FROM toxic WHERE id=%s",
                        (item_id,), fetch=True)
            if r:
                d = r[0]
                id_toxic_em_edicao = d[0]
                ent_data_toxic.delete(0, 'end');    ent_data_toxic.insert(0, d[2] or "")
                ent_nome_toxic.delete(0, 'end');    ent_nome_toxic.insert(0, d[3] or "")
                ent_empresa_toxic.delete(0, 'end'); ent_empresa_toxic.insert(0, d[4] or "")
                ent_cpf_toxic.delete(0, 'end');     ent_cpf_toxic.insert(0, d[5] or "")
                cb_enviado_toxic.set("SIM" if d[6] else "NÃO")
                cb_cobrado_toxic.set("SIM" if d[7] else "NÃO")
                btn_salvar_toxic.configure(text="📝 ATUALIZAR", fg_color="#F39C12")
                show_status("✏️ Modo edição TOXIC")
        elif escolha == "Excluir":
            if messagebox.askyesno("Confirmar", "Excluir este registro?"):
                executa("UPDATE toxic SET excluido=TRUE WHERE id=%s", (item_id,))
                atualizar_tabela_toxic()
                show_status("🗑️ Excluído!")
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def atualizar_tabela_toxic(mes=None, ano=None):
    try:
        if mes is None: mes = datetime.now().month
        if ano is None: ano = datetime.now().year
        s, e = mes_intervalo(mes, ano)
        regs = executa("""SELECT id, data_coleta_ts, data_coleta, nome_colaborador, empresa, cpf, enviado, cobrado
                          FROM toxic WHERE data_coleta_ts>=%s AND data_coleta_ts<%s AND excluido=FALSE
                          ORDER BY data_coleta_ts DESC LIMIT 200""", (s, e), fetch=True) or []
        for item in tree_toxic.get_children():
            tree_toxic.delete(item)
        tree_toxic.tag_configure('completo',  background='#D5F5E3')
        tree_toxic.tag_configure('parcial',   background='#FFF3CD')
        tree_toxic.tag_configure('pendente',  background='#FADBD8')
        tree_toxic.tag_configure('vencido',   background='#F1948A')
        tree_toxic.tag_configure('urgente',   background='#FAD7A0')
        for r in regs:
            env = r[6]; cob = r[7]
            # Calcular prazo 7 dias úteis
            try:
                dt_base = r[1] if r[1] else None
                if dt_base:
                    prazo   = _prazo_uteis(dt_base)
                    dias_r  = _dias_uteis_restantes(dt_base)
                    prazo_s = prazo.strftime("%d/%m/%Y")
                    if not env:
                        if dias_r < 0:
                            dias_s = f"⛔ {abs(dias_r)}d atraso"
                        elif dias_r == 0:
                            dias_s = "⚠️ HOJE"
                        elif dias_r <= 2:
                            dias_s = f"⚠️ {dias_r}d"
                        else:
                            dias_s = f"✅ {dias_r}d"
                    else:
                        dias_s = "✓ Enviado"
                else:
                    prazo_s = "—"; dias_s = "—"
            except:
                prazo_s = "—"; dias_s = "—"; dias_r = 99

            # Tag de cor
            if env and cob:
                tag = 'completo'
            elif env:
                tag = 'parcial'
            elif dias_r < 0:
                tag = 'vencido'
            elif dias_r <= 2:
                tag = 'urgente'
            else:
                tag = 'pendente'

            tree_toxic.insert("", "end", values=(
                r[0], r[2] or "", (r[3] or "")[:28], (r[4] or "")[:22],
                formatar_cpf(r[5]) if r[5] else "",
                "✓" if env else "✗", "✓" if cob else "✗",
                prazo_s, dias_s
            ), tags=(tag,))

        # Atualizar painel de pendentes
        _atualizar_painel_pendentes()
        show_status(f"{len(regs)} registros TOXIC")
    except Exception as e:
        log(f"Erro TOXIC: {e}")


def _marcar_enviado_toxic(toxic_id):
    """Marca um registro toxicológico como enviado e atualiza a tabela."""
    executa("UPDATE toxic SET enviado=TRUE WHERE id=%s", (toxic_id,))
    atualizar_tabela_toxic()
    show_status("✉️ Marcado como ENVIADO!")

def _atualizar_painel_pendentes():
    """Atualiza o contador de pendentes no filtro da aba Toxicológico."""
    try:
        pends = executa("SELECT COUNT(*) FROM toxic WHERE enviado=FALSE AND excluido=FALSE",
                        fetch=True)
        qtd = pends[0][0] if pends else 0
        if hasattr(_atualizar_painel_pendentes, 'lbl_contador'):
            try:
                lbl = _atualizar_painel_pendentes.lbl_contador
                if lbl.winfo_exists():
                    if qtd > 0:
                        lbl.configure(text=f"⚠️ {qtd} pendente(s) não enviado(s)",
                                      text_color="#C0392B")
                    else:
                        lbl.configure(text="✅ Todos enviados", text_color="#27AE60")
            except: pass
    except Exception as e:
        log(f"Erro contador pendentes: {e}")

# =============================================================================
# FETCH RECEPÇÃO + CAIXA (thread)
# =============================================================================

def _fetch_data():
    data = {"lancamentos": [], "totals": (0, 0), "recepcao": []}
    try:
        ano = datetime.now().year; mes = datetime.now().month
        s, e = mes_intervalo(mes, ano)
        lancs = executa("SELECT id, data_ts, tipo, valor_num, descricao FROM lancamentos WHERE data_ts>=%s AND data_ts<%s ORDER BY id DESC LIMIT 60",
                        (s, e), fetch=True) or []
        ent = sum(float(l[3] or 0) for l in lancs if str(l[2] or "").strip().upper() in ["ENTRADA", "ENTRADAS"])
        sai = sum(float(l[3] or 0) for l in lancs if str(l[2] or "").strip().upper() in ["SAIDA", "SAÍDA", "SAIDAS", "SAÍDAS"])
        data["lancamentos"] = lancs; data["totals"] = (ent, sai)

        busca = ent_busca_menu.get().strip() if ent_busca_menu else ""
        if busca:
            recs = executa("""SELECT id, data_ts, nome, tipo, empresa, exames, valor_num, pagamento, telefone, cpf,
                               status_atendimento, excluido, atendido_visual
                               FROM recepcao WHERE (nome ILIKE %s OR empresa ILIKE %s) AND excluido=FALSE
                               ORDER BY data_ts DESC LIMIT 100""",
                           (f"%{busca}%", f"%{busca}%"), fetch=True) or []
        else:
            txt = ent_data_r.get().strip() if ent_data_r else ""
            try:
                td = datetime.strptime(txt, "%d/%m/%Y").date()
            except:
                td = date.today()
            sd = datetime.combine(td, time.min)
            ed = sd + timedelta(days=1)
            recs = executa("""SELECT id, data_ts, nome, tipo, empresa, exames, valor_num, pagamento, telefone, cpf,
                               status_atendimento, excluido, atendido_visual
                               FROM recepcao WHERE data_ts>=%s AND data_ts<%s AND excluido=FALSE
                               ORDER BY id DESC LIMIT 100""", (sd, ed), fetch=True) or []
        data["recepcao"] = recs
    except Exception as e:
        log(f"Erro fetch: {e}")
    return data

def _apply_data(d):
    try:
        for w in scroll_fin.winfo_children():
            w.destroy()
        for l in d.get("lancamentos", []):
            f = ctk.CTkFrame(scroll_fin, fg_color="white", height=38)
            f.pack(fill="x", pady=1, padx=5); f.pack_propagate(False)
            dt = l[1].strftime("%d/%m/%Y") if isinstance(l[1], datetime) else (l[1] or "")
            v  = limpar_valor(l[3])
            cor = "#27AE60" if str(l[2] or "").upper() in ["ENTRADA", "ENTRADAS"] else "#C0392B"
            ctk.CTkLabel(f, text=f"{dt} | {l[2]} | R$ {v:.2f} | {l[4] or ''}",
                         text_color=cor, font=("Arial", 10)).pack(side="left", padx=10, pady=8)
            ctk.CTkButton(f, text="✕", width=28, height=28, fg_color="#C0392B",
                          command=lambda i=l[0]: excluir_lancamento(i)).pack(side="right", padx=5, pady=5)

        ent, sai = d.get("totals", (0, 0))
        saldo = float(ent) - float(sai)
        mes_n = MESES_NOMES[datetime.now().month - 1]
        lbl_saldo_caixa.configure(text=f"Saldo {mes_n}: R$ {saldo:.2f}",
                                  text_color="#2ECC71" if saldo >= 0 else "#E74C3C")
        render_recepcao_list(d.get("recepcao", []))
    except Exception as e:
        log(f"Erro apply_data: {e}")

def atualizar_tabelas(event=None, silent=False):
    """silent=True: atualiza caixa+recepção sem spinner (útil ao mudar de aba)."""

    def _worker():
        if not silent:
            gui_safe(lambda: _start_loading("Atualizando..."))
        data = _fetch_data()

        def _done():
            _stop_loading()
            _apply_data(data)

        gui_safe(_done)
    threading.Thread(target=_worker, daemon=True).start()

def atualizar_so_recepcao():
    """Atualiza APENAS a lista de recepção — sem tocar no caixa."""
    def _worker():
        gui_safe(lambda: _start_loading("Buscando..."))
        data = {}
        try:
            busca = ent_busca_menu.get().strip() if ent_busca_menu else ""
            if busca:
                recs = executa("""SELECT id, data_ts, nome, tipo, empresa, exames, valor_num, pagamento, telefone, cpf,
                                   status_atendimento, excluido, atendido_visual
                                   FROM recepcao WHERE (nome ILIKE %s OR empresa ILIKE %s) AND excluido=FALSE
                                   ORDER BY data_ts DESC LIMIT 100""",
                               (f"%{busca}%", f"%{busca}%"), fetch=True) or []
            else:
                txt = ent_data_r.get().strip() if ent_data_r else ""
                try:
                    td = datetime.strptime(txt, "%d/%m/%Y").date()
                except:
                    td = date.today()
                sd = datetime.combine(td, time.min)
                ed = sd + timedelta(days=1)
                recs = executa("""SELECT id, data_ts, nome, tipo, empresa, exames, valor_num, pagamento, telefone, cpf,
                                   status_atendimento, excluido, atendido_visual
                                   FROM recepcao WHERE data_ts>=%s AND data_ts<%s AND excluido=FALSE
                                   ORDER BY id DESC LIMIT 100""", (sd, ed), fetch=True) or []
            data["recepcao"] = recs
        except Exception as e:
            log(f"Erro fetch recepção: {e}")

        def _done():
            _stop_loading()
            render_recepcao_list(data.get("recepcao", []))

        gui_safe(_done)
    threading.Thread(target=_worker, daemon=True).start()

def debounce_busca(event=None):
    global ultimo_job_busca
    if ultimo_job_busca:
        app.after_cancel(ultimo_job_busca)
    ultimo_job_busca = app.after(500, atualizar_so_recepcao)

# =============================================================================
# ABA FATURAMENTO (OFAT)
# =============================================================================

def atualizar_filtros_fat():
    # Recarregar cache apenas se vazio ou expirado (TTL = 5 min)
    import threading, time as _time
    _agora = _time.time()
    _expirado = (_agora - _cache_ts) > 300  # 5 minutos
    if not _cache_nomes_colaboradores or _expirado:
        threading.Thread(target=carregar_cache_nomes, daemon=True).start()
    try:
        emps = executar_query("SELECT id, nome FROM empresas WHERE ativo=TRUE ORDER BY nome", fetch=True)
        nomes_filtro = ["TODAS"] + [f"{e[1]} (ID:{e[0]})" for e in emps]
        nomes_atend  = [f"{e[1]} (ID:{e[0]})" for e in emps] if emps else ["Nenhuma empresa"]

        # Atualizar filtro da lista de atendimentos
        if cb_empresa_filtro:
            cb_empresa_filtro.configure(values=nomes_filtro)
            if cb_empresa_filtro.get() not in nomes_filtro:
                cb_empresa_filtro.set("TODAS")

        # Atualizar ComboBox de empresa no formulário de novo atendimento
        if _cb_empresa_atend:
            atual = _cb_empresa_atend.get()
            _cb_empresa_atend.configure(values=nomes_atend)
            if atual in nomes_atend:
                _cb_empresa_atend.set(atual)
            elif nomes_atend:
                _cb_empresa_atend.set(nomes_atend[0])

        if cb_mes_filtro:
            cb_mes_filtro.configure(values=MESES_NOMES)
            if not cb_mes_filtro.get() or cb_mes_filtro.get() not in MESES_NOMES:
                cb_mes_filtro.set(MESES_NOMES[datetime.now().month - 1])
    except Exception as e:
        log(f"Erro filtros: {e}")

def excluir_atendimento_selecionado():
    """
    Exclui atendimento em cascata:
    1. exames_atendimento
    2. itens_fatura (se existir) + recalcula fatura
    3. Se fatura ficar vazia, exclui a fatura
    4. atendimentos (registro principal)
    """
    if not tree_atendimentos:
        return
    sel = tree_atendimentos.selection()
    if not sel:
        messagebox.showwarning("Atencao", "Selecione um atendimento para excluir.")
        return

    atend_id = sel[0]
    vals = tree_atendimentos.item(atend_id, "values")
    colaborador = vals[1] if vals and len(vals) > 1 else "?"

    try:
        atend_id_int = int(atend_id)
    except ValueError:
        messagebox.showerror("Erro", "ID invalido: " + str(atend_id))
        return

    # Verificar se este atendimento esta em alguma fatura
    fatura_info = executar_query(
        "SELECT f.id, f.numero_fatura, "
        "(SELECT COUNT(*) FROM itens_fatura WHERE fatura_id=f.id) "
        "FROM itens_fatura it "
        "JOIN faturas f ON it.fatura_id = f.id "
        "WHERE it.atendimento_id = %s LIMIT 1",
        (atend_id_int,), fetch=True
    )

    if fatura_info:
        fatura_id   = fatura_info[0][0]
        fatura_num  = fatura_info[0][1]
        total_itens = int(fatura_info[0][2])
        if total_itens == 1:
            aviso = ("Atendimento de: " + colaborador +
                     "\n\nEste atendimento esta na Fatura " + str(fatura_num) +
                     ".\nA fatura ficara VAZIA e tambem sera excluida.\n\nConfirmar?")
        else:
            aviso = ("Atendimento de: " + colaborador +
                     "\n\nEste atendimento esta na Fatura " + str(fatura_num) +
                     ".\nO valor sera recalculado (" + str(total_itens-1) + " item(s) restante(s)).\n\nConfirmar?")
    else:
        aviso = "Excluir atendimento de:\n\n" + colaborador + "\n\nEsta acao nao pode ser desfeita."

    if not messagebox.askyesno("Confirmar Exclusao", aviso):
        return

    # 1. Excluir exames do atendimento
    executar_query("DELETE FROM exames_atendimento WHERE atendimento_id=%s", (atend_id_int,))

    # 2. Propagar para faturas
    if fatura_info:
        fatura_id   = fatura_info[0][0]
        total_itens = int(fatura_info[0][2])
        executar_query("DELETE FROM itens_fatura WHERE atendimento_id=%s", (atend_id_int,))
        if total_itens == 1:
            # Fatura ficou vazia — excluir
            executar_query("DELETE FROM faturas WHERE id=%s", (fatura_id,))
        else:
            # Recalcular totais da fatura
            executar_query(
                "UPDATE faturas SET "
                "valor_total=(SELECT COALESCE(SUM(valor_atendimento),0) FROM itens_fatura WHERE fatura_id=%s), "
                "quantidade_atendimentos=(SELECT COUNT(*) FROM itens_fatura WHERE fatura_id=%s) "
                "WHERE id=%s",
                (fatura_id, fatura_id, fatura_id)
            )

    # 3. Excluir o atendimento principal
    ok = executar_query("DELETE FROM atendimentos WHERE id=%s", (atend_id_int,))

    if ok:
        messagebox.showinfo("Excluido", "Atendimento de " + colaborador + " excluido com sucesso!")
        atualizar_tabela_atendimentos()
        atualizar_tabela_faturas()
        atualizar_filtros_fat()
    else:
        messagebox.showerror("Erro", "Nao foi possivel excluir. Verifique o terminal.")


def atualizar_tabela_atendimentos():
    """Carrega atendimentos em background para não travar a UI."""
    def _worker():
        try:
            if not tree_atendimentos:
                return
            emp_f = cb_empresa_filtro.get() if cb_empresa_filtro else "TODAS"
            mes_f = cb_mes_filtro.get() if cb_mes_filtro else MESES_NOMES[datetime.now().month - 1]

            where = ["a.status='ATIVO'"]; params = []
            if emp_f != "TODAS":
                eid = int(emp_f.split("ID:")[1].split(")")[0])
                where.append("a.empresa_id=%s"); params.append(eid)
            if mes_f:
                mn  = obter_mes_num(mes_f)
                ano = datetime.now().year
                # Usar intervalo de datas (mais eficiente que EXTRACT — usa índice)
                dt_ini = date(ano, mn, 1)
                dt_fim = date(ano + 1, 1, 1) if mn == 12 else date(ano, mn + 1, 1)
                where.append("a.data_atendimento >= %s AND a.data_atendimento < %s")
                params.extend([dt_ini, dt_fim])

            rows = executar_query(f"""
                SELECT a.id,
                       COALESCE(a.numero_sequencial, a.id) AS seq,
                       a.colaborador,
                       COALESCE(e.nome, '') AS empresa,
                       a.modo,
                       a.data_atendimento,
                       COALESCE(ex_agg.nomes, '') AS exames,
                       COALESCE(ex_agg.total, 0) AS total,
                       a.data_vencimento_aso
                FROM atendimentos a
                LEFT JOIN empresas e ON a.empresa_id = e.id
                LEFT JOIN (
                    SELECT atendimento_id,
                           STRING_AGG(nome_exame, ' | ' ORDER BY nome_exame) AS nomes,
                           SUM(valor_unitario) AS total
                    FROM exames_atendimento
                    GROUP BY atendimento_id
                ) ex_agg ON ex_agg.atendimento_id = a.id
                WHERE {' AND '.join(where)}
                ORDER BY a.data_atendimento DESC, seq ASC
                LIMIT 300
            """, params if params else None, fetch=True)

            gui_safe(lambda r=rows: _apply_atendimentos(r))
        except Exception as e:
            log(f"Erro tabela atendimentos: {e}")

    def _apply_atendimentos(rows):
        try:
            for item in tree_atendimentos.get_children():
                tree_atendimentos.delete(item)
            tree_atendimentos.tag_configure("vencido",  background="#ffebee")
            tree_atendimentos.tag_configure("vencendo", background="#fff3e0")
            tree_atendimentos.tag_configure("normal",   background="white")
            total = 0; hoje = date.today()
            for r in (rows or []):
                vf = float(r[7] or 0); total += vf
                tag = "normal"; venc_txt = ""
                if r[8]:
                    dv = _to_date(r[8])
                    if dv:
                        dias = (dv - hoje).days
                        if dias < 0:
                            tag = "vencido";  venc_txt = f"VENCIDO {abs(dias)}d"
                        elif dias <= 60:
                            tag = "vencendo"; venc_txt = f"Vence {dias}d"
                        else:
                            venc_txt = f"Vence {dias}d"
                ex_txt = (r[6] or "")[:35] + ("..." if r[6] and len(r[6]) > 35 else "")
                tree_atendimentos.insert("", "end", iid=str(r[0]), values=(
                    r[1], (r[2] or "")[:25], (r[3] or "")[:20], r[4],
                    _to_date_str(r[5]), ex_txt, f"R$ {vf:.2f}", venc_txt
                ), tags=(tag,))
            if lbl_total_empresa:
                lbl_total_empresa.configure(text=f"TOTAL: R$ {total:.2f}")
        except Exception as e:
            log(f"Erro apply atendimentos: {e}")

    threading.Thread(target=_worker, daemon=True).start()

def salvar_atendimento_ofat():
    global _exames_vars_atend, _ent_nome_atend, _ent_cpf_atend
    global _cb_modo_atend, _cb_empresa_atend, _ent_data_atend
    try:
        nome = _ent_nome_atend.get().strip() if _ent_nome_atend else ""
        if not nome:
            messagebox.showwarning("Aviso", "Nome do colaborador é obrigatório!")
            return

        emp_txt = _cb_empresa_atend.get() if _cb_empresa_atend else ""
        if not emp_txt or "Nenhuma" in emp_txt:
            messagebox.showwarning("Aviso", "Selecione uma empresa!")
            return

        exames_sel = [(eid, d["nome"], d["valor"])
                      for eid, d in _exames_vars_atend.items() if d["var"].get()]
        if not exames_sel:
            messagebox.showwarning("Aviso", "Selecione pelo menos um exame!")
            return

        try:
            empresa_id = int(emp_txt.split("ID:")[1].split(")")[0])
        except:
            messagebox.showerror("Erro", "Empresa inválida!"); return

        cpf  = _ent_cpf_atend.get().strip() if _ent_cpf_atend else ""
        modo = _cb_modo_atend.get() if _cb_modo_atend else "ADM"
        try:
            data_at = datetime.strptime(_ent_data_atend.get(), "%d/%m/%Y").date()
        except:
            data_at = date.today()

        data_venc = (data_at + timedelta(days=365)) if modo in ("ADM", "PERIO") else None

        # Número sequencial
        r_seq = executar_query("""SELECT COALESCE(MAX(numero_sequencial),0) FROM atendimentos
                                  WHERE empresa_id=%s AND EXTRACT(MONTH FROM data_atendimento)=%s
                                  AND EXTRACT(YEAR FROM data_atendimento)=%s""",
                               (empresa_id, data_at.month, data_at.year), fetch=True)
        num_seq = (r_seq[0][0] if r_seq else 0) + 1

        paciente_id = buscar_ou_criar_paciente(nome, cpf if cpf else None)

        r_at = executar_query("""INSERT INTO atendimentos
                (numero_sequencial, paciente_id, empresa_id, colaborador, cpf_colaborador,
                 modo, data_atendimento, data_vencimento_aso, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ATIVO') RETURNING id""",
                (num_seq, paciente_id, empresa_id, nome, cpf or None,
                 modo, data_at, data_venc), fetch=True)
        if not r_at:
            messagebox.showerror("Erro", "Falha ao salvar atendimento!"); return

        atend_id = r_at[0][0]; total = 0
        for eid, nome_ex, val in exames_sel:
            executar_query("INSERT INTO exames_atendimento (atendimento_id, exame_id, nome_exame, valor_unitario) VALUES (%s,%s,%s,%s)",
                           (atend_id, eid, nome_ex, val))
            total += val

        emp_nome = emp_txt.split(" (ID:")[0]
        msg = (f"✅ Atendimento cadastrado!\n\n"
               f"👤 {nome}\n🏢 {emp_nome}\n📋 {modo} — Nº {num_seq}\n"
               f"🔬 {len(exames_sel)} exame(s) — R$ {total:.2f}")
        if data_venc:
            msg += f"\n📅 Venc. ASO: {data_venc.strftime('%d/%m/%Y')}"
        messagebox.showinfo("✅ Sucesso!", msg)

        # Limpar campos
        if _ent_nome_atend: _ent_nome_atend.delete(0, 'end')
        if _ent_cpf_atend:  _ent_cpf_atend.delete(0, 'end')
        if _ent_data_atend:
            _ent_data_atend.delete(0, 'end')
            _ent_data_atend.insert(0, datetime.now().strftime("%d/%m/%Y"))
        for d in _exames_vars_atend.values():
            d["var"].set(False)
        _atualizar_total_ofat()
        atualizar_tabela_atendimentos()
        atualizar_cards_vencimentos()

    except Exception as e:
        messagebox.showerror("Erro", str(e)); traceback.print_exc()

def _atualizar_total_ofat():
    try:
        count = sum(1 for d in _exames_vars_atend.values() if d["var"].get())
        total = sum(d["valor"] for d in _exames_vars_atend.values() if d["var"].get())
        if _lbl_total_atend:
            _lbl_total_atend.configure(text=f"{count} exame(s) — R$ {total:.2f}")
        if _lbl_total_geral_atend:
            _lbl_total_geral_atend.configure(text=f"Total: R$ {total:.2f}")
        if _frame_resumo_custos:
            for w in _frame_resumo_custos.winfo_children():
                w.destroy()
            sels = [(d["nome"], d["valor"]) for d in _exames_vars_atend.values() if d["var"].get()]
            if not sels:
                ctk.CTkLabel(_frame_resumo_custos, text="Nenhum selecionado",
                             font=("Arial", 10), text_color="#adb5bd").pack(pady=15)
            else:
                for nome, val in sels:
                    row = ctk.CTkFrame(_frame_resumo_custos, fg_color="white", corner_radius=6, height=30)
                    row.pack(fill="x", pady=2, padx=4); row.pack_propagate(False)
                    ctk.CTkLabel(row, text=nome, font=("Arial", 10, "bold"), anchor="w").pack(side="left", padx=8, pady=5)
                    ctk.CTkLabel(row, text=f"R$ {val:.2f}", font=("Arial", 10, "bold"),
                                 text_color="#27ae60").pack(side="right", padx=8)
    except:
        pass


# =============================================================================
# BUSCA DE COLABORADORES POR NOME (Faturamento)
# =============================================================================

def carregar_cache_nomes():
    """Cache de colaboradores — UNION ALL com LIMIT por tabela + DISTINCT ON para dados."""
    global _cache_nomes_colaboradores, _cache_dados_colaboradores, _cache_ts
    try:
        # ── 1. Nomes únicos de todas as tabelas (LIMIT por sub-SELECT) ────────
        r = executar_query("""
            SELECT DISTINCT nome_up
            FROM (
                (SELECT UPPER(TRIM(nome)) AS nome_up
                FROM recepcao
                WHERE nome IS NOT NULL AND TRIM(nome) != ''
                  AND excluido IS NOT TRUE
                ORDER BY nome LIMIT 1200)

                UNION ALL

                (SELECT UPPER(TRIM(nome))
                FROM pacientes
                WHERE nome IS NOT NULL AND TRIM(nome) != ''
                ORDER BY nome LIMIT 800)

                UNION ALL

                (SELECT UPPER(TRIM(colaborador))
                FROM atendimentos
                WHERE colaborador IS NOT NULL AND TRIM(colaborador) != ''
                  AND status != 'EXCLUIDO'
                ORDER BY colaborador LIMIT 1200)

                UNION ALL

                (SELECT UPPER(TRIM(nome_colaborador))
                FROM toxic
                WHERE nome_colaborador IS NOT NULL AND TRIM(nome_colaborador) != ''
                  AND excluido IS NOT TRUE
                ORDER BY nome_colaborador LIMIT 800)
            ) sub
            WHERE nome_up IS NOT NULL AND LENGTH(nome_up) > 1
            ORDER BY nome_up
        """, fetch=True)
        _cache_nomes_colaboradores = [n[0] for n in r if n[0] and len(n[0]) > 1] if r else []

        # ── 2. Último atendimento por colaborador — DISTINCT ON (mais rápido) ─
        dados_fat = executar_query("""
            SELECT UPPER(TRIM(a.colaborador)) AS nome_up,
                   a.data_atendimento,
                   COALESCE(e.nome, '') AS empresa,
                   a.modo,
                   COALESCE(a.cpf_colaborador, p.cpf, '') AS cpf,
                   COALESCE(e.id::TEXT, '') AS empresa_id_txt
            FROM (
                SELECT DISTINCT ON (UPPER(TRIM(colaborador)))
                       id, colaborador, data_atendimento, modo,
                       empresa_id, cpf_colaborador
                FROM atendimentos
                WHERE colaborador IS NOT NULL AND TRIM(colaborador) != ''
                  AND status != 'EXCLUIDO'
                ORDER BY UPPER(TRIM(colaborador)), data_atendimento DESC
                LIMIT 1000
            ) a
            LEFT JOIN empresas e  ON a.empresa_id = e.id
            LEFT JOIN pacientes p ON UPPER(p.nome) = UPPER(a.colaborador)
        """, fetch=True) or []

        _cache_dados_colaboradores = {}
        for row in dados_fat:
            nome_up = row[0]
            if nome_up:
                _cache_dados_colaboradores[nome_up] = {
                    "data":       row[1],
                    "empresa":    row[2],
                    "modo":       row[3],
                    "cpf":        row[4],
                    "empresa_id": row[5],
                }

        # ── 3. Fallback: Recepção — DISTINCT ON nativo do PostgreSQL ──────────
        dados_rec = executar_query("""
            SELECT DISTINCT ON (UPPER(TRIM(nome)))
                   UPPER(TRIM(nome)) AS nome_up,
                   data_ts, empresa, tipo, cpf
            FROM recepcao
            WHERE nome IS NOT NULL AND TRIM(nome) != ''
              AND excluido IS NOT TRUE
            ORDER BY UPPER(TRIM(nome)), data_ts DESC
            LIMIT 1000
        """, fetch=True) or []

        for row in dados_rec:
            nome_up = row[0]
            if nome_up and nome_up not in _cache_dados_colaboradores:
                _cache_dados_colaboradores[nome_up] = {
                    "data":       row[1],
                    "empresa":    row[2] or "",
                    "modo":       row[3] or "",
                    "cpf":        row[4] or "",
                    "empresa_id": "",
                }

        import time as _time
        _cache_ts = _time.time()
        log(f"Cache nomes carregado: {len(_cache_nomes_colaboradores)} colaboradores")
    except Exception as e:
        log(f"Erro cache nomes: {e}")
        _cache_nomes_colaboradores = []
        _cache_dados_colaboradores = {}
    return _cache_nomes_colaboradores


def _enriquecer_sugestoes_nomes(nomes_upper):
    """Monta linhas 'NOME  —  DD/MM/AAAA' quando há data no cache."""
    resultado = []
    for n in nomes_upper:
        dados = _cache_dados_colaboradores.get(n)
        if dados and dados.get("data"):
            try:
                dt = dados["data"]
                data_str = dt.strftime("%d/%m/%Y") if hasattr(dt, "strftime") else str(dt)[:10]
                resultado.append(f"{n}  —  {data_str}")
            except Exception:
                resultado.append(n)
        else:
            resultado.append(n)
    return resultado


def buscar_nomes_colaboradores_sql(texto):
    """Busca rápida no PostgreSQL quando o cache global ainda não carregou (abertura do sistema)."""
    t = (texto or "").strip()
    if len(t) < 2:
        return []
    term = f"%{t}%"
    try:
        r = executar_query(
            """
            SELECT nome_up FROM (
                (SELECT DISTINCT UPPER(TRIM(nome)) AS nome_up
                 FROM recepcao
                 WHERE nome IS NOT NULL AND UPPER(nome) LIKE UPPER(%s)
                   AND excluido IS NOT TRUE LIMIT 35)
                UNION ALL
                (SELECT DISTINCT UPPER(TRIM(nome))
                 FROM pacientes
                 WHERE nome IS NOT NULL AND UPPER(nome) LIKE UPPER(%s) LIMIT 25)
                UNION ALL
                (SELECT DISTINCT UPPER(TRIM(colaborador))
                 FROM atendimentos
                 WHERE colaborador IS NOT NULL AND UPPER(colaborador) LIKE UPPER(%s)
                   AND status != 'EXCLUIDO' LIMIT 35)
                UNION ALL
                (SELECT DISTINCT UPPER(TRIM(nome_colaborador))
                 FROM toxic
                 WHERE nome_colaborador IS NOT NULL AND UPPER(nome_colaborador) LIKE UPPER(%s)
                   AND excluido IS NOT TRUE LIMIT 20)
            ) x
            WHERE nome_up IS NOT NULL AND LENGTH(TRIM(nome_up)) > 1
            ORDER BY nome_up
            LIMIT 28
            """,
            (term, term, term, term),
            fetch=True,
        ) or []
        vistos = set()
        out = []
        for row in r:
            n = row[0]
            if n and n not in vistos:
                vistos.add(n)
                out.append(n)
        return out
    except Exception as e:
        log(f"Erro busca SQL nomes: {e}")
        return []


def buscar_nomes_colaboradores(texto):
    """Filtra nomes do cache — retorna 'NOME  —  DD/MM/AAAA' quando disponível."""
    global _cache_nomes_colaboradores, _cache_dados_colaboradores
    if not texto or len(texto) < 2:
        return []
    t = texto.strip().upper()
    # Cache ainda vazio: não bloqueia a digitação — consulta direta ao banco
    if not _cache_nomes_colaboradores:
        threading.Thread(target=carregar_cache_nomes, daemon=True).start()
        sql_hits = buscar_nomes_colaboradores_sql(texto)
        return _enriquecer_sugestoes_nomes(sql_hits)
    # Busca por prefixo primeiro (mais relevante), depois por substring
    prefixo = [n for n in _cache_nomes_colaboradores if n.startswith(t)][:15]
    substr = [n for n in _cache_nomes_colaboradores if t in n and n not in prefixo][:10]
    nomes = (prefixo + substr)[:25]
    return _enriquecer_sugestoes_nomes(nomes)


def cadastrar_paciente_avulso_se_necessario(nome_upper):
    """Garante nome em pacientes para aparecer nas próximas buscas (CPF opcional depois)."""
    try:
        nu = (nome_upper or "").strip().upper()
        if len(nu) < 2:
            return False
        executar_query(
            """INSERT INTO pacientes (nome, cpf)
               SELECT %s, NULL
               WHERE NOT EXISTS (
                   SELECT 1 FROM pacientes WHERE UPPER(TRIM(nome)) = UPPER(TRIM(%s))
               )""",
            (nu, nu),
            fetch=False,
        )
        return True
    except Exception as e:
        log(f"cadastrar paciente avulso: {e}")
        return False

def buscar_historico_colaborador(nome):
    """Retorna histórico do ANO ATUAL do colaborador"""
    try:
        ano = datetime.now().year
        inicio_ano = datetime(ano, 1, 1)
        fim_ano    = datetime(ano, 12, 31, 23, 59, 59)

        # Atendimentos do ano na recepção
        rec_ano = executar_query("""
            SELECT data_ts, tipo, empresa, exames, valor_num, pagamento
            FROM recepcao
            WHERE UPPER(nome)=UPPER(%s)
              AND data_ts >= %s AND data_ts <= %s
              AND excluido=FALSE
            ORDER BY data_ts DESC
        """, (nome, inicio_ano, fim_ano), fetch=True) or []

        # Atendimentos OFAT do ano
        ofat_ano = executar_query("""
            SELECT a.data_atendimento, a.modo,
                   COALESCE(emp.nome, a.colaborador) as empresa,
                   STRING_AGG(ex.nome_exame, ', '), SUM(ex.valor_unitario)
            FROM atendimentos a
            LEFT JOIN empresas emp ON a.empresa_id=emp.id
            LEFT JOIN exames_atendimento ex ON ex.atendimento_id=a.id
            WHERE UPPER(a.colaborador)=UPPER(%s)
              AND EXTRACT(YEAR FROM a.data_atendimento)=%s
              AND a.status='ATIVO'
            GROUP BY a.id, a.data_atendimento, a.modo, emp.nome, a.colaborador
            ORDER BY a.data_atendimento DESC
        """, (nome, ano), fetch=True) or []

        # CPF do colaborador
        cpf_r = executar_query(
            "SELECT cpf FROM pacientes WHERE UPPER(nome)=UPPER(%s) AND cpf IS NOT NULL LIMIT 1",
            (nome,), fetch=True)
        cpf = cpf_r[0][0] if cpf_r else ""

        return {
            "cpf":      cpf,
            "rec_mes":  rec_ano,
            "ofat_mes": ofat_ano,
            "total_mes": len(rec_ano) + len(ofat_ano),
        }
    except Exception as e:
        log(f"Erro histórico colaborador: {e}")
        return {"cpf": "", "rec_mes": [], "ofat_mes": [], "total_mes": 0}

def editar_empresa():
    """Abre janela para editar empresa selecionada na tree"""
    try:
        if not tree_empresas:
            return
        sel = tree_empresas.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma empresa para editar!"); return
        vals = tree_empresas.item(sel[0])["values"]
        emp_id = vals[0]; emp_nome_atual = vals[1]

        # Buscar dados completos
        r = executar_query(
            "SELECT id, nome, cnpj, responsavel, telefone, email, endereco, ativo FROM empresas WHERE id=%s",
            (emp_id,), fetch=True
        )
        if not r:
            messagebox.showerror("Erro", "Empresa não encontrada!"); return
        d = r[0]

        jan = ctk.CTkToplevel(app)
        jan.title(f"Editar — {emp_nome_atual}"); jan.geometry("520x420")
        jan.transient(app); jan.grab_set()

        hdr = ctk.CTkFrame(jan, fg_color="#fd7e14", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=f"✏️ EDITAR EMPRESA — ID {emp_id}",
                     font=("Arial", 13, "bold"), text_color="white").pack(pady=13)

        main = ctk.CTkScrollableFrame(jan)
        main.pack(fill="both", expand=True, padx=12, pady=10)

        campos = {}
        dados_iniciais = {
            "nome": d[1] or "", "cnpj": d[2] or "", "resp": d[3] or "",
            "tel": d[4] or "", "email": d[5] or "", "end": d[6] or ""
        }
        for label, key, w in [("Nome/Razão Social:", "nome", 280), ("CNPJ:", "cnpj", 160),
                               ("Responsável:", "resp", 230), ("Telefone:", "tel", 160),
                               ("Email:", "email", 230), ("Endereço:", "end", 280)]:
            f = ctk.CTkFrame(main, fg_color="transparent")
            f.pack(fill="x", pady=5)
            ctk.CTkLabel(f, text=label, width=130, font=("Arial", 10, "bold")).pack(side="left", padx=4)
            ent = ctk.CTkEntry(f, width=w)
            ent.insert(0, dados_iniciais[key])
            ent.pack(side="left", padx=4)
            campos[key] = ent



        f_btn = ctk.CTkFrame(jan, fg_color="transparent")
        f_btn.pack(fill="x", padx=12, pady=8)

        def salvar_edicao():
            nome = campos["nome"].get().strip()
            if not nome:
                messagebox.showwarning("Aviso", "Nome é obrigatório!"); return
            executar_query("""UPDATE empresas SET nome=%s, cnpj=%s, responsavel=%s,
                               telefone=%s, email=%s, endereco=%s WHERE id=%s""",
                           (nome, campos["cnpj"].get().strip(), campos["resp"].get().strip(),
                            campos["tel"].get().strip(), campos["email"].get().strip(),
                            campos["end"].get().strip(), emp_id))
            messagebox.showinfo("✅", f"Empresa '{nome}' atualizada!")
            jan.destroy(); atualizar_tabela_empresas(); atualizar_filtros_fat()

        ctk.CTkButton(f_btn, text="💾 SALVAR", fg_color="#fd7e14", font=("Arial", 11, "bold"),
                      width=120, command=salvar_edicao).pack(side="right", padx=4)
        ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545",
                      width=100, command=jan.destroy).pack(side="right", padx=4)

    except Exception as e:
        messagebox.showerror("Erro", str(e))

# =============================================================================
# GERAR FATURA (OFAT)
# =============================================================================

def gerar_fatura_empresa():
    try:
        emp_txt = cb_empresa_filtro.get() if cb_empresa_filtro else "TODAS"
        if emp_txt == "TODAS":
            messagebox.showwarning("Aviso", "Selecione uma empresa específica!"); return
        mes_nome = cb_mes_filtro.get() if cb_mes_filtro else ""
        if not mes_nome:
            messagebox.showwarning("Aviso", "Selecione um mês!"); return

        empresa_id   = int(emp_txt.split("ID:")[1].split(")")[0])
        empresa_nome = emp_txt.split(" (ID:")[0]
        mes_int      = obter_mes_num(mes_nome)
        ano_int      = datetime.now().year

        # ── 1 query com JOIN (evita N queries em loop) ───────────────────────
        dt_ini = date(ano_int, mes_int, 1)
        dt_fim = date(ano_int + 1, 1, 1) if mes_int == 12 else date(ano_int, mes_int + 1, 1)

        rows = executar_query("""
            SELECT a.id, COALESCE(a.numero_sequencial, a.id) AS seq,
                   a.colaborador, a.modo, a.data_atendimento,
                   COALESCE(ex.nome_exame, 'SEM EXAME') AS nome_exame,
                   COALESCE(ex.valor_unitario, 0)        AS valor_unitario
            FROM atendimentos a
            LEFT JOIN exames_atendimento ex ON ex.atendimento_id = a.id
            WHERE a.empresa_id = %s
              AND a.data_atendimento >= %s AND a.data_atendimento < %s
              AND a.status = 'ATIVO'
            ORDER BY seq ASC, ex.nome_exame ASC
        """, (empresa_id, dt_ini, dt_fim), fetch=True)

        if not rows:
            messagebox.showinfo("Aviso", f"Nenhum atendimento para {empresa_nome} em {mes_nome}/{ano_int}!")
            return

        # Agrupar por atendimento
        from collections import defaultdict, OrderedDict
        atend_map = OrderedDict()
        for r in rows:
            aid = r[0]
            if aid not in atend_map:
                atend_map[aid] = {"seq": r[1], "colab": r[2], "modo": r[3],
                                   "dt": r[4], "exames": []}
            atend_map[aid]["exames"].append((r[5], float(r[6])))

        dados = []; total = 0
        for aid, at in atend_map.items():
            dt_fmt = _to_date_str(at["dt"])
            val_at = sum(v for _, v in at["exames"])
            for i, (nome_ex, val) in enumerate(at["exames"]):
                dados.append({"N°": at["seq"] if i==0 else "",
                               "COLABORADOR": at["colab"] if i==0 else "",
                               "MODO": at["modo"] if i==0 else "",
                               "EXAMES": nome_ex,
                               "VALOR": f"R$ {val:.2f}",
                               "DATA": dt_fmt if i==0 else "",
                               "atendimento_id": aid,
                               "valor_atendimento": val_at if i==0 else 0})
                total += val

        _janela_config_fatura(empresa_id, empresa_nome, mes_nome, ano_int, dados, total, len(atend_map))

    except Exception as e:
        messagebox.showerror("Erro", str(e)); traceback.print_exc()

def _janela_config_fatura(empresa_id, empresa_nome, mes_nome, ano_int, dados, total, qtd):
    jan = ctk.CTkToplevel(app)
    jan.title("Configurar Fatura"); jan.geometry("520x380")
    jan.transient(app); jan.grab_set()

    hdr = ctk.CTkFrame(jan, fg_color="#17a2b8", height=50)
    hdr.pack(fill="x"); hdr.pack_propagate(False)
    ctk.CTkLabel(hdr, text="💳 CONFIGURAR FATURA", font=("Arial", 14, "bold"), text_color="white").pack(pady=12)

    main = ctk.CTkScrollableFrame(jan)
    main.pack(fill="both", expand=True, padx=12, pady=10)

    info = ctk.CTkFrame(main, fg_color="#e9ecef")
    info.pack(fill="x", pady=8)
    for txt in [f"🏢 {empresa_nome}", f"📅 {mes_nome}/{ano_int}",
                f"👥 {qtd} atendimento(s)", f"💰 Total: R$ {total:.2f}"]:
        ctk.CTkLabel(info, text=txt, font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=2)

    def linha(label, widget_fn):
        f = ctk.CTkFrame(main, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text=label, width=140, font=("Arial", 10, "bold")).pack(side="left", padx=4)
        w = widget_fn(f); w.pack(side="left", padx=4)
        return w

    cb_forma  = linha("Forma Pagamento:", lambda f: ctk.CTkComboBox(f, values=FORMAS_PAG_FAT, width=150))
    cb_forma.set("PIX")
    ent_venc  = linha("Vencimento:", lambda f: ctk.CTkEntry(f, width=150))
    ent_venc.insert(0, (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y"))
    cb_status = linha("Status:", lambda f: ctk.CTkComboBox(f, values=["PENDENTE","PAGO","ATRASADO"], width=150))
    cb_status.set("PENDENTE")

    f_obs = ctk.CTkFrame(main, fg_color="transparent")
    f_obs.pack(fill="x", pady=5)
    ctk.CTkLabel(f_obs, text="Observações:", width=140, font=("Arial", 10, "bold")).pack(anchor="nw", padx=4)
    ent_obs = ctk.CTkTextbox(f_obs, height=50, font=("Arial", 9))
    ent_obs.pack(fill="x", padx=(144, 4))

    f_btn = ctk.CTkFrame(jan, fg_color="transparent")
    f_btn.pack(fill="x", padx=12, pady=8)

    def gerar():
        try:
            try:
                dv = datetime.strptime(ent_venc.get(), "%d/%m/%Y").date()
            except:
                dv = (datetime.now() + timedelta(days=30)).date()

            mes_num = obter_mes_num(mes_nome)
            emp_pref = "".join(c for c in empresa_nome if c.isalpha())[:3].upper()

            # ── Verificar se já existe fatura para esta empresa/mês ───────────
            fat_exist = executar_query(
                "SELECT id, numero_fatura FROM faturas WHERE empresa_id=%s AND mes_referencia=%s AND ano_referencia=%s",
                (empresa_id, f"{mes_num:02d}", ano_int), fetch=True)
            if fat_exist:
                resp = messagebox.askyesno(
                    "Fatura já existe",
                    f"Já existe a fatura {fat_exist[0][1]} para {empresa_nome} em {mes_nome}/{ano_int}.\n\nDeseja SUBSTITUIR (excluir a antiga e criar nova)?")
                if not resp:
                    return
                # Excluir fatura antiga e seus itens
                for fid, _ in fat_exist:
                    executar_query("DELETE FROM itens_fatura WHERE fatura_id=%s", (fid,))
                    executar_query("DELETE FROM faturas WHERE id=%s", (fid,))

            # ── Gerar número único garantido ──────────────────────────────────
            seq = 1
            while True:
                num_fat = f"FAT-{emp_pref}-{mes_num:02d}{ano_int}-{seq:03d}"
                existe = executar_query(
                    "SELECT 1 FROM faturas WHERE numero_fatura=%s", (num_fat,), fetch=True)
                if not existe:
                    break
                seq += 1
                if seq > 999:
                    messagebox.showerror("Erro", "Não foi possível gerar número único para a fatura!")
                    return

            # ── Inserir fatura ────────────────────────────────────────────────
            r_fat = executar_query("""
                INSERT INTO faturas (numero_fatura, empresa_id, mes_referencia, ano_referencia,
                                     valor_total, quantidade_atendimentos, forma_pagamento,
                                     status_pagamento, data_vencimento, observacoes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (numero_fatura) DO NOTHING
                RETURNING id
            """, (num_fat, empresa_id, f"{mes_num:02d}", ano_int, total, qtd,
                  cb_forma.get(), cb_status.get(), dv,
                  ent_obs.get("1.0", "end-1c")), fetch=True)

            if not r_fat:
                messagebox.showerror("Erro", "Falha ao salvar fatura! Tente novamente."); return

            # ── Inserir itens (inclui valor zero — perícias etc.) ─────────────
            fat_id = r_fat[0][0]; proc = set()
            for item in dados:
                aid = item["atendimento_id"]
                if aid not in proc:
                    try:
                        dt_at = datetime.strptime(item["DATA"], "%d/%m/%Y").date()
                    except:
                        dt_at = date.today()
                    executar_query(
                        """INSERT INTO itens_fatura
                           (fatura_id, atendimento_id, colaborador, modo, data_atendimento, valor_atendimento)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING""",
                        (fat_id, aid, item["COLABORADOR"], item["MODO"],
                         dt_at, item["valor_atendimento"]))
                    proc.add(aid)

            _gerar_excel_fatura(num_fat, empresa_nome, mes_nome, ano_int, dados, total, qtd,
                                cb_forma.get(), cb_status.get(), dv)
            jan.destroy()
            atualizar_tabela_faturas()
            show_status(f"✅ Fatura {num_fat} gerada com sucesso!")

        except Exception as e:
            log(f"Erro ao gerar fatura: {e}", exc=True)
            messagebox.showerror("Erro", f"Falha ao gerar fatura:\n{str(e)}")

    ctk.CTkButton(f_btn, text="📄 GERAR FATURA", fg_color="#28a745", font=("Arial", 11, "bold"),
                  width=140, height=34, command=gerar).pack(side="right", padx=4)
    ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545", font=("Arial", 11, "bold"),
                  width=110, height=34, command=jan.destroy).pack(side="right", padx=4)

def _gerar_excel_fatura(num_fat, empresa_nome, mes_nome, ano_int, dados, total, qtd, forma, status, data_venc):
    try:
        wb = Workbook(); ws = wb.active; ws.title = "Fatura"

        ws.merge_cells("A1:F1"); ws["A1"] = DADOS_EMPRESA["nome"]
        ws["A1"].font = Font(bold=True, size=15, color="0066CC")
        ws["A1"].alignment = Alignment(horizontal="center")
        ws.merge_cells("A2:F2"); ws["A2"] = DADOS_EMPRESA["endereco"]
        ws["A2"].alignment = Alignment(horizontal="center")
        ws.merge_cells("A3:F3"); ws["A3"] = f"Email: {DADOS_EMPRESA['email']} | Tel: {DADOS_EMPRESA['contato']}"
        ws["A3"].alignment = Alignment(horizontal="center")
        ws["A4"] = ""
        ws.merge_cells("A5:F5"); ws["A5"] = f"FATURA Nº {num_fat}"
        ws["A5"].font = Font(bold=True, size=13)
        ws["A5"].alignment = Alignment(horizontal="center")
        ws["A5"].fill = PatternFill(start_color="E6F3FF", end_color="E6F3FF", fill_type="solid")
        ws.merge_cells("A6:D6"); ws["A6"] = f"EMPRESA: {empresa_nome}"
        ws["A6"].font = Font(bold=True, size=12)
        ws.merge_cells("E6:F6"); ws["E6"] = f"Período: {mes_nome}/{ano_int}"
        ws["E6"].font = Font(bold=True, size=12); ws["E6"].alignment = Alignment(horizontal="center")
        ws["A7"] = f"Forma: {forma}"; ws["D7"] = f"Vencimento: {_to_date_str(data_venc)}"
        ws["F7"] = f"Status: {status}"; ws["A8"] = ""

        hdrs = ["N°","COLABORADOR","MODO","EXAMES","VALOR","DATA"]
        for col, h in enumerate(hdrs, 1):
            c = ws.cell(row=9, column=col, value=h)
            c.font = Font(bold=True, color="FFFFFF"); c.alignment = Alignment(horizontal="center")
            c.fill = PatternFill(start_color="0066CC", end_color="0066CC", fill_type="solid")

        linha = 10
        agrup = {}
        for item in dados:
            aid = item["atendimento_id"]
            if aid not in agrup:
                agrup[aid] = {"info": item, "exames": []}
            if item["EXAMES"]:
                agrup[aid]["exames"].append((item["EXAMES"], item["VALOR"]))

        thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                      top=Side(style="thin"), bottom=Side(style="thin"))
        for aid, d in agrup.items():
            info = d["info"]; exs = d["exames"]; n = len(exs)
            li = linha; lf = linha + n - 1
            if n > 1:
                for col_l in ["A","B","C","F"]:
                    ws.merge_cells(f"{col_l}{li}:{col_l}{lf}")
            ws.cell(li, 1, info["N°"]); ws.cell(li, 2, info["COLABORADOR"])
            ws.cell(li, 3, info["MODO"]); ws.cell(li, 6, info["DATA"])
            for i, (nome_ex, val) in enumerate(exs):
                le = li + i
                ws.cell(le, 4, nome_ex); ws.cell(le, 5, val)
                for c in range(1, 7):
                    ws.cell(le, c).border = thin
                    if le % 2 == 0:
                        ws.cell(le, c).fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
            linha += n

        ws.merge_cells(f"A{linha}:D{linha}")
        ws[f"A{linha}"] = "TOTAL GERAL:"
        ws[f"A{linha}"].font = Font(bold=True, size=13)
        ws[f"A{linha}"].alignment = Alignment(horizontal="right")
        ws[f"E{linha}"] = f"R$ {total:.2f}"
        ws[f"E{linha}"].font = Font(bold=True, size=13, color="008000")
        ws[f"E{linha}"].fill = PatternFill(start_color="E8F5E8", end_color="E8F5E8", fill_type="solid")

        for col, w in zip(["A","B","C","D","E","F"], [8, 30, 10, 35, 15, 12]):
            ws.column_dimensions[col].width = w

        nome_arq = f"FATURA_{num_fat}_{limpar_nome_arquivo(empresa_nome)}.xlsx"
        caminho = _salvar_abrir(wb, nome_arq)
        if caminho:
            messagebox.showinfo("✅ Fatura Gerada!",
                f"📄 {num_fat}\n🏢 {empresa_nome}\n📅 {mes_nome}/{ano_int}\n"
                f"👥 {qtd} atendimento(s)\n💰 R$ {total:.2f}\n\n📁 {caminho}")
        else:
            messagebox.showerror("Erro", "Não foi possível salvar o arquivo Excel!")
    except Exception as e:
        messagebox.showerror("Erro Excel", str(e)); traceback.print_exc()

# =============================================================================
# TABELAS OFAT
# =============================================================================

def atualizar_tabela_faturas():
    """Carrega faturas em background para não travar a UI."""
    def _worker():
        try:
            if not tree_faturas:
                return
            rows = executar_query("""
                SELECT f.id, f.numero_fatura, e.nome, f.mes_referencia, f.ano_referencia,
                       f.valor_total, f.quantidade_atendimentos, f.forma_pagamento,
                       f.status_pagamento, f.data_vencimento,
                       COALESCE(f.data_vencimento::TEXT, f.numero_fatura, ''),
                       COALESCE(f.observacoes, '') AS obs
                FROM faturas f
                LEFT JOIN empresas e ON f.empresa_id = e.id
                ORDER BY f.id DESC
                LIMIT 200
            """, fetch=True)
            gui_safe(lambda r=rows: _apply_faturas(r))
        except Exception as e:
            log(f"Erro tabela faturas: {e}")

    def _apply_faturas(rows):
        try:
            for item in tree_faturas.get_children():
                tree_faturas.delete(item)
            tree_faturas.tag_configure("PAGO",     background="#d4edda")
            tree_faturas.tag_configure("PENDENTE", background="#fff3cd")
            tree_faturas.tag_configure("ATRASADO", background="#f8d7da")
            for r in (rows or []):
                try:
                    mn = int(r[3]); mes_n = MESES_NOMES[mn-1] if 1<=mn<=12 else r[3]
                    obs_icon = "📝" if r[11] else ""
                    tree_faturas.insert("", "end", iid=str(r[0]), values=(
                        r[0], r[1], (r[2] or "")[:25], f"{mes_n}/{r[4]}",
                        f"R$ {float(r[5]):.2f}", r[6], r[7], r[8],
                        _to_date_str(r[9]), _to_date_str(r[10]), obs_icon
                    ), tags=(r[8],))
                except:
                    continue
        except Exception as e:
            log(f"Erro apply faturas: {e}")

    threading.Thread(target=_worker, daemon=True).start()

def alterar_status_fatura():
    try:
        if not tree_faturas:
            return
        sel = tree_faturas.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma fatura!"); return
        vals   = tree_faturas.item(sel[0])["values"]
        fat_id = vals[0]; num_fat = vals[1]; status_at = vals[7]

        # Buscar observação atual do banco
        obs_atual = executar_query(
            "SELECT COALESCE(observacoes,'') FROM faturas WHERE id=%s",
            (fat_id,), fetch=True)
        obs_atual = obs_atual[0][0] if obs_atual else ""

        jan = ctk.CTkToplevel(app)
        jan.title("Alterar Status"); jan.geometry("440x360")
        jan.transient(app); jan.grab_set(); jan.lift()

        hdr = ctk.CTkFrame(jan, fg_color="#fd7e14", height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🔄 ALTERAR STATUS DA FATURA",
                     font=("Arial", 13, "bold"), text_color="white").pack(pady=12)

        main = ctk.CTkFrame(jan, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=15, pady=10)

        ctk.CTkLabel(main, text=f"Fatura: {num_fat}  |  Status atual: {status_at}",
                     font=("Arial", 11, "bold")).pack(pady=(0, 8))

        # Status
        f1 = ctk.CTkFrame(main, fg_color="transparent")
        f1.pack(fill="x", pady=4)
        ctk.CTkLabel(f1, text="Novo Status:", width=130, font=("Arial", 10, "bold"), anchor="w").pack(side="left")
        cb_novo = ctk.CTkComboBox(f1, values=["PENDENTE","PAGO","ATRASADO"], width=140, state="readonly")
        cb_novo.set(status_at); cb_novo.pack(side="left", padx=6)

        # Data pagamento
        f2 = ctk.CTkFrame(main, fg_color="transparent")
        f2.pack(fill="x", pady=4)
        ctk.CTkLabel(f2, text="Data Pagamento:", width=130, font=("Arial", 10, "bold"), anchor="w").pack(side="left")
        ent_dp = ctk.CTkEntry(f2, width=140, placeholder_text="DD/MM/AAAA")
        ent_dp.insert(0, datetime.now().strftime("%d/%m/%Y")); ent_dp.pack(side="left", padx=6)

        # Observação
        ctk.CTkLabel(main, text="📝 Observação:", font=("Arial", 10, "bold"), anchor="w").pack(fill="x", pady=(8,2))
        txt_obs = ctk.CTkTextbox(main, height=80, font=("Arial", 10))
        txt_obs.pack(fill="x")
        if obs_atual:
            txt_obs.insert("1.0", obs_atual)
        txt_obs.configure(wrap="word")

        f_btn = ctk.CTkFrame(jan, fg_color="transparent")
        f_btn.pack(fill="x", padx=15, pady=8)

        def salvar():
            novo = cb_novo.get(); dp = None
            if novo == "PAGO":
                try:
                    dp = datetime.strptime(ent_dp.get().strip(), "%d/%m/%Y").date()
                except:
                    messagebox.showerror("Erro", "Data inválida! Use DD/MM/AAAA"); return
            obs_novo = txt_obs.get("1.0", "end").strip()
            executar_query(
                "UPDATE faturas SET status_pagamento=%s, data_pagamento=%s, observacoes=%s WHERE id=%s",
                (novo, dp, obs_novo or None, fat_id))
            messagebox.showinfo("✅", f"Status alterado: {status_at} → {novo}")
            jan.destroy(); atualizar_tabela_faturas()

        ctk.CTkButton(f_btn, text="💾 SALVAR", fg_color="#28a745",
                      width=130, height=34, font=("Arial", 11, "bold"),
                      command=salvar).pack(side="right", padx=4)
        ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545",
                      width=110, height=34,
                      command=jan.destroy).pack(side="right", padx=4)

    except Exception as e:
        messagebox.showerror("Erro", str(e))

def excluir_fatura():
    """Exclui a fatura selecionada e seus itens_fatura vinculados"""
    if not tree_faturas:
        return
    sel = tree_faturas.selection()
    if not sel:
        messagebox.showwarning("Atencao", "Selecione uma fatura para excluir.")
        return

    fat_id  = sel[0]
    vals    = tree_faturas.item(fat_id)["values"]
    num_fat = vals[1] if vals and len(vals) > 1 else "?"
    empresa = vals[2] if vals and len(vals) > 2 else "?"
    valor   = vals[4] if vals and len(vals) > 4 else "?"
    status  = vals[7] if vals and len(vals) > 7 else "?"

    try:
        fat_id_int = int(fat_id)
    except ValueError:
        messagebox.showerror("Erro", "ID invalido: " + str(fat_id))
        return

    # Contar itens vinculados
    itens = executar_query(
        "SELECT COUNT(*) FROM itens_fatura WHERE fatura_id=%s",
        (fat_id_int,), fetch=True)
    qtd_itens = int(itens[0][0]) if itens else 0

    aviso = ("Excluir fatura:\n\n"
             "  Numero: " + str(num_fat) + "\n"
             "  Empresa: " + str(empresa) + "\n"
             "  Valor: " + str(valor) + "\n"
             "  Status: " + str(status) + "\n")
    if qtd_itens > 0:
        aviso += "\n  " + str(qtd_itens) + " item(s) vinculado(s) tambem serao removidos.\n"
    aviso += "\nEsta acao nao pode ser desfeita."

    if not messagebox.askyesno("Confirmar Exclusao", aviso):
        return

    # 1. Excluir itens da fatura
    executar_query("DELETE FROM itens_fatura WHERE fatura_id=%s", (fat_id_int,))
    # 2. Excluir a fatura
    ok = executar_query("DELETE FROM faturas WHERE id=%s", (fat_id_int,))

    if ok:
        messagebox.showinfo("Excluido", "Fatura " + str(num_fat) + " excluida com sucesso!")
        atualizar_tabela_faturas()
    else:
        messagebox.showerror("Erro", "Nao foi possivel excluir a fatura.")


def atualizar_tabela_exames():
    if not tree_exames:
        return
    try:
        for item in tree_exames.get_children():
            tree_exames.delete(item)
        rows = executar_query("SELECT id, codigo, nome_exame, valor_unitario, categoria, ativo FROM exames_disponiveis ORDER BY categoria, nome_exame", fetch=True)
        tree_exames.tag_configure("ativo",   background="#d4edda")
        tree_exames.tag_configure("inativo", background="#f8d7da")
        for r in rows:
            tree_exames.insert("", "end", values=(r[0], r[1], r[2], f"R$ {float(r[3]):.2f}", r[4], "ATIVO" if r[5] else "INATIVO"),
                               tags=("ativo" if r[5] else "inativo",))
    except Exception as e:
        log(f"Erro tabela exames: {e}")

def atualizar_tabela_empresas():
    if not tree_empresas:
        return
    try:
        for item in tree_empresas.get_children():
            tree_empresas.delete(item)
        rows = executar_query("""SELECT e.id, e.nome, e.cnpj, e.responsavel, e.telefone, e.email, e.ativo,
                                        (SELECT COUNT(*) FROM atendimentos a WHERE a.empresa_id=e.id)
                                 FROM empresas e ORDER BY e.nome""", fetch=True)
        tree_empresas.tag_configure("ativo",   background="#d4edda")
        tree_empresas.tag_configure("inativo", background="#f8d7da")
        for r in rows:
            tree_empresas.insert("", "end", values=(r[0], r[1], r[2] or "", r[3] or "", r[4] or "", r[5] or "", r[7], "ATIVO" if r[6] else "INATIVO"),
                                 tags=("ativo" if r[6] else "inativo",))
    except Exception as e:
        log(f"Erro tabela empresas: {e}")

def inserir_empresa():
    try:
        jan = ctk.CTkToplevel(app)
        jan.title("Nova Empresa"); jan.geometry("500x380")
        jan.transient(app); jan.grab_set()

        hdr = ctk.CTkFrame(jan, fg_color="#17a2b8", height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🏢 NOVA EMPRESA", font=("Arial", 14, "bold"), text_color="white").pack(pady=12)

        main = ctk.CTkScrollableFrame(jan)
        main.pack(fill="both", expand=True, padx=12, pady=10)

        campos = {}
        for label, key, w in [("Nome/Razão Social:", "nome", 280), ("CNPJ:", "cnpj", 160),
                               ("Responsável:", "resp", 230), ("Telefone:", "tel", 160),
                               ("Email:", "email", 230), ("Endereço:", "end", 280)]:
            f = ctk.CTkFrame(main, fg_color="transparent")
            f.pack(fill="x", pady=5)
            ctk.CTkLabel(f, text=label, width=130, font=("Arial", 10, "bold")).pack(side="left", padx=4)
            ent = ctk.CTkEntry(f, width=w); ent.pack(side="left", padx=4)
            campos[key] = ent

        f_btn = ctk.CTkFrame(jan, fg_color="transparent")
        f_btn.pack(fill="x", padx=12, pady=8)

        def salvar():
            nome = campos["nome"].get().strip()
            if not nome:
                messagebox.showwarning("Aviso", "Nome é obrigatório!"); return
            r = executar_query("""INSERT INTO empresas (nome, cnpj, responsavel, telefone, email, endereco, ativo)
                                  VALUES (%s,%s,%s,%s,%s,%s,TRUE) ON CONFLICT (nome) DO NOTHING RETURNING id""",
                               (nome, campos["cnpj"].get().strip(), campos["resp"].get().strip(),
                                campos["tel"].get().strip(), campos["email"].get().strip(),
                                campos["end"].get().strip()), fetch=True)
            if not r:
                messagebox.showwarning("Aviso", "Empresa já cadastrada!"); return
            messagebox.showinfo("✅", f"Empresa '{nome}' cadastrada! ID: {r[0][0]}")
            jan.destroy(); atualizar_tabela_empresas(); atualizar_filtros_fat()

        ctk.CTkButton(f_btn, text="💾 SALVAR", fg_color="#17a2b8", width=120, command=salvar).pack(side="right", padx=4)
        ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545", width=100, command=jan.destroy).pack(side="right", padx=4)
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def editar_exame():
    """Abre janela para editar exame selecionado na tree"""
    try:
        if not tree_exames:
            return
        sel = tree_exames.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um exame para editar!"); return
        vals = tree_exames.item(sel[0])["values"]
        ex_id   = vals[0]
        ex_nome = vals[1]

        # Buscar dados completos do exame
        r = executar_query(
            "SELECT id, codigo, nome_exame, categoria, valor_unitario, ativo FROM exames_disponiveis WHERE id=%s",
            (ex_id,), fetch=True
        )
        if not r:
            messagebox.showerror("Erro", "Exame não encontrado!"); return
        d = r[0]

        jan = ctk.CTkToplevel(app)
        jan.title(f"Editar Exame — {ex_nome}"); jan.geometry("480x360")
        jan.transient(app); jan.grab_set()

        hdr = ctk.CTkFrame(jan, fg_color="#e67e22", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=f"✏️ EDITAR EXAME — ID {ex_id}",
                     font=("Arial", 13, "bold"), text_color="white").pack(pady=13)

        main = ctk.CTkScrollableFrame(jan)
        main.pack(fill="both", expand=True, padx=14, pady=10)

        campos = {}
        dados = {"codigo": d[1] or "", "nome": d[2] or "", "categoria": d[3] or "", "valor": str(d[4] or "0")}

        for label, key, w in [("Código:", "codigo", 120), ("Nome do Exame:", "nome", 260),
                               ("Categoria:", "categoria", 180), ("Valor (R$):", "valor", 120)]:
            f = ctk.CTkFrame(main, fg_color="transparent"); f.pack(fill="x", pady=6)
            ctk.CTkLabel(f, text=label, width=130, font=("Arial", 10, "bold")).pack(side="left", padx=4)
            ent = ctk.CTkEntry(f, width=w, height=34)
            ent.insert(0, dados[key])
            ent.pack(side="left", padx=4)
            campos[key] = ent

        f_btn = ctk.CTkFrame(jan, fg_color="transparent")
        f_btn.pack(fill="x", padx=14, pady=10)

        def salvar_edicao_exame():
            nome = campos["nome"].get().strip()
            if not nome:
                messagebox.showwarning("Aviso", "Nome do exame é obrigatório!"); return
            try:
                valor = float(campos["valor"].get().strip().replace(",", "."))
            except:
                messagebox.showwarning("Aviso", "Valor inválido! Use números (ex: 45.00)"); return

            executar_query("""UPDATE exames_disponiveis
                               SET codigo=%s, nome_exame=%s, categoria=%s, valor_unitario=%s
                               WHERE id=%s""",
                           (campos["codigo"].get().strip(), nome,
                            campos["categoria"].get().strip(), valor, ex_id))
            messagebox.showinfo("Sucesso", f"Exame atualizado com sucesso! Novo valor: R$ {valor:.2f}")
            jan.destroy()
            atualizar_tabela_exames()

        ctk.CTkButton(f_btn, text="💾 SALVAR", fg_color="#e67e22",
                      font=("Arial", 11, "bold"), width=130, height=36,
                      command=salvar_edicao_exame).pack(side="right", padx=4)
        ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545",
                      width=110, height=36, command=jan.destroy).pack(side="right", padx=4)

    except Exception as e:
        messagebox.showerror("Erro", str(e))

def inserir_exame():
    try:
        jan = ctk.CTkToplevel(app)
        jan.title("Novo Exame"); jan.geometry("500x340")
        jan.transient(app); jan.grab_set()

        hdr = ctk.CTkFrame(jan, fg_color="#6f42c1", height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🔬 NOVO EXAME", font=("Arial", 14, "bold"), text_color="white").pack(pady=12)

        main = ctk.CTkScrollableFrame(jan)
        main.pack(fill="both", expand=True, padx=12, pady=10)

        def campo(lbl, w):
            f = ctk.CTkFrame(main, fg_color="transparent"); f.pack(fill="x", pady=5)
            ctk.CTkLabel(f, text=lbl, width=110, font=("Arial", 10, "bold")).pack(side="left", padx=4)
            ent = ctk.CTkEntry(f, width=w); ent.pack(side="left", padx=4)
            return ent

        ent_cod  = campo("Código:", 120)
        ent_nome = campo("Nome:", 280)
        ent_val  = campo("Valor:", 120)

        f_cat = ctk.CTkFrame(main, fg_color="transparent"); f_cat.pack(fill="x", pady=5)
        ctk.CTkLabel(f_cat, text="Categoria:", width=110, font=("Arial", 10, "bold")).pack(side="left", padx=4)
        cb_cat = ctk.CTkComboBox(f_cat, values=["CLINICO","LABORATORIAL","RADIOLOGICO","CARDIOLOGICO",
                                                  "NEUROLOGICO","OFTALMOLOGICO","AUDIOLOGICO","PNEUMOLOGICO"], width=180)
        cb_cat.set("CLINICO"); cb_cat.pack(side="left", padx=4)

        f_btn = ctk.CTkFrame(jan, fg_color="transparent")
        f_btn.pack(fill="x", padx=12, pady=8)

        def salvar():
            nome = ent_nome.get().strip()
            if not nome:
                messagebox.showwarning("Aviso", "Nome é obrigatório!"); return
            try:
                val = float(ent_val.get().replace(",", "."))
            except:
                messagebox.showerror("Erro", "Valor inválido!"); return
            cod = ent_cod.get().strip() or f"{cb_cat.get()[:3]}{len(nome):03d}"
            r = executar_query("""INSERT INTO exames_disponiveis (codigo, nome_exame, valor_unitario, categoria, ativo)
                                  VALUES (%s,%s,%s,%s,TRUE) ON CONFLICT (nome_exame) DO NOTHING RETURNING id""",
                               (cod, nome, val, cb_cat.get()), fetch=True)
            if not r:
                messagebox.showwarning("Aviso", "Exame já cadastrado!"); return
            messagebox.showinfo("✅", f"Exame '{nome}' cadastrado!")
            jan.destroy(); atualizar_tabela_exames()

        ctk.CTkButton(f_btn, text="💾 SALVAR", fg_color="#6f42c1", width=120, command=salvar).pack(side="right", padx=4)
        ctk.CTkButton(f_btn, text="❌ CANCELAR", fg_color="#dc3545", width=100, command=jan.destroy).pack(side="right", padx=4)
    except Exception as e:
        messagebox.showerror("Erro", str(e))


def _alerta_aso_startup():
    """Verifica ASOs vencidos/próximos ao abrir e exibe popup se necessário."""
    try:
        rows = executar_query("""
            SELECT
                a.colaborador,
                COALESCE(e.nome,'N/A') AS empresa,
                a.data_vencimento_aso,
                (a.data_vencimento_aso - CURRENT_DATE) AS dias
            FROM atendimentos a
            LEFT JOIN empresas e ON a.empresa_id=e.id
            WHERE a.data_vencimento_aso IS NOT NULL
              AND a.status='ATIVO'
              AND a.data_vencimento_aso <= CURRENT_DATE + INTERVAL '30 days'
            ORDER BY a.data_vencimento_aso ASC
            LIMIT 20
        """, fetch=True) or []

        if not rows:
            return

        vencidos  = [r for r in rows if (r[3] or 0) < 0]
        proximos  = [r for r in rows if 0 <= (r[3] or 0) <= 30]

        if not vencidos and not proximos:
            return

        # Criar janela de alerta
        win = ctk.CTkToplevel(app)
        win.title("⚠️ Alerta de Vencimento ASO")
        win.geometry("520x480")
        win.grab_set()
        win.lift()

        ctk.CTkLabel(win, text="🚨  ALERTA DE VENCIMENTO ASO",
                     font=("Arial", 16, "bold"), text_color="#dc3545").pack(pady=(16,4))
        ctk.CTkLabel(win, text=f"{len(vencidos)} vencido(s) | {len(proximos)} vence(m) em até 30 dias",
                     font=("Arial", 12), text_color="#666").pack(pady=(0,10))

        scroll = ctk.CTkScrollableFrame(win, fg_color="#f8f9fa", height=320)
        scroll.pack(fill="both", expand=True, padx=16, pady=4)

        for r in rows:
            colab, emp, dt_venc, dias = r
            dias_int = int(dias) if dias is not None else 0
            if dias_int < 0:
                cor = "#FADBD8"; badge = f"VENCIDO {abs(dias_int)}d"; bc = "#dc3545"
            elif dias_int <= 7:
                cor = "#FDEBD0"; badge = f"URGENTE {dias_int}d"; bc = "#e74c3c"
            else:
                cor = "#FEF9E7"; badge = f"VENCE {dias_int}d"; bc = "#fd7e14"

            linha = ctk.CTkFrame(scroll, fg_color=cor, corner_radius=6, height=52)
            linha.pack(fill="x", pady=2); linha.pack_propagate(False)
            ctk.CTkLabel(linha, text=colab[:28] if colab else "—",
                         font=("Arial",11,"bold"), anchor="w").pack(side="left", padx=10, pady=4)
            ctk.CTkLabel(linha, text=emp[:18] if emp else "—",
                         font=("Arial",10), text_color="#555", anchor="w").pack(side="left", padx=4)
            b = ctk.CTkFrame(linha, fg_color=bc, corner_radius=6, width=100, height=28)
            b.pack(side="right", padx=10, pady=12); b.pack_propagate(False)
            ctk.CTkLabel(b, text=badge, font=("Arial",9,"bold"), text_color="white").pack(expand=True)

        f_btns = ctk.CTkFrame(win, fg_color="transparent")
        f_btns.pack(pady=12)
        ctk.CTkButton(f_btns, text="✖ FECHAR", fg_color="#6c757d", width=120,
                      command=win.destroy).pack(side="left", padx=8)

    except Exception as e:
        log(f"Erro alerta ASO: {e}")


def abrir_historico_paciente():
    """
    Janela de Histórico do Paciente — busca por nome ou CPF.
    Mostra todos os atendimentos (Recepção + Faturamento) com datas e valores.
    Queries verificadas: usa valor_num (recepção) e valor_unitario (faturamento).
    """
    win = ctk.CTkToplevel(app)
    win.title("📋 Histórico do Paciente")
    win.geometry("900x640")
    win.grab_set(); win.lift()

    # ── Header ────────────────────────────────────────────────────────────────
    f_hdr = ctk.CTkFrame(win, fg_color="#1f4e79", height=50, corner_radius=0)
    f_hdr.pack(fill="x"); f_hdr.pack_propagate(False)
    ctk.CTkLabel(f_hdr, text="📋  HISTÓRICO DO PACIENTE / COLABORADOR",
                 font=("Arial", 14, "bold"), text_color="white").pack(side="left", pady=12, padx=20)

    # ── Busca ─────────────────────────────────────────────────────────────────
    f_busca = ctk.CTkFrame(win, fg_color="#E8F4FD", corner_radius=8)
    f_busca.pack(fill="x", padx=12, pady=8)
    ctk.CTkLabel(f_busca, text="🔍 Nome ou CPF:",
                 font=("Arial", 12, "bold")).pack(side="left", padx=12, pady=10)
    ent_busca_hist = ctk.CTkEntry(f_busca, placeholder_text="Digite nome ou CPF e pressione Enter...",
                                  width=360, height=34, font=("Arial", 12))
    ent_busca_hist.pack(side="left", padx=8, pady=10)
    ctk.CTkButton(f_busca, text="🔍 BUSCAR", width=110, height=34,
                  fg_color="#1f4e79", font=("Arial", 12, "bold"),
                  command=lambda: _buscar()).pack(side="left", padx=8, pady=10)
    ctk.CTkButton(f_busca, text="✖ LIMPAR", width=80, height=34,
                  fg_color="#6c757d", font=("Arial", 11),
                  command=lambda: (ent_busca_hist.delete(0,"end"),
                                   [w.destroy() for w in scroll_hist.winfo_children()])
                  ).pack(side="left", padx=4, pady=10)

    scroll_hist = ctk.CTkScrollableFrame(win, fg_color="#f8f9fa")
    scroll_hist.pack(fill="both", expand=True, padx=12, pady=(0,8))

    def _buscar():
        termo = ent_busca_hist.get().strip()
        if len(termo) < 2:
            return
        for w in scroll_hist.winfo_children():
            w.destroy()

        # ── Recepção: usa valor_num (NUMERIC) com fallback para valor (REAL) ──
        rec = executar_query("""
            SELECT
                data_ts,
                COALESCE(nome, '') AS nome,
                COALESCE(cpf, '')  AS cpf,
                COALESCE(tipo, '') AS tipo,
                COALESCE(empresa, '') AS empresa,
                COALESCE(exames, '') AS exames,
                COALESCE(valor_num, valor, 0) AS valor,
                COALESCE(pagamento, '') AS pagamento,
                COALESCE(telefone, '') AS telefone
            FROM recepcao
            WHERE (UPPER(nome) LIKE UPPER(%s) OR cpf LIKE %s)
              AND (excluido IS NOT TRUE)
            ORDER BY data_ts DESC
            LIMIT 200
        """, (f"%{termo}%", f"%{termo}%"), fetch=True) or []

        # ── Faturamento: soma exames_atendimento ──────────────────────────────
        fat = executar_query("""
            SELECT
                a.data_atendimento,
                COALESCE(a.colaborador, '') AS colaborador,
                COALESCE(a.cpf_colaborador, '') AS cpf,
                COALESCE(a.modo, '') AS modo,
                COALESCE(e.nome, 'N/A') AS empresa,
                a.data_vencimento_aso,
                COALESCE(SUM(ex.valor_unitario), 0) AS total,
                COALESCE(STRING_AGG(ex.nome_exame, ', '), '') AS exames
            FROM atendimentos a
            LEFT JOIN empresas e ON a.empresa_id = e.id
            LEFT JOIN exames_atendimento ex ON ex.atendimento_id = a.id
            WHERE (UPPER(a.colaborador) LIKE UPPER(%s)
                   OR a.cpf_colaborador LIKE %s)
              AND a.status = 'ATIVO'
            GROUP BY a.id, a.data_atendimento, a.colaborador,
                     a.cpf_colaborador, a.modo, e.nome, a.data_vencimento_aso
            ORDER BY a.data_atendimento DESC
            LIMIT 200
        """, (f"%{termo}%", f"%{termo}%"), fetch=True) or []

        if not rec and not fat:
            ctk.CTkLabel(scroll_hist, text="⚠️  Nenhum registro encontrado para este termo.",
                         font=("Arial", 13), text_color="#888").pack(pady=30)
            return

        # ── Resumo ────────────────────────────────────────────────────────────
        total_rec = sum(float(r[6] or 0) for r in rec)
        total_fat = sum(float(r[6] or 0) for r in fat)
        total_geral = total_rec + total_fat

        f_res = ctk.CTkFrame(scroll_hist, fg_color="#1f4e79", corner_radius=8)
        f_res.pack(fill="x", pady=(4,8))
        ctk.CTkLabel(f_res,
                     text=(f"📊  {len(rec)} na Recepção (R$ {total_rec:.2f})  |  "
                           f"{len(fat)} no Faturamento (R$ {total_fat:.2f})  |  "
                           f"Total Geral: R$ {total_geral:.2f}"),
                     font=("Arial", 12, "bold"), text_color="white").pack(pady=8, padx=16)

        # ── RECEPÇÃO ──────────────────────────────────────────────────────────
        if rec:
            f_sec = ctk.CTkFrame(scroll_hist, fg_color="#EBF5FB", corner_radius=6)
            f_sec.pack(fill="x", pady=(6,2))
            ctk.CTkLabel(f_sec, text=f"👥  RECEPÇÃO  ({len(rec)} registros)",
                         font=("Arial", 12, "bold"), text_color="#1A5276",
                         anchor="w").pack(fill="x", padx=12, pady=6)

            # Cabeçalho
            f_ch = ctk.CTkFrame(scroll_hist, fg_color="#1A5276", height=30)
            f_ch.pack(fill="x", pady=(0,1)); f_ch.pack_propagate(False)
            for txt, w in [("DATA/HORA",130),("NOME",190),("TIPO",70),
                            ("EMPRESA",150),("EXAMES",160),("VALOR",90),("PAG.",80)]:
                ctk.CTkLabel(f_ch, text=txt, width=w, font=("Arial",9,"bold"),
                             text_color="white", anchor="w").pack(side="left", padx=4, pady=6)

            for r in rec:
                dt, nome, cpf, tipo, emp, exames, val, pag, tel = r
                dt_str = dt.strftime("%d/%m/%Y %H:%M") if hasattr(dt,"strftime") else str(dt or "—")
                cor = "#FFFFFF" if rec.index(r) % 2 == 0 else "#F2F9FF"
                linha = ctk.CTkFrame(scroll_hist, fg_color=cor, height=44)
                linha.pack(fill="x", pady=0); linha.pack_propagate(False)
                for txt, w in [(dt_str,130),(nome[:26],190),(tipo[:10],70),
                                (emp[:20],150),(exames[:22],160),
                                (f"R$ {float(val or 0):.2f}",90),(pag[:10],80)]:
                    ctk.CTkLabel(linha, text=txt, width=w,
                                 font=("Arial",10), anchor="w").pack(side="left", padx=4)

        # ── FATURAMENTO ───────────────────────────────────────────────────────
        if fat:
            f_sec2 = ctk.CTkFrame(scroll_hist, fg_color="#F5EEF8", corner_radius=6)
            f_sec2.pack(fill="x", pady=(10,2))
            ctk.CTkLabel(f_sec2, text=f"📋  FATURAMENTO OCUPACIONAL  ({len(fat)} registros)",
                         font=("Arial", 12, "bold"), text_color="#8E44AD",
                         anchor="w").pack(fill="x", padx=12, pady=6)

            # Cabeçalho
            f_ch2 = ctk.CTkFrame(scroll_hist, fg_color="#8E44AD", height=30)
            f_ch2.pack(fill="x", pady=(0,1)); f_ch2.pack_propagate(False)
            for txt, w in [("DATA",100),("COLABORADOR",190),("TIPO",70),
                            ("EMPRESA",150),("EXAMES",160),("VALOR",90),("VENCIMENTO",110)]:
                ctk.CTkLabel(f_ch2, text=txt, width=w, font=("Arial",9,"bold"),
                             text_color="white", anchor="w").pack(side="left", padx=4, pady=6)

            for r in fat:
                dt, colab, cpf, modo, emp, dt_venc, val, exames = r
                dt_str   = dt.strftime("%d/%m/%Y") if hasattr(dt,"strftime") else str(dt or "—")
                venc_str = dt_venc.strftime("%d/%m/%Y") if dt_venc and hasattr(dt_venc,"strftime") else "—"
                cor = "#FFFFFF" if fat.index(r) % 2 == 0 else "#FDF2FF"
                linha = ctk.CTkFrame(scroll_hist, fg_color=cor, height=44)
                linha.pack(fill="x", pady=0); linha.pack_propagate(False)
                for txt, w in [(dt_str,100),(colab[:26],190),(modo[:10],70),
                                (emp[:20],150),(exames[:22],160),
                                (f"R$ {float(val or 0):.2f}",90),(venc_str,110)]:
                    ctk.CTkLabel(linha, text=txt, width=w,
                                 font=("Arial",10), anchor="w").pack(side="left", padx=4)

    ent_busca_hist.bind("<Return>", lambda e: _buscar())


def _html_esc_doc(s):
    if s is None:
        return ""
    t = str(s)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _base_dir_sistema():
    return _diretorio_app()


def _data_extenso_porto_velho():
    """Ex.: '3 de abril de 2026' para uso em atestados."""
    d = datetime.now()
    return f"{d.day} de {MESES_NOMES[d.month - 1]} de {d.year}"


def _data_linha_documentos():
    """Data padrão impressa nos documentos — ex.: Porto Velho-Ro, 7 de abril de 2026."""
    return f"Porto Velho-Ro, {_data_extenso_porto_velho()}."


def _frase_inscricao_crm_rqe(crm, uf, rqe):
    """Trecho após o nome do médico: CRM/UF; RQE só se existir no cadastro."""
    uf_c = _html_esc_doc(uf or "RO")
    crm_e = (crm or "").strip()
    rqe_e = (rqe or "").strip()
    if crm_e:
        base = f"inscrito(a) no Conselho Regional de Medicina sob nº {_html_esc_doc(crm_e)}/{uf_c}"
        if rqe_e:
            rqe_part = f" e RQE {_html_esc_doc(rqe_e)}"
        else:
            rqe_part = ""
        return f"{base}{rqe_part}, declaro que"
    return f"inscrito(a) no Conselho Regional de Medicina sob nº (informar CRM/{uf_c}), declaro que"


def _frase_inscricao_crm_rqe_pdf(crm, uf, rqe):
    """Igual a _frase_inscricao_crm_rqe, texto plano para PDF (sem entidades HTML)."""
    uf_c = uf or "RO"
    crm_e = (crm or "").strip()
    rqe_e = (rqe or "").strip()
    if crm_e:
        base = f"inscrito(a) no Conselho Regional de Medicina sob nº {crm_e}/{uf_c}"
        if rqe_e:
            base += f" e RQE {rqe_e}"
        return f"{base}, declaro que"
    return f"inscrito(a) no Conselho Regional de Medicina sob nº (informar CRM/{uf_c}), declaro que"


_logo_data_uri_cache = [None]


def _iter_bases_assets():
    """Pastas-base: empacotado no PyInstaller (_MEIPASS), pasta do .exe e (ZIP) pasta pai com assets."""
    visto = set()
    if getattr(sys, "frozen", False):
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            p = os.path.normpath(meip)
            if p not in visto:
                visto.add(p)
                yield p
    p = os.path.normpath(_diretorio_app())
    if p not in visto:
        visto.add(p)
        yield p
    # Entrega em ZIP: exe em ...\Pacote\APTUS\APTUS.exe — assets pode estar em ...\Pacote\assets\
    if getattr(sys, "frozen", False):
        pai = os.path.dirname(p)
        if pai and os.path.isdir(os.path.join(pai, "assets")):
            pai = os.path.normpath(pai)
            if pai not in visto:
                visto.add(pai)
                yield pai


def logo_documentos_configurada():
    """True se existir logo em assets (obrigatória para documentos HTML/PDF)."""
    for base in _iter_bases_assets():
        pasta = os.path.join(base, "assets")
        for nome in ("logo_aptus.png", "logo_aptus.jpg", "logo_aptus.jpeg"):
            if os.path.isfile(os.path.join(pasta, nome)):
                return True
    return False


def _caminho_icone_app():
    """Primeiro .ico encontrado em assets: logo_aptus.ico, app.ico, aptus.ico, icon.ico."""
    for base in _iter_bases_assets():
        pasta = os.path.join(base, "assets")
        for nome in ("logo_aptus.ico", "app.ico", "aptus.ico", "icon.ico"):
            p = os.path.join(pasta, nome)
            if os.path.isfile(p):
                return os.path.normpath(os.path.abspath(p))
    return ""


def _aplicar_icone_janela(root):
    """Ícone da barra de título — falha silenciosa (ícone inválido não deve impedir o programa)."""
    path = _caminho_icone_app()
    if not path:
        return
    try:
        root.iconbitmap(path)
    except Exception:
        try:
            root.tk.call("wm", "iconbitmap", root._w, path)
        except Exception:
            pass
    else:
        try:
            log(f"Ícone da janela: {os.path.basename(path)}")
        except Exception:
            pass


def _pasta_executavel_abs():
    """Pasta onde está APTUS.exe (ou o script .py ao desenvolver). Caminho absoluto."""
    return os.path.abspath(_diretorio_app())


def _texto_local_logo_documentos():
    """Instruções com caminhos completos para colocar a logo ao lado do executável."""
    raiz = _pasta_executavel_abs()
    pasta_assets = os.path.join(raiz, "assets")
    extras = ""
    pai = os.path.dirname(raiz)
    if pai and os.path.isdir(os.path.join(pai, "assets")):
        pa = os.path.join(pai, "assets")
        extras = (
            "\n\n(O pacote ZIP também pode ter a pasta assets ao lado da pasta APTUS:)\n"
            f"   • {os.path.join(pa, 'logo_aptus.png')} (ou .jpg / .jpeg)"
        )
    return (
        "A logo vai na pasta assets — preferencialmente ao lado do APTUS.exe:\n\n"
        f"1) Pasta do executável:\n   {raiz}\n\n"
        f"2) Crie (ou use) a pasta:\n   {pasta_assets}\n\n"
        "3) Coloque UM destes ficheiros:\n"
        f"   • {os.path.join(pasta_assets, 'logo_aptus.png')}\n"
        f"   • {os.path.join(pasta_assets, 'logo_aptus.jpg')}\n"
        f"   • {os.path.join(pasta_assets, 'logo_aptus.jpeg')}"
        f"{extras}"
    )


def _logo_png_data_uri():
    """Lê assets/logo_aptus.png (ou .jpg) — cache só com sucesso; procura no .exe empacotado e ao lado do programa."""
    import base64

    if _logo_data_uri_cache[0]:
        return _logo_data_uri_cache[0]
    candidatos = (
        ("logo_aptus.png", "image/png"),
        ("logo_aptus.jpg", "image/jpeg"),
        ("logo_aptus.jpeg", "image/jpeg"),
    )
    for base in _iter_bases_assets():
        pasta = os.path.join(base, "assets")
        for nome, mime in candidatos:
            path = os.path.join(pasta, nome)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode("ascii")
                _logo_data_uri_cache[0] = f"data:{mime};base64,{b64}"
                return _logo_data_uri_cache[0]
            except Exception:
                continue
    return ""


def _html_cabecalho_so_logo():
    """Cabeçalho: somente imagem da logo (assets/logo_aptus.png ou .jpg)."""
    uri = _logo_png_data_uri()
    if uri:
        return f'<div class="cab-logo"><img src="{uri}" class="logo-cab" alt="" /></div>'
    return """<div class="cab-logo cab-logo-aviso">
<p class="aviso-logo">Logo obrigatória — coloque <strong>assets/logo_aptus.png</strong> (ou .jpg) na pasta do programa.</p>
</div>"""


def _primeiro_caminho_logo_assets():
    """Caminho absoluto do ficheiro de logo em assets (png/jpg/jpeg)."""
    for base in _iter_bases_assets():
        pasta = os.path.join(base, "assets")
        for nome in ("logo_aptus.png", "logo_aptus.jpg", "logo_aptus.jpeg"):
            p = os.path.join(pasta, nome)
            if os.path.isfile(p):
                return os.path.normpath(p)
    return None


_pdf_arial_registo_feito = False


def _pdf_garantir_fontes_arial():
    """Regista Arial / Arial-Bold (pasta Fonts do Windows) para PDF."""
    global _pdf_arial_registo_feito
    if _pdf_arial_registo_feito:
        return
    _pdf_arial_registo_feito = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return
    try:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        arial = os.path.join(windir, "Fonts", "arial.ttf")
        arial_bd = os.path.join(windir, "Fonts", "arialbd.ttf")
        if os.path.isfile(arial):
            pdfmetrics.registerFont(TTFont("Arial", arial))
        if os.path.isfile(arial_bd):
            pdfmetrics.registerFont(TTFont("Arial-Bold", arial_bd))
    except Exception:
        pass


def _pdf_font_corpo():
    from reportlab.pdfbase import pdfmetrics

    _pdf_garantir_fontes_arial()
    return "Arial" if "Arial" in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _pdf_font_titulo_canvas():
    from reportlab.pdfbase import pdfmetrics

    _pdf_garantir_fontes_arial()
    return "Arial-Bold" if "Arial-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"


# Distância do topo da folha ao topo da logo (pt). Subir N linhas ≈ −N×11 neste valor.
_PDF_LOGO_TOPO_PT = 28.0


def _pdf_altura_logo_pt(pw, ph):
    """Altura efectiva da logo (pt) após escala — igual lógica a draw_fixed_header."""
    path = _primeiro_caminho_logo_assets()
    if not path:
        return 0.0
    try:
        from reportlab.lib.utils import ImageReader

        ir = ImageReader(path)
        iw, ih = ir.getSize()
        max_w = float(pw) - 72.0
        max_h = 112.0
        scale = min(max_w / float(iw), max_h / float(ih), 1.0)
        return float(ih * scale)
    except Exception:
        return 0.0


def _pdf_top_margin_corpo_pt():
    """
    Margem superior (pt) para o fluxo começar duas linhas (corpo 11 pt) abaixo do título
    desenhado no canvas (título a 3 linhas abaixo da base da logo).
    """
    from reportlab.lib.pagesizes import A4

    ph = float(A4[1])
    pw = float(A4[0])
    linha = 11.0
    y_topo_logo = ph - _PDF_LOGO_TOPO_PT
    altura = _pdf_altura_logo_pt(pw, ph)
    y_img = y_topo_logo - altura
    y_titulo_bl = y_img - 3.0 * linha
    # Duas linhas abaixo do título (12 pt): baseline do 1.º parágrafo do corpo
    y_corpo_bl = y_titulo_bl - 2.0 * linha - 12.0
    y_frame_top = y_corpo_bl + linha * 1.15
    top_m = ph - y_frame_top
    return max(150, int(round(top_m + 8)))


def draw_fixed_header(canvas, doc, titulo):
    """
    Cabeçalho fixo no canvas: logotipo Aptus + título do documento.
    Título: 3 linhas (11 pt) abaixo da base da logo; Arial 12 negrito.
    """
    try:
        from reportlab.lib.utils import ImageReader
    except ImportError:
        return
    _pdf_garantir_fontes_arial()
    pw, ph = float(doc.pagesize[0]), float(doc.pagesize[1])
    linha = 11.0
    y_topo_logo = ph - _PDF_LOGO_TOPO_PT
    path = _primeiro_caminho_logo_assets()
    canvas.saveState()
    if path:
        try:
            ir = ImageReader(path)
            iw, ih = ir.getSize()
            max_w = pw - 72.0
            max_h = 112.0
            scale = min(max_w / float(iw), max_h / float(ih), 1.0)
            largura = iw * scale
            altura = ih * scale
            x = (pw - largura) / 2.0
            y_img = y_topo_logo - altura
            canvas.drawImage(path, x, y_img, width=largura, height=altura, mask="auto")
        except Exception:
            y_img = y_topo_logo
            altura = 0.0
    else:
        y_img = y_topo_logo
        altura = 0.0

    titulo_txt = (titulo or "").strip().upper()
    if titulo_txt:
        y_titulo = y_img - 3.0 * linha
        canvas.setFont(_pdf_font_titulo_canvas(), 12)
        canvas.drawCentredString(pw / 2.0, y_titulo, titulo_txt)
    canvas.restoreState()


def footer(canvas, doc):
    """Rodapé fixo: linha horizontal + três linhas centradas (cinza escuro)."""
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor

    emp = DADOS_EMPRESA
    l1 = (emp.get("rodape_l1") or "").strip()
    l2 = (emp.get("rodape_l2") or emp.get("endereco", "") or "").strip()
    l3 = (emp.get("rodape_l3") or "").strip()
    lines = [ln.upper() for ln in (l1, l2, l3) if ln]
    if not lines:
        return
    pw = float(doc.pagesize[0])
    x_center = pw / 2.0
    leading = 10
    margem_h = 72.0
    cinza = HexColor("#4a4a4a")
    y_base = 0.75 * inch
    canvas.saveState()
    _pdf_garantir_fontes_arial()
    canvas.setFont(_pdf_font_corpo(), 8)
    canvas.setFillColor(cinza)
    n = len(lines)
    y_top_baseline = y_base + (n - 1) * leading
    # Linha fina acima do bloco de texto (dois pontos acima da 1.ª linha)
    y_sep = y_top_baseline + 9
    canvas.setStrokeColor(cinza)
    canvas.setLineWidth(0.6)
    canvas.line(margem_h, y_sep, pw - margem_h, y_sep)
    y = y_base
    for line in reversed(lines):
        canvas.drawCentredString(x_center, y, line)
        y += leading
    canvas.restoreState()


def _pdf_on_first_page_header_e_footer(titulo_doc):
    """Factory: 1.ª página com cabeçalho fixo (logo+título) + rodapé."""

    def _cb(canvas, doc):
        draw_fixed_header(canvas, doc, titulo_doc)
        footer(canvas, doc)

    return _cb


def _pdf_estilos_documento():
    """Corpo Arial 11 justificado (entrelinhas 1,5 ABNT); título em canvas 12 negrito."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT

    _pdf_garantir_fontes_arial()
    fn = _pdf_font_corpo()
    fn_b = _pdf_font_titulo_canvas()

    titulo = ParagraphStyle(
        name="TituloDocPdf",
        fontName=fn_b,
        fontSize=12,
        leading=14.4,
        alignment=TA_CENTER,
        spaceAfter=10,
    )
    corpo = ParagraphStyle(
        name="CorpoDocPdf",
        fontName=fn,
        fontSize=11,
        leading=16.5,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
        # Justificar também linhas após <br/>; última linha se tiver >2 palavras (ReportLab)
        justifyBreaks=1,
        justifyLastLine=2,
        # Não partir palavras ao meio para “encaixar” linhas
        splitLongWords=0,
        embeddedHyphenation=0,
    )
    centro = ParagraphStyle(
        name="CentroDocPdf",
        fontName=fn,
        fontSize=11,
        leading=16.5,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    corpo_esq = ParagraphStyle(
        name="CorpoEsqPdf",
        fontName=fn,
        fontSize=11,
        leading=16.5,
        alignment=TA_LEFT,
        spaceAfter=8,
        splitLongWords=0,
    )
    corpo_esq_continua = ParagraphStyle(
        name="CorpoEsqContinuaPdf",
        parent=corpo_esq,
        spaceBefore=-11,
        leading=16.5,
        spaceAfter=8,
    )
    data_dir = ParagraphStyle(
        name="DataDirPdf",
        fontName=fn,
        fontSize=11,
        leading=16.5,
        alignment=TA_RIGHT,
        spaceAfter=8,
        splitLongWords=0,
    )
    return {
        "titulo": titulo,
        "corpo": corpo,
        "centro": centro,
        "corpo_esq": corpo_esq,
        "corpo_esq_continua": corpo_esq_continua,
        "data_dir": data_dir,
    }


def _pdf_paragraph(texto, estilo):
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    s = texto if isinstance(texto, str) else str(texto or "")
    return Paragraph(escape(s).replace("\n", "<br/>"), estilo)


def _pdf_paragraph_corpo_varias_linhas(estilo_corpo, *linhas):
    """Várias linhas num só parágrafo com &lt;br/&gt; — justificação + justifyBreaks funcionam."""
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    t = "<br/>".join(escape(str(x or "")) for x in linhas)
    return Paragraph(t, estilo_corpo)


def _html_corpo_para_flowables(corpo_html, est):
    """
    Extrai blocos <p>...</p> para Paragraphs (est = dict com corpo, corpo_esq, centro).
    Romberg: linha-opcoes-romberg → esquerda.
    Comparecimento: linha-periodo-comparecimento → centro; texto-consulta-periodo-esq e texto-firma → esquerda.
    """
    import re
    from html import unescape
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    estilo_corpo = est["corpo"]
    out = []
    if not (corpo_html or "").strip():
        return out
    blocos = list(re.finditer(r"<p([^>]*)>(.*?)</p>", corpo_html, flags=re.I | re.S))
    if not blocos:
        t = re.sub(r"<[^>]+>", " ", corpo_html or "")
        t = " ".join(unescape(t).split())
        if t:
            out.append(Paragraph(escape(t), estilo_corpo))
        return out
    for m in blocos:
        attrs = m.group(1) or ""
        ch = m.group(2)
        if "linha-periodo-comparecimento" in attrs:
            para_est = est["centro"]
        elif "texto-consulta-periodo-esq" in attrs:
            para_est = est["corpo_esq_continua"]
        elif "texto-firma-comparecimento" in attrs:
            para_est = est["corpo_esq"]
        elif "linha-opcoes-romberg" in attrs:
            para_est = est["corpo_esq"]
        else:
            para_est = estilo_corpo
        t = re.sub(r"<[^>]+>", "", ch)
        t = unescape(t).replace("\xa0", " ").replace("&nbsp;", " ")
        t = " ".join(t.split())
        if t:
            out.append(Paragraph(escape(t), para_est))
    return out


def _story_bloco_assinatura_pdf(estilos):
    from reportlab.platypus import Spacer
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    st = ParagraphStyle(
        name="LegAssPdf",
        parent=estilos["centro"],
        fontSize=10,
        spaceBefore=4,
        alignment=TA_CENTER,
    )
    linha = ParagraphStyle(
        name="LinhaAssPdf",
        parent=estilos["centro"],
        fontSize=11,
        leading=14,
    )
    story = []
    story.append(Spacer(1, 1.0 * cm))
    story.append(_pdf_paragraph("_" * 52, linha))
    story.append(_pdf_paragraph("CARIMBO E ASSINATURA", st))
    return story


def _salvar_abrir_pdf_documento_clinico(story, nome_base_arquivo, titulo_cabecalho_canvas):
    """
    Monta o PDF: logo + título desenhados em draw_fixed_header na 1.ª página (canvas);
    rodapé (Dr./endereço/tel.) em footer no fundo em todas as páginas.
    titulo_cabecalho_canvas: mesmo texto do título (não repetir no story).
    """
    try:
        from reportlab.platypus import SimpleDocTemplate
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
    except ImportError as e:
        audit_db_failure("_salvar_abrir_pdf_documento_clinico", e, extra="import_reportlab")
        messagebox.showerror(
            "Dependência",
            "Instale o ReportLab para gerar PDF:\n\npip install reportlab",
        )
        return
    try:
        path = os.path.join(tempfile.gettempdir(), limpar_nome_arquivo(nome_base_arquivo) + ".pdf")
        _pdf_garantir_fontes_arial()
        top_m = _pdf_top_margin_corpo_pt()
        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            leftMargin=3 * cm,
            rightMargin=2 * cm,
            topMargin=top_m,
            bottomMargin=3.0 * cm,
        )
        doc.build(
            story,
            onFirstPage=_pdf_on_first_page_header_e_footer(titulo_cabecalho_canvas),
            onLaterPages=footer,
        )
        if os.name == "nt":
            os.startfile(path)
        else:
            os.system(f'xdg-open "{path}"')
        show_status("Documento PDF aberto.")
    except OSError as e:
        audit_db_failure("_salvar_abrir_pdf_documento_clinico", e, extra="filesystem")
        messagebox.showerror(
            "Documento PDF",
            "Não foi possível gravar ou abrir o PDF (disco, permissões ou caminho).\n\n"
            "Verifique espaço em disco e tente novamente.",
        )
    except Exception as e:
        audit_db_failure("_salvar_abrir_pdf_documento_clinico", e)
        messagebox.showerror(
            "Documento PDF",
            "Não foi possível gerar o documento. Tente novamente.\n\n"
            "Se o erro continuar, contacte o suporte.",
        )


def _montar_story_documento_generico_pdf(titulo_pagina, corpo_html):
    """Declaração / Romberg / comparecimento — Platypus + assinatura (rodapé em canvas)."""
    from reportlab.platypus import Spacer
    from reportlab.lib.units import cm

    est = _pdf_estilos_documento()
    story = []
    story.append(Spacer(1, 0.15 * cm))
    story.extend(_html_corpo_para_flowables(corpo_html, est))
    story.append(Spacer(1, 1.8 * cm))
    story.append(_pdf_paragraph(_data_linha_documentos(), est["data_dir"]))
    story.extend(_story_bloco_assinatura_pdf(est))
    return story


def _montar_story_acuidade_visual_pdf(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    _ = rqe
    from reportlab.platypus import Spacer
    from reportlab.lib.units import cm

    data_linha = _data_linha_documentos()
    np = (nome_paciente or "").strip().upper()
    nm = nome_med or ""
    uf_c = uf or "RO"
    crm_raw = (crm or "").strip()
    crm_part = crm_raw if crm_raw else "_____"
    est = _pdf_estilos_documento()
    story = [
        Spacer(1, 0.1 * cm),
        _pdf_paragraph_corpo_varias_linhas(
            est["corpo"],
            f"Eu, Dr(a). {nm}, inscrito(a) no Conselho Regional de Medicina",
            f"sob o CRM nº {crm_part}/{uf_c}, declaro para os devidos fins que examinei o(a)",
            f"Sr(a). {np}, apresentando visão:",
        ),
        Spacer(1, 0.2 * cm),
        _pdf_paragraph("OD: _____________________ | OE: _____________________", est["corpo_esq"]),
        Spacer(1, 0.15 * cm),
        _pdf_paragraph(
            "( ) Normal / Sem correção ( ) Com correção (uso de lentes/óculos)",
            est["corpo_esq"],
        ),
        _pdf_paragraph("Estando, assim, apto(a) para as suas atividades laborais.", est["corpo_esq"]),
        Spacer(1, 1.5 * cm),
        _pdf_paragraph(data_linha, est["data_dir"]),
    ]
    story.extend(_story_bloco_assinatura_pdf(est))
    return story


def _montar_story_acuidade_ishihara_pdf(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    _ = rqe
    from reportlab.platypus import Spacer
    from reportlab.lib.units import cm

    data_linha = _data_linha_documentos()
    np = (nome_paciente or "").strip().upper()
    nm = nome_med or ""
    uf_c = uf or "RO"
    crm_raw = (crm or "").strip()
    crm_part = crm_raw if crm_raw else "_____"
    est = _pdf_estilos_documento()
    story = [
        Spacer(1, 0.1 * cm),
        _pdf_paragraph_corpo_varias_linhas(
            est["corpo"],
            f"Eu, Dr(a). {nm}, inscrito(a) no Conselho Regional de Medicina",
            f"sob o CRM nº {crm_part}/{uf_c}, declaro para os devidos fins que examinei o(a)",
            f"Sr(a). {np}, apresentando visão:",
        ),
        _pdf_paragraph("1. ACUIDADE VISUAL:", est["corpo_esq"]),
        Spacer(1, 0.15 * cm),
        _pdf_paragraph("OD: _____________________ | OE: _____________________", est["corpo_esq"]),
        _pdf_paragraph(
            "( ) Normal / Sem correção ( ) Com correção (uso de lentes/óculos)",
            est["corpo_esq"],
        ),
        Spacer(1, 0.2 * cm),
        _pdf_paragraph("2. TESTE DE ISHIHARA", est["corpo_esq"]),
        _pdf_paragraph("(   ) Normal (sem alterações na percepção de cores)", est["corpo_esq"]),
        _pdf_paragraph("(   ) Alterado: _______________________________", est["corpo_esq"]),
        _pdf_paragraph("Estando, assim, apto(a) para as suas atividades laborais.", est["corpo_esq"]),
        Spacer(1, 1.4 * cm),
        _pdf_paragraph(data_linha, est["data_dir"]),
    ]
    story.extend(_story_bloco_assinatura_pdf(est))
    return story


def _montar_story_atestado_fisico_mental_pdf(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    from reportlab.platypus import Spacer
    from reportlab.lib.units import cm

    np = (nome_paciente or "").strip().upper()
    cpf_disp = (cpf_txt or "").strip()
    if not cpf_disp or cpf_disp == "—":
        cpf_e = "000.000.000-00"
    else:
        cpf_e = cpf_disp
    nm = nome_med or ""
    frase = _frase_inscricao_crm_rqe_pdf(crm, uf, rqe)
    est = _pdf_estilos_documento()
    corpo = (
        f"Eu, Dr(a). {nm}, {frase} {np}, inscrito(a) no CPF sob nº {cpf_e}, "
        f"foi por mim examinado(a) e, no momento, goza de boa saúde física e mental, "
        f"estando APTO(A) para exercer sua atividade laboral."
    )
    story = [
        Spacer(1, 0.1 * cm),
        _pdf_paragraph(corpo, est["corpo"]),
        Spacer(1, 1.6 * cm),
        _pdf_paragraph(_data_linha_documentos(), est["data_dir"]),
    ]
    story.extend(_story_bloco_assinatura_pdf(est))
    return story


def _abrir_pdf_declaracao_ou_romberg(titulo_pagina, corpo_html):
    """Declaração / Romberg / comparecimento — cabeçalho (logo+título) no canvas."""
    story = _montar_story_documento_generico_pdf(titulo_pagina, corpo_html)
    _salvar_abrir_pdf_documento_clinico(
        story,
        f"doc_{titulo_pagina}",
        titulo_pagina.strip().upper(),
    )


def _html_rodape_fixo_abnt():
    """Rodapé — 3 linhas fixas, maiúsculas e 10pt via CSS."""
    emp = DADOS_EMPRESA
    l1 = _html_esc_doc(emp.get("rodape_l1") or "")
    l2 = _html_esc_doc(emp.get("rodape_l2") or emp.get("endereco", ""))
    l3 = _html_esc_doc(emp.get("rodape_l3") or "")
    return f"""
<footer class="rodape-abnt">
  <p class="rodape-linha">{l1}</p>
  <p class="rodape-linha">{l2}</p>
  <p class="rodape-linha">{l3}</p>
</footer>"""


def _html_bloco_assinatura_abnt():
    """Linha de assinatura + legenda (espaçamento anterior no CSS)."""
    return """
<div class="bloco-assinatura">
  <div class="linha-assinatura"></div>
  <p class="legenda-assinatura">CARIMBO E ASSINATURA</p>
</div>"""


def _css_documentos_abnt():
    """CSS único: margens ABNT-like, Arial 12 corpo / 14 título, corpo 1,5 entrelinhas, só título em negrito."""
    return """
@page { size: A4; margin: 3cm 2cm 2cm 3cm; }
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: #111;
  font-size: 12pt;
  line-height: 1.5;
  background: #f0f0f0;
}
/* Folha: altura mínima A4 + space-between empurra o rodapé para o fim da página (não “no meio”). */
.doc-shell {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: stretch;
  min-height: 297mm;
  max-width: 210mm;
  margin: 0 auto;
  padding: 0.2cm 2cm 2cm 3cm;
  background: #fff;
  box-shadow: 0 0 6px rgba(0,0,0,.08);
}
.doc-main {
  display: block;
  width: 100%;
  flex: 0 0 auto;
}
.cab-logo { text-align: center; width: 100%; margin: 0; padding: 0; page-break-after: avoid; break-after: avoid-page; page-break-inside: avoid; break-inside: avoid; }
/* block: evita “buraco” de baseline abaixo de img inline / inline-block que empurra o título */
.cab-logo .logo-cab { max-height: 200px; max-width: 85%; width: auto; height: auto; display: block; margin: 0 auto; object-fit: contain; }
.cab-logo-aviso { padding: 8px; border: 1px dashed #c00; color: #a00; font-size: 11px; font-weight: normal; }
.aviso-logo { margin: 0; line-height: 1.5; }
.aviso-logo strong { font-weight: normal; }
/* Espaço reduzido após a logo (evita título “longe” do topo). Impressão ajusta em @media print. */
.gap-3linhas { min-height: 1em; height: 1em; flex-shrink: 0; }
.gap-pos-logo { min-height: 0.85em; height: 0.85em; flex-shrink: 0; }
.gap-5linhas { min-height: 5em; height: 5em; flex-shrink: 0; width: 100%; }
h1.titulo-doc {
  text-align: center;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 14pt;
  font-weight: 700;
  margin: 0;
  padding: 0;
  letter-spacing: 0.4px;
  page-break-after: avoid;
}
.corpo-doc {
  text-align: justify !important;
  text-justify: inter-word;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 12pt;
  line-height: 1.5;
  hyphens: none;
  -webkit-hyphens: none;
  -ms-hyphens: none;
  hyphenate-character: "";
  page-break-before: avoid;
  break-before: avoid-page;
}
/* Linha OD | OE — fileira única; largura total limitada para linhas de preenchimento mais curtas */
.linha-odoe-wrap {
  display: flex;
  flex-wrap: nowrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.4em;
  width: 100%;
  max-width: 68%;
  margin: 10px 0;
  font-size: 12pt;
  line-height: 1.5;
  text-align: left;
}
.linha-odoe-wrap .odoe-esq,
.linha-odoe-wrap .odoe-dir {
  display: flex;
  align-items: flex-end;
  gap: 0.25em;
  flex: 1 1 0;
  min-width: 0;
  max-width: 48%;
}
.linha-odoe-wrap .odoe-preench {
  flex: 1 1 auto;
  border-bottom: 1px solid #000;
  min-height: 1.15em;
  min-width: 0;
  max-width: 100%;
}
.linha-odoe-wrap .odoe-sep {
  flex: 0 0 auto;
  flex-shrink: 0;
  padding: 0 0.15em 0.1em;
  line-height: 1;
  align-self: flex-end;
}
.corpo-doc strong { font-weight: normal; }
/* Justificado sem hifenização: não cortar palavras (ex.: SER-GIO). */
.corpo-doc p, .corpo-doc li {
  margin: 0 0 0.55em;
  hyphens: none !important;
  -webkit-hyphens: none !important;
  word-break: normal;
  overflow-wrap: normal;
}
.corpo-doc p.texto-comparecimento { text-align: justify; text-justify: inter-word; }
.corpo-doc .nb-doc { white-space: nowrap; font-weight: normal; }
/* Espaço fixo entre a data e o bloco CARIMBO E ASSINATURA (5 linhas a entrelinhas 1,5) */
.gap-data-assinatura { min-height: 7.5em; height: 7.5em; flex-shrink: 0; }
.gap-15linhas { min-height: 15em; margin-top: 1.5em; flex-shrink: 0; }
.bloco-assinatura { text-align: center; margin-bottom: 2mm; page-break-inside: avoid; }
.linha-assinatura { border: none; border-top: 1px solid #000; width: 62%; margin: 0 auto; }
.legenda-assinatura { font-size: 10pt; margin: 6px 0 0; letter-spacing: 0.3px; font-weight: normal; }
.doc-shell > footer.rodape-abnt { margin-top: 0; }
.rodape-abnt {
  flex-shrink: 0;
  margin-top: 0;
  padding-top: 8px;
  border-top: 1px solid #888;
  text-align: center;
  font-size: 8pt;
  line-height: 1.35;
  color: #111;
  page-break-inside: avoid;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.rodape-linha { margin: 2px 0; }
.data-local-doc { text-align: right; font-size: 12pt; line-height: 1.5; margin: 0; font-weight: normal; }
.linha-periodo-comparecimento { margin-top: 0.75em; text-align: center; letter-spacing: 0.03em; }
.linha-opcoes-romberg { margin: 0.2em 0; text-align: left; letter-spacing: 0.03em; }
@media print {
  html, body { height: auto !important; overflow: visible !important; background: #fff !important; }
  body { padding: 0 !important; }
  .doc-shell {
    box-shadow: none !important;
    padding: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
    /* A4 menos margens @page (3cm+2cm) ≈ altura útil do texto */
    min-height: 245mm !important;
    height: auto !important;
    max-width: 100% !important;
  }
  .doc-main {
    display: block !important;
    flex: 0 0 auto !important;
  }
  .rodape-abnt {
    margin-top: 0 !important;
    page-break-inside: avoid;
  }
  .cab-logo { page-break-after: avoid; break-inside: avoid; margin: 0 !important; padding: 0 !important; }
  .cab-logo .logo-cab { max-height: 200px; max-width: 85%; }
  .gap-3linhas { min-height: 1em !important; height: 1em !important; }
  .gap-5linhas { min-height: 2em !important; height: 2em !important; }
  .gap-data-assinatura { min-height: 7.5em !important; height: 7.5em !important; }
  .gap-15linhas { min-height: 5em !important; margin-top: 0.6em !important; }
  h1.titulo-doc { page-break-after: avoid; }
  .corpo-doc { page-break-before: avoid; }
}
"""


def _html_fragmento_logo_aptus():
    """Compatível: mesmo que cabeçalho só logo."""
    return _html_cabecalho_so_logo()


def _montar_html_acuidade_visual(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    """Acuidade visual — sem CPF no texto (CPF só em Declaração e Atestado)."""
    _ = rqe
    data_linha = _html_esc_doc(_data_linha_documentos())
    np = _html_esc_doc((nome_paciente or "").strip().upper())
    nm = _html_esc_doc(nome_med)
    uf_c = _html_esc_doc(uf or "RO")
    crm_raw = (crm or "").strip()
    crm_e = _html_esc_doc(crm_raw) if crm_raw else ""
    if crm_e:
        crm_frase = f"sob o CRM nº {crm_e}/{uf_c}"
    else:
        crm_frase = "sob o CRM nº _____/_____"
    cab = _html_cabecalho_so_logo()
    rod = _html_rodape_fixo_abnt()
    assin = _html_bloco_assinatura_abnt()
    css = _css_documentos_abnt()
    extra = """
.checks-ac { margin: 12px 0; font-size: 11.5pt; line-height: 1.7; white-space: pre-wrap; }
.conclusao { margin: 10px 0; font-weight: normal; }
"""
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Acuidade Visual — APTUS</title>
<style>{css}{extra}</style></head><body>
<div class="doc-shell">
<div class="doc-main">
{cab}
<div class="gap-3linhas"></div>
<h1 class="titulo-doc">ACUIDADE VISUAL</h1>
<div class="gap-3linhas"></div>
<div class="corpo-doc">
<p>
Eu, Dr(a). {nm}, inscrito(a) no Conselho Regional de Medicina {crm_frase}, declaro para os devidos fins que examinei o(a) Sr(a). {np}, apresentando visão:
</p>
<div class="linha-odoe-wrap" aria-label="Acuidade OD e OE">
  <div class="odoe-esq">OD:<span class="odoe-preench"></span></div>
  <span class="odoe-sep">|</span>
  <div class="odoe-dir">OE:<span class="odoe-preench"></span></div>
</div>
<p class="checks-ac">(&nbsp;&nbsp;) Normal / Sem correção &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(&nbsp;&nbsp;) Com correção (uso de lentes/óculos)</p>
<p class="conclusao">Estando, assim, apto(a) para as suas atividades laborais.</p>
<div class="gap-5linhas"></div>
<p class="data-local-doc">{data_linha}</p>
</div>
<div class="gap-data-assinatura"></div>
{assin}
</div>
{rod}
</div>
</body></html>"""


def _montar_html_acuidade_ishihara(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    """Acuidade visual + teste de Ishihara — mesmo padrão de cabeçalho/rodapé dos demais documentos."""
    _ = rqe  # modelo atual usa só CRM/UF no texto principal
    data_linha = _html_esc_doc(_data_linha_documentos())
    np = _html_esc_doc((nome_paciente or "").strip().upper())
    nm = _html_esc_doc(nome_med)
    uf_c = _html_esc_doc(uf or "RO")
    crm_raw = (crm or "").strip()
    crm_e = _html_esc_doc(crm_raw) if crm_raw else ""
    if crm_e:
        crm_frase_inicio = f"sob o CRM nº {crm_e}/{uf_c}"
    else:
        crm_frase_inicio = "sob o CRM nº _____/_____"
    cab = _html_cabecalho_so_logo()
    rod = _html_rodape_fixo_abnt()
    assin = _html_bloco_assinatura_abnt()
    css = _css_documentos_abnt()
    extra = """
.sec-numero { margin: 14px 0 6px; font-size: 12pt; font-weight: normal; }
.checks-ish { margin: 10px 0; font-size: 11.5pt; line-height: 1.65; }
.ish-opcoes { margin: 10px 0 6px; font-size: 11.5pt; line-height: 1.6; }
.linha-alterado { margin: 8px 0; font-size: 11.5pt; }
.conclusao { margin: 14px 0 0; font-weight: normal; }
"""
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Acuidade Visual e Ishihara — APTUS</title>
<style>{css}{extra}</style></head><body>
<div class="doc-shell">
<div class="doc-main">
{cab}
<div class="gap-3linhas"></div>
<h1 class="titulo-doc">ACUIDADE VISUAL E ISHIHARA</h1>
<div class="gap-3linhas"></div>
<div class="corpo-doc">
<p>
Eu, Dr(a). {nm}, inscrito(a) no Conselho Regional de Medicina {crm_frase_inicio}, declaro para os devidos fins que examinei o(a) Sr(a). {np}, apresentando visão:
</p>
<p class="sec-numero">1. ACUIDADE VISUAL:</p>
<div class="linha-odoe-wrap" aria-label="Acuidade OD e OE">
  <div class="odoe-esq">OD:<span class="odoe-preench"></span></div>
  <span class="odoe-sep">|</span>
  <div class="odoe-dir">OE:<span class="odoe-preench"></span></div>
</div>
<p class="checks-ish">
(&nbsp;&nbsp;) Normal / Sem correção &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
(&nbsp;&nbsp;) Com correção (uso de lentes/óculos)
</p>
<p class="sec-numero">2. TESTE DE ISHIHARA</p>
<p class="ish-opcoes">(&nbsp;) Normal (sem alterações na percepção de cores)</p>
<p class="linha-alterado">(&nbsp;) Alterado: _______________________________</p>
<p class="conclusao">Estando, assim, apto(a) para as suas atividades laborais.</p>
<div class="gap-5linhas"></div>
<p class="data-local-doc">{data_linha}</p>
</div>
<div class="gap-data-assinatura"></div>
{assin}
</div>
{rod}
</div>
</body></html>"""


def _montar_html_atestado_fisico_mental(nome_paciente, cpf_txt, nome_med, crm, uf, rqe):
    """Atestado físico e mental — paciente com CPF no texto; rodapé fixo."""
    np = _html_esc_doc((nome_paciente or "").strip().upper())
    cpf_disp = (cpf_txt or "").strip()
    if not cpf_disp or cpf_disp == "—":
        cpf_e = "000.000.000-00"
    else:
        cpf_e = _html_esc_doc(cpf_disp)
    nm = _html_esc_doc(nome_med)
    frase = _frase_inscricao_crm_rqe(crm, uf, rqe)
    data_linha = _html_esc_doc(_data_linha_documentos())
    cab = _html_cabecalho_so_logo()
    rod = _html_rodape_fixo_abnt()
    assin = _html_bloco_assinatura_abnt()
    css = _css_documentos_abnt()
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Atestado Físico e Mental — APTUS</title>
<style>{css}</style></head><body>
<div class="doc-shell">
<div class="doc-main">
{cab}
<div class="gap-3linhas"></div>
<h1 class="titulo-doc">ATESTADO FÍSICO E MENTAL</h1>
<div class="gap-3linhas"></div>
<div class="corpo-doc">
<p>
Eu, Dr(a). {nm}, {frase} {np}, inscrito(a) no CPF sob nº {cpf_e}, foi por mim examinado(a) e, no momento, goza de boa saúde física e mental, estando APTO(A) para exercer sua atividade laboral.
</p>
<div class="gap-5linhas"></div>
<p class="data-local-doc">{data_linha}</p>
</div>
<div class="gap-data-assinatura"></div>
{assin}
</div>
{rod}
</div>
</body></html>"""


def atualizar_aba_documentos():
    """Recarrega a lista de médicos na aba Documentos."""
    global _cb_medico_doc, _medicos_doc_lookup
    try:
        rows = executar_query(
            """SELECT id, nome, COALESCE(TRIM(crm),''), COALESCE(TRIM(uf_crm),''),
                      COALESCE(TRIM(rqe),'')
               FROM medicos WHERE ativo IS NOT FALSE ORDER BY nome""",
            fetch=True,
        ) or []
        # Se a query com RQE falhou (coluna inexistente em base antiga), tenta sem RQE
        if not rows:
            rows_simples = executar_query(
                """SELECT id, nome, COALESCE(TRIM(crm),''), COALESCE(TRIM(uf_crm),'')
                   FROM medicos WHERE ativo IS NOT FALSE ORDER BY nome""",
                fetch=True,
            ) or []
            rows = [(r[0], r[1], r[2], r[3], "") for r in rows_simples]
        _medicos_doc_lookup = {}
        vals = []
        for _rid, nome, crm, uf, rqe in rows:
            uf = uf or "RO"
            if crm:
                disp = f"{nome} — CRM {crm}/{uf}"
            else:
                disp = f"{nome} — CRM S/N/{uf}"
            if rqe:
                disp += f" — RQE {rqe}"
            vals.append(disp)
            _medicos_doc_lookup[disp] = (nome, crm or "", uf, rqe or "")
        if _cb_medico_doc:
            _cb_medico_doc.configure(values=vals if vals else ["(cadastre médicos na tabela medicos)"])
            if vals:
                _cb_medico_doc.set(vals[0])
        if not vals:
            log("Aba Documentos: nenhum médico retornado do banco (verifique conexão e inicializar_banco).")
    except Exception as e:
        log(f"Erro atualizar médicos documentos: {e}")


def emitir_documento_clinico(tipo):
    """tipo: comparecimento | acuidade | acuidade_ishihara | romberg | atestado"""
    global _ent_nome_doc, _ent_cpf_doc, _cb_medico_doc, _medicos_doc_lookup, _var_periodo_doc
    nome = (_ent_nome_doc.get() or "").strip()
    if len(nome) < 2:
        messagebox.showwarning("Atenção", "Informe o nome do paciente/colaborador (mín. 2 caracteres).")
        return
    cpf_raw = re.sub(r"[^\d]", "", (_ent_cpf_doc.get() or ""))
    cpf_txt = formatar_cpf(cpf_raw) if len(cpf_raw) == 11 else (_ent_cpf_doc.get() or "").strip() or "—"
    med_key = (_cb_medico_doc.get() or "").strip() if _cb_medico_doc else ""
    if med_key.startswith("("):
        messagebox.showwarning("Atenção", "Cadastre ao menos um médico na tabela medicos (banco de dados).")
        return
    if not logo_documentos_configurada():
        messagebox.showerror("Logo obrigatória", _texto_local_logo_documentos())
        return
    md = _medicos_doc_lookup.get(med_key, (med_key, "", "", ""))
    nome_med = md[0]
    crm = md[1] if len(md) > 1 else ""
    uf = md[2] if len(md) > 2 else ""
    rqe = md[3] if len(md) > 3 else ""

    n_plain = (nome or "").strip().upper()

    try:
        if tipo == "comparecimento":
            tit = "DECLARAÇÃO DE COMPARECIMENTO"
            cpf_cmp = formatar_cpf(cpf_raw) if len(cpf_raw) == 11 else "000.000.000-00"
            try:
                per = _var_periodo_doc.get() if _var_periodo_doc else "matutino"
            except Exception:
                per = "matutino"
            if per not in ("matutino", "vespertino"):
                per = "matutino"
            if per == "matutino":
                linha_per = '<p class="linha-periodo-comparecimento">(X) MATUTINO &nbsp;&nbsp;&nbsp; ( ) VESPERTINO</p>'
            else:
                linha_per = '<p class="linha-periodo-comparecimento">( ) MATUTINO &nbsp;&nbsp;&nbsp; (X) VESPERTINO</p>'
            corpo = f"""
<p class="texto-comparecimento">Declaro, para os devidos fins, que o(a) Sr(a). {n_plain}, inscrito(a) no CPF sob o nº {cpf_cmp}, compareceu a esta clínica para a realização </p>
<p class="texto-consulta-periodo-esq">de consulta médica nesta data, no período:</p>
{linha_per}
<p class="texto-firma-comparecimento">E, por ser verdade, firmo a presente.</p>
"""
        elif tipo == "acuidade":
            story = _montar_story_acuidade_visual_pdf(nome, cpf_txt, nome_med, crm, uf, rqe)
            _salvar_abrir_pdf_documento_clinico(story, "Acuidade_Visual_APTUS", "ACUIDADE VISUAL")
            return
        elif tipo == "acuidade_ishihara":
            story = _montar_story_acuidade_ishihara_pdf(nome, cpf_txt, nome_med, crm, uf, rqe)
            _salvar_abrir_pdf_documento_clinico(story, "Acuidade_Visual_Ishihara_APTUS", "ACUIDADE VISUAL E ISHIHARA")
            return
        elif tipo == "romberg":
            tit = "TESTE DE ROMBERG"
            cpf_rom = formatar_cpf(cpf_raw) if len(cpf_raw) == 11 else "000.000.000-00"
            corpo = f"""
<p class="texto-comparecimento">Declaro que o(a) Sr(a). {n_plain}, CPF: {cpf_rom}, foi submetido ao Teste de Romberg, apresentando resultado:</p>
<p class="linha-opcoes-romberg">(&nbsp;&nbsp;&nbsp;) NEGATIVO (Normal)</p>
<p class="linha-opcoes-romberg">(&nbsp;&nbsp;&nbsp;) POSITIVO (Alterado)</p>
<p class="texto-comparecimento">O(a) examinado(a) encontra-se APTO(A) para sua atividade laboral.</p>
"""
        elif tipo == "atestado":
            story = _montar_story_atestado_fisico_mental_pdf(nome, cpf_txt, nome_med, crm, uf, rqe)
            _salvar_abrir_pdf_documento_clinico(story, "Atestado_Fisico_Mental_APTUS", "ATESTADO FÍSICO E MENTAL")
            return
        else:
            return
        _abrir_pdf_declaracao_ou_romberg(tit, corpo)
    except Exception as e:
        audit_db_failure("emitir_documento_clinico", e)
        messagebox.showerror(
            "Documento clínico",
            "Não foi possível concluir o documento. Verifique os dados e tente novamente.\n\n"
            "Se o erro continuar, contacte o suporte.",
        )
        traceback.print_exc()


# =============================================================================
# VENCIMENTOS ASO
# =============================================================================

def atualizar_cards_vencimentos():
    """
    Aba Vencimentos ASO — exibe cada colaborador individualmente
    com empresa, CPF, data do ASO, data de vencimento e dias restantes.
    Filtros: TODOS | VENCIDOS | ATÉ 60 DIAS | ATÉ 90 DIAS | EM DIA
    """
    try:
        if not scroll_vencimentos:
            return
        for w in scroll_vencimentos.winfo_children():
            w.destroy()

        # ── Buscar todos os colaboradores com ASO ─────────────────────────────
        rows = executar_query("""
            SELECT
                a.id,
                a.colaborador,
                a.cpf_colaborador,
                COALESCE(e.nome, a.empresa_id::TEXT, 'N/A') AS empresa,
                a.data_atendimento,
                a.data_vencimento_aso,
                a.modo,
                (a.data_vencimento_aso - CURRENT_DATE) AS dias_restantes
            FROM atendimentos a
            LEFT JOIN empresas e ON a.empresa_id = e.id
            WHERE a.data_vencimento_aso IS NOT NULL
              AND a.status = 'ATIVO'
              AND a.modo IN ('ADM','PERIO','RT','DEMI')
            ORDER BY a.data_vencimento_aso ASC
        """, fetch=True)

        if not rows:
            ctk.CTkLabel(scroll_vencimentos, text="📋 Nenhum ASO cadastrado ainda.",
                         font=("Arial", 14, "bold"), text_color="#6c757d").pack(pady=40)
            return

        # ── Contadores para o resumo ──────────────────────────────────────────
        total_venc = sum(1 for r in rows if (r[7] or 0) < 0)
        total_p60  = sum(1 for r in rows if 0 <= (r[7] or 0) <= 60)
        total_p90  = sum(1 for r in rows if 60 < (r[7] or 0) <= 90)
        total_ok   = sum(1 for r in rows if (r[7] or 0) > 90)

        # ── CABEÇALHO ─────────────────────────────────────────────────────────
        f_hdr = ctk.CTkFrame(scroll_vencimentos, fg_color="#1f4e79", corner_radius=8)
        f_hdr.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(f_hdr, text="📅  CONTROLE DE VENCIMENTOS ASO — DETALHADO",
                     font=("Arial", 15, "bold"), text_color="white").pack(side="left", padx=16, pady=10)
        ctk.CTkLabel(f_hdr, text=f"Total: {len(rows)} colaboradores",
                     font=("Arial", 12), text_color="#adb5bd").pack(side="right", padx=16)

        # ── CARDS DE RESUMO ───────────────────────────────────────────────────
        f_resumo = ctk.CTkFrame(scroll_vencimentos, fg_color="transparent")
        f_resumo.pack(fill="x", padx=8, pady=6)
        for val, lbl, cor in [
            (total_venc, "🚨 VENCIDOS",   "#dc3545"),
            (total_p60,  "⚠️ ATÉ 60 DIAS","#fd7e14"),
            (total_p90,  "📅 ATÉ 90 DIAS","#ffc107"),
            (total_ok,   "✅ EM DIA",      "#28a745"),
        ]:
            fc = ctk.CTkFrame(f_resumo, fg_color=cor, corner_radius=10, width=160, height=70)
            fc.pack(side="left", padx=6); fc.pack_propagate(False)
            ctk.CTkLabel(fc, text=str(val), font=("Arial", 26, "bold"), text_color="white").pack(pady=(8,0))
            ctk.CTkLabel(fc, text=lbl, font=("Arial", 10, "bold"), text_color="white").pack()

        # ── FILTRO ────────────────────────────────────────────────────────────
        f_filtro = ctk.CTkFrame(scroll_vencimentos, fg_color="#f0f4f8", corner_radius=8)
        f_filtro.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(f_filtro, text="🔍 Filtrar:", font=("Arial", 11, "bold")).pack(side="left", padx=10, pady=8)

        _filtro_ativo = {"v": "TODOS"}

        def _aplicar_filtro(filtro):
            _filtro_ativo["v"] = filtro
            _renderizar_lista(filtro)

        for txt, val in [("TODOS","TODOS"),("🚨 VENCIDOS","VENCIDOS"),
                          ("⚠️ 60 DIAS","P60"),("📅 90 DIAS","P90"),("✅ EM DIA","OK")]:
            ctk.CTkButton(f_filtro, text=txt, width=110, height=28,
                          font=("Arial", 10, "bold"), fg_color="#34495E",
                          command=lambda v=val: _aplicar_filtro(v)).pack(side="left", padx=4, pady=6)

        # ── CABEÇALHO DA TABELA ───────────────────────────────────────────────
        f_tbl_hdr = ctk.CTkFrame(scroll_vencimentos, fg_color="#001F3F", height=36)
        f_tbl_hdr.pack(fill="x", padx=8, pady=(4,0))
        f_tbl_hdr.pack_propagate(False)
        TCOLS = [("COLABORADOR",220,"w"),("CPF",120,"w"),("EMPRESA",160,"w"),
                 ("TIPO",60,"center"),("DATA ASO",100,"center"),
                 ("VENCIMENTO",100,"center"),("DIAS",80,"center"),("STATUS",110,"center")]
        for txt, w, anc in TCOLS:
            ctk.CTkLabel(f_tbl_hdr, text=txt, font=("Arial", 10, "bold"),
                         text_color="white", width=w, anchor=anc).pack(side="left", padx=4, pady=8)

        # ── CONTAINER DAS LINHAS ──────────────────────────────────────────────
        f_lista = ctk.CTkFrame(scroll_vencimentos, fg_color="transparent")
        f_lista.pack(fill="x", padx=8)

        def _renderizar_lista(filtro="TODOS"):
            for w in f_lista.winfo_children():
                w.destroy()

            for r in rows:
                aid, colab, cpf, empresa, dt_aso, dt_venc, modo, dias = r
                dias = int(dias) if dias is not None else 0

                # Aplicar filtro
                if filtro == "VENCIDOS" and dias >= 0: continue
                if filtro == "P60"      and not (0 <= dias <= 60): continue
                if filtro == "P90"      and not (60 < dias <= 90): continue
                if filtro == "OK"       and dias <= 90: continue

                # Cor e status por urgência
                if dias < 0:
                    cor_linha = "#FADBD8"; cor_badge = "#dc3545"; status_txt = f"VENCIDO {abs(dias)}d"
                elif dias <= 30:
                    cor_linha = "#FDEBD0"; cor_badge = "#e74c3c"; status_txt = f"URGENTE {dias}d"
                elif dias <= 60:
                    cor_linha = "#FEF9E7"; cor_badge = "#fd7e14"; status_txt = f"ATENÇÃO {dias}d"
                elif dias <= 90:
                    cor_linha = "#FFFDE7"; cor_badge = "#ffc107"; status_txt = f"PRÓXIMO {dias}d"
                else:
                    cor_linha = "#EAFAF1"; cor_badge = "#28a745"; status_txt = f"OK {dias}d"

                linha = ctk.CTkFrame(f_lista, fg_color=cor_linha, height=44, corner_radius=4)
                linha.pack(fill="x", pady=1)
                linha.pack_propagate(False)

                dt_aso_str  = dt_aso.strftime("%d/%m/%Y")  if dt_aso  else "—"
                dt_venc_str = dt_venc.strftime("%d/%m/%Y") if dt_venc else "—"
                cpf_fmt = formatar_cpf(cpf) if cpf else "—"

                vals = [(colab or "—", 220, "w", ("Arial",11,"bold"), "#2C3E50"),
                        (cpf_fmt,       120, "w", ("Arial",10),       "#555"),
                        (empresa or "—",160, "w", ("Arial",10),       "#333"),
                        (modo or "—",    60, "center", ("Arial",10),  "#555"),
                        (dt_aso_str,    100, "center", ("Arial",10),  "#333"),
                        (dt_venc_str,   100, "center", ("Arial",10,"bold"), "#333"),
                       ]
                for txt, w, anc, fnt, tc in vals:
                    ctk.CTkLabel(linha, text=str(txt)[:22], width=w, font=fnt,
                                 text_color=tc, anchor=anc).pack(side="left", padx=4)

                # Dias restantes
                ctk.CTkLabel(linha, text=str(abs(dias)), width=80,
                             font=("Arial",11,"bold"), text_color=cor_badge,
                             anchor="center").pack(side="left", padx=4)

                # Badge de status
                badge = ctk.CTkFrame(linha, fg_color=cor_badge, corner_radius=6, width=105, height=28)
                badge.pack(side="left", padx=4, pady=8); badge.pack_propagate(False)
                ctk.CTkLabel(badge, text=status_txt, font=("Arial",9,"bold"),
                             text_color="white").pack(expand=True)

        _renderizar_lista("TODOS")

    except Exception as e:
        log(f"Erro vencimentos: {e}")
        import traceback; traceback.print_exc()


# =============================================================================
# DASHBOARD — Visão geral do sistema
# =============================================================================

def atualizar_dashboard():
    """Dashboard com totais do dia, mês, alertas de ASO e resumo financeiro."""
    global frame_dashboard
    try:
        if not frame_dashboard:
            return
        # Limpar conteúdo anterior (exceto header)
        for w in frame_dashboard.winfo_children():
            w.destroy()

        # ── HEADER ────────────────────────────────────────────────────────────
        f_hdr = ctk.CTkFrame(frame_dashboard, fg_color="#001F3F", height=55, corner_radius=0)
        f_hdr.pack(fill="x"); f_hdr.pack_propagate(False)
        ctk.CTkLabel(f_hdr, text="🏠  DASHBOARD — VISÃO GERAL",
                     font=("Arial", 16, "bold"), text_color="white").pack(side="left", padx=20, pady=14)
        hoje_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        ctk.CTkLabel(f_hdr, text=f"🕐 {hoje_str}",
                     font=("Arial", 11), text_color="#adb5bd").pack(side="right", padx=20)

        scroll_dash = ctk.CTkScrollableFrame(frame_dashboard, fg_color="#f0f4f8")
        scroll_dash.pack(fill="both", expand=True, padx=0, pady=0)

        hoje = datetime.now().date()
        mes  = hoje.month
        ano  = hoje.year

        # ── Buscar dados em paralelo ──────────────────────────────────────────
        # Recepção hoje
        rec_hoje = executar_query(
            "SELECT COUNT(*), COALESCE(SUM(valor_num),0) FROM recepcao "
            "WHERE DATE(data_ts)=CURRENT_DATE AND (excluido IS NOT TRUE)",
            fetch=True) or [[0,0]]
        qtd_hoje, val_hoje = int(rec_hoje[0][0] or 0), float(rec_hoje[0][1] or 0)

        # Recepção mês
        rec_mes = executar_query(
            "SELECT COUNT(*), COALESCE(SUM(valor_num),0) FROM recepcao "
            "WHERE mes=%s AND ano=%s AND (excluido IS NOT TRUE)",
            (mes, ano), fetch=True) or [[0,0]]
        qtd_mes, val_mes = int(rec_mes[0][0] or 0), float(rec_mes[0][1] or 0)

        # Caixa mês
        caixa = executar_query(
            "SELECT COALESCE(SUM(CASE WHEN tipo='ENTRADA' THEN valor_num ELSE 0 END),0),"
            "       COALESCE(SUM(CASE WHEN tipo='SAIDA'   THEN valor_num ELSE 0 END),0) "
            "FROM lancamentos WHERE mes=%s AND ano=%s",
            (mes, ano), fetch=True) or [[0,0]]
        entradas, saidas = float(caixa[0][0] or 0), float(caixa[0][1] or 0)

        # ASO vencidos e próximos
        aso_alerta = executar_query("""
            SELECT
                SUM(CASE WHEN data_vencimento_aso < CURRENT_DATE THEN 1 ELSE 0 END),
                SUM(CASE WHEN data_vencimento_aso BETWEEN CURRENT_DATE AND CURRENT_DATE+30 THEN 1 ELSE 0 END),
                SUM(CASE WHEN data_vencimento_aso BETWEEN CURRENT_DATE+30 AND CURRENT_DATE+60 THEN 1 ELSE 0 END)
            FROM atendimentos WHERE status='ATIVO' AND data_vencimento_aso IS NOT NULL
        """, fetch=True) or [[0,0,0]]
        aso_venc = int(aso_alerta[0][0] or 0)
        aso_30   = int(aso_alerta[0][1] or 0)
        aso_60   = int(aso_alerta[0][2] or 0)

        # Toxicológico pendente
        tox_pend = executar_query(
            "SELECT COUNT(*) FROM toxic WHERE cobrado=FALSE AND (excluido IS NOT TRUE)",
            fetch=True) or [[0]]
        qtd_tox = int(tox_pend[0][0] or 0)

        # ── SEÇÃO 1: HOJE ─────────────────────────────────────────────────────
        ctk.CTkLabel(scroll_dash, text="📆  HOJE",
                     font=("Arial", 13, "bold"), text_color="#1f4e79",
                     anchor="w").pack(fill="x", padx=16, pady=(14,4))
        f_hoje = ctk.CTkFrame(scroll_dash, fg_color="transparent")
        f_hoje.pack(fill="x", padx=12, pady=4)

        def _card(parent, titulo, valor, subtitulo, cor, icone, largura=200):
            c = ctk.CTkFrame(parent, fg_color="white", corner_radius=12,
                             width=largura, height=110, border_color=cor, border_width=2)
            c.pack(side="left", padx=6, pady=4); c.pack_propagate(False)
            ctk.CTkLabel(c, text=icone, font=("Arial", 22)).pack(pady=(10,0))
            ctk.CTkLabel(c, text=valor, font=("Arial", 18, "bold"), text_color=cor).pack()
            ctk.CTkLabel(c, text=titulo, font=("Arial", 10, "bold"), text_color="#555").pack()
            if subtitulo:
                ctk.CTkLabel(c, text=subtitulo, font=("Arial", 9), text_color="#888").pack()

        _card(f_hoje, "Atendimentos Hoje", str(qtd_hoje), f"R$ {val_hoje:.2f}", "#1A5276", "👥")
        _card(f_hoje, "Saldo Hoje (Caixa)", f"R$ {entradas-saidas:.2f}", f"↑{entradas:.0f} ↓{saidas:.0f}", "#27AE60", "💰")
        _card(f_hoje, "Tox. Não Cobrados", str(qtd_tox), "pendentes de cobrança", "#E67E22", "🧪")

        # ── SEÇÃO 2: MÊS ─────────────────────────────────────────────────────
        mes_nome = MESES_NOMES[mes-1] if mes <= 12 else str(mes)
        ctk.CTkLabel(scroll_dash, text=f"📅  {mes_nome.upper()} / {ano}",
                     font=("Arial", 13, "bold"), text_color="#1f4e79",
                     anchor="w").pack(fill="x", padx=16, pady=(14,4))
        f_mes = ctk.CTkFrame(scroll_dash, fg_color="transparent")
        f_mes.pack(fill="x", padx=12, pady=4)

        _card(f_mes, "Atendimentos Mês", str(qtd_mes), f"R$ {val_mes:.2f}", "#3498DB", "📋")
        _card(f_mes, "Entradas Caixa", f"R$ {entradas:.2f}", f"mês {mes_nome}", "#27AE60", "📈")
        _card(f_mes, "Saídas Caixa", f"R$ {saidas:.2f}", f"mês {mes_nome}", "#E74C3C", "📉")
        _card(f_mes, "Saldo Mês", f"R$ {entradas-saidas:.2f}", "entradas - saídas", "#8E44AD", "💹")

        # ── SEÇÃO 3: ALERTAS ASO ──────────────────────────────────────────────
        ctk.CTkLabel(scroll_dash, text="🚨  ALERTAS DE VENCIMENTO ASO",
                     font=("Arial", 13, "bold"), text_color="#dc3545",
                     anchor="w").pack(fill="x", padx=16, pady=(14,4))
        f_aso = ctk.CTkFrame(scroll_dash, fg_color="transparent")
        f_aso.pack(fill="x", padx=12, pady=4)

        _card(f_aso, "ASO Vencidos",    str(aso_venc), "ação imediata!", "#dc3545", "🚨")
        _card(f_aso, "Vencem em 30d",   str(aso_30),   "atenção urgente", "#e74c3c", "⚠️")
        _card(f_aso, "Vencem em 60d",   str(aso_60),   "agendar em breve", "#fd7e14", "📅")

        # ── ALERTA VISUAL se houver vencidos ──────────────────────────────────
        if aso_venc > 0 or aso_30 > 0:
            f_alerta = ctk.CTkFrame(scroll_dash, fg_color="#FADBD8",
                                    corner_radius=10, border_color="#dc3545", border_width=2)
            f_alerta.pack(fill="x", padx=12, pady=10)
            msg = f"⚠️  ATENÇÃO: {aso_venc} ASO(s) VENCIDO(S)"
            if aso_30 > 0:
                msg += f" | {aso_30} vence(m) em até 30 dias"
            ctk.CTkLabel(f_alerta, text=msg,
                         font=("Arial", 12, "bold"), text_color="#dc3545").pack(pady=10, padx=16)

        # ── BOTÃO ATUALIZAR ───────────────────────────────────────────────────
        ctk.CTkButton(scroll_dash, text="🔄 ATUALIZAR DASHBOARD",
                      fg_color="#1f4e79", width=220, height=36,
                      font=("Arial", 12, "bold"),
                      command=atualizar_dashboard).pack(pady=16)

    except Exception as e:
        log(f"Erro dashboard: {e}")
        import traceback; traceback.print_exc()

# =============================================================================
# RELATÓRIOS EXCEL
# =============================================================================

def _obter_mes_relatorios():
    try:
        return MESES_NOMES.index(cb_mes_relatorios.get()) + 1
    except:
        return datetime.now().month

def gerar_relatorio_recepcao():
    try:
        mn = _obter_mes_relatorios(); ano = datetime.now().year
        s, e = mes_intervalo(mn, ano)
        regs = executa("""SELECT data_ts, nome, tipo, empresa, exames, valor_num, pagamento, telefone, cpf
                          FROM recepcao WHERE data_ts>=%s AND data_ts<%s AND excluido=FALSE ORDER BY data_ts DESC""",
                       (s, e), fetch=True) or []
        if not regs:
            messagebox.showinfo("Relatório", f"Nenhum registro em {MESES_NOMES[mn-1]}/{ano}"); return

        wb = Workbook(); ws = wb.active; ws.title = "Dados"
        cr = _titulo(ws, 1, f"RELATÓRIO DE RECEPÇÃO — {MESES_NOMES[mn-1].upper()}/{ano}", 1, 9)
        hdrs = ["Data","Nome","Tipo","Empresa","Exames","Valor","Pagamento","Telefone","CPF"]
        for col, h in enumerate(hdrs, 1):
            ws.cell(cr, col, h)
        _fmt(ws, cr, cr, 1, len(hdrs), "subheader"); cr += 1
        sr = cr
        for r in regs:
            row = [r[0].strftime("%d/%m/%Y %H:%M") if r[0] else "", r[1] or "", r[2] or "",
                   r[3] or "", r[4] or "", float(r[5]) if r[5] else 0.0,
                   r[6] or "", r[7] or "", formatar_cpf(r[8]) if r[8] else ""]
            for col, v in enumerate(row, 1):
                ws.cell(cr, col, v)
            cr += 1
        _fmt(ws, sr, cr-1, 1, len(hdrs))
        cr += 1
        total_f = sum(float(r[5]) if r[5] else 0 for r in regs)
        ws.cell(cr, 1, "TOTAIS:"); ws.cell(cr, 2, f"{len(regs)} atendimentos")
        ws.cell(cr, 6, total_f); _fmt(ws, cr, cr, 1, len(hdrs), "total")
        _ajustar_colunas(ws)

        # Aba estatísticas
        ws2 = wb.create_sheet("Estatísticas")
        cr2 = _titulo(ws2, 1, f"ESTATÍSTICAS — {MESES_NOMES[mn-1].upper()}/{ano}", 1, 6)
        cr2 = _titulo(ws2, cr2, "POR TIPO DE ATENDIMENTO", 1, 6)
        tipos = {}
        for r in regs:
            t = r[2] or "SEM TIPO"; v = float(r[5]) if r[5] else 0
            tipos[t] = tipos.get(t, [0, 0]); tipos[t][0] += 1; tipos[t][1] += v
        for col, h in enumerate(["Tipo","Qtd","Valor Total"], 1):
            ws2.cell(cr2, col, h)
        _fmt(ws2, cr2, cr2, 1, 3, "subheader"); cr2 += 1; sr2 = cr2
        for t, (q, v) in tipos.items():
            ws2.cell(cr2, 1, t); ws2.cell(cr2, 2, q); ws2.cell(cr2, 3, f"R$ {v:.2f}"); cr2 += 1
        _fmt(ws2, sr2, cr2-1, 1, 3); _ajustar_colunas(ws2)

        nome = f"Relatorio_Recepcao_{MESES_NOMES[mn-1]}_{ano}.xlsx"
        c = _salvar_abrir(wb, nome)
        show_status(f"✅ Excel gerado! {len(regs)} registros | R$ {total_f:.2f}")
    except Exception as e:
        messagebox.showerror("Erro", str(e)); traceback.print_exc()

def gerar_relatorio_caixa():
    try:
        mn = _obter_mes_relatorios(); ano = datetime.now().year
        s, e = mes_intervalo(mn, ano)
        lancs = executa("""SELECT data_ts, tipo, valor_num, descricao FROM lancamentos
                           WHERE data_ts>=%s AND data_ts<%s ORDER BY data_ts DESC""",
                        (s, e), fetch=True) or []
        if not lancs:
            messagebox.showinfo("Relatório", f"Nenhum lançamento em {MESES_NOMES[mn-1]}/{ano}"); return

        wb = Workbook(); ws = wb.active; ws.title = "Movimentação"
        cr = _titulo(ws, 1, f"RELATÓRIO DE CAIXA — {MESES_NOMES[mn-1].upper()}/{ano}", 1, 4)
        for col, h in enumerate(["Data","Descrição","Entrada","Saída"], 1):
            ws.cell(cr, col, h)
        _fmt(ws, cr, cr, 1, 4, "subheader"); cr += 1; sr = cr
        ent_t = sai_t = 0.0
        for l in lancs:
            dt = l[0].strftime("%d/%m/%Y") if l[0] else ""; tipo = str(l[1] or "").upper()
            v = float(l[2]) if l[2] else 0.0; desc = l[3] or ""
            ve = v if tipo in ["ENTRADA","ENTRADAS"] else ""
            vs = v if tipo in ["SAIDA","SAÍDA","SAIDAS","SAÍDAS"] else ""
            if ve: ent_t += v
            if vs: sai_t += v
            ws.cell(cr, 1, dt); ws.cell(cr, 2, desc); ws.cell(cr, 3, ve); ws.cell(cr, 4, vs)
            cr += 1
        _fmt(ws, sr, cr-1, 1, 4); cr += 1
        ws.cell(cr, 1, "TOTAIS:"); ws.cell(cr, 3, ent_t); ws.cell(cr, 4, sai_t)
        _fmt(ws, cr, cr, 1, 4, "total"); cr += 1
        ws.cell(cr, 1, "SALDO:"); ws.cell(cr, 4, ent_t - sai_t)
        _fmt(ws, cr, cr, 1, 4, "total"); _ajustar_colunas(ws)

        nome = f"Relatorio_Caixa_{MESES_NOMES[mn-1]}_{ano}.xlsx"
        _salvar_abrir(wb, nome)
        show_status(f"✅ Caixa gerado! Ent: R$ {ent_t:.2f} | Saí: R$ {sai_t:.2f} | Saldo: R$ {ent_t-sai_t:.2f}")
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def gerar_relatorio_toxic():
    try:
        mn = _obter_mes_relatorios(); ano = datetime.now().year
        s, e = mes_intervalo(mn, ano)
        regs = executa("""SELECT data_coleta_ts, nome_colaborador, empresa, cpf, enviado, cobrado
                          FROM toxic WHERE data_coleta_ts>=%s AND data_coleta_ts<%s AND excluido=FALSE
                          ORDER BY data_coleta_ts DESC""", (s, e), fetch=True) or []
        if not regs:
            messagebox.showinfo("Relatório", f"Nenhum exame em {MESES_NOMES[mn-1]}/{ano}"); return

        wb = Workbook(); ws = wb.active; ws.title = "Exames"
        cr = _titulo(ws, 1, f"RELATÓRIO TOXICOLÓGICO — {MESES_NOMES[mn-1].upper()}/{ano}", 1, 7)
        for col, h in enumerate(["Data","Nome","Empresa","CPF","Status","Enviado","Cobrado"], 1):
            ws.cell(cr, col, h)
        _fmt(ws, cr, cr, 1, 7, "subheader"); cr += 1; sr = cr
        comp = parc = pend = 0
        for r in regs:
            dt = r[0].strftime("%d/%m/%Y %H:%M") if r[0] else ""
            env = r[4]; cob = r[5]
            if env and cob:   st = "COMPLETO"; comp += 1; stype = "success"
            elif env or cob:  st = "PARCIAL";  parc += 1; stype = "warning"
            else:             st = "PENDENTE"; pend += 1; stype = "error"
            row = [dt, r[1] or "", r[2] or "", formatar_cpf(r[3]) if r[3] else "",
                   st, "✓ SIM" if env else "✗ NÃO", "✓ SIM" if cob else "✗ NÃO"]
            for col, v in enumerate(row, 1):
                ws.cell(cr, col, v)
            _fmt(ws, cr, cr, 1, 7, stype); cr += 1
        cr += 1
        ws.cell(cr, 1, "TOTAIS:"); ws.cell(cr, 2, f"{len(regs)} exames")
        ws.cell(cr, 5, f"Comp:{comp} | Parc:{parc} | Pend:{pend}")
        _fmt(ws, cr, cr, 1, 7, "total"); _ajustar_colunas(ws)

        nome = f"Relatorio_Toxicologico_{MESES_NOMES[mn-1]}_{ano}.xlsx"
        _salvar_abrir(wb, nome)
        show_status(f"✅ Tox gerado! Total:{len(regs)} | Comp:{comp} | Pend:{pend}")
    except Exception as e:
        messagebox.showerror("Erro", str(e))

def gerar_relatorio_faturas_geradas():
    """
    Relatório de todas as FATURAS GERADAS na aba Faturas.
    Exporta: número, empresa, período, valor, qtd atendimentos,
             forma pagamento, status, vencimento, data pagamento.
    Inclui aba de detalhes com todos os itens de cada fatura.
    """
    try:
        ano = datetime.now().year

        # ── Buscar todas as faturas ───────────────────────────────────────────
        faturas = executa("""
            SELECT f.id, f.numero_fatura,
                   COALESCE(e.nome, 'N/A') as empresa,
                   f.mes_referencia, f.ano_referencia,
                   COALESCE(f.valor_total, 0) as valor,
                   COALESCE(f.quantidade_atendimentos, 0) as qtd,
                   COALESCE(f.forma_pagamento, 'PIX') as forma,
                   COALESCE(f.status_pagamento, 'PENDENTE') as status,
                   f.data_vencimento,
                   f.data_pagamento,
                   f.data_criacao
            FROM faturas f
            LEFT JOIN empresas e ON f.empresa_id = e.id
            ORDER BY f.id DESC
        """, fetch=True) or []

        if not faturas:
            messagebox.showinfo("Relatório", "Nenhuma fatura gerada ainda."); return

        # ── Buscar itens de todas as faturas ──────────────────────────────────
        itens = executa("""
            SELECT it.fatura_id, it.colaborador, it.modo,
                   it.data_atendimento, it.valor_atendimento
            FROM itens_fatura it
            ORDER BY it.fatura_id, it.colaborador
        """, fetch=True) or []

        # Agrupar itens por fatura_id
        itens_por_fatura = {}
        for it in itens:
            fid = it[0]
            if fid not in itens_por_fatura:
                itens_por_fatura[fid] = []
            itens_por_fatura[fid].append(it)

        wb = Workbook()

        # ── ABA 1: Resumo de Faturas ──────────────────────────────────────────
        ws1 = wb.active; ws1.title = "Faturas"
        hdrs1 = ["Nº Fatura","Empresa","Período","Valor Total","Qtd Atend.",
                 "Forma Pag.","Status","Vencimento","Data Pagamento","Criação"]
        cr = _titulo(ws1, 1, "RELATÓRIO DE FATURAS GERADAS — APTUS", 1, len(hdrs1))
        for col, h in enumerate(hdrs1, 1):
            ws1.cell(cr, col, h)
        _fmt(ws1, cr, cr, 1, len(hdrs1), "subheader"); cr += 1; sr = cr

        total_geral = 0.0
        pago = pendente = atrasado = 0

        for f in faturas:
            fid, num, emp, mes, ano_f, valor, qtd, forma, status, venc, dt_pag, dt_cri = f
            try: mn_n = MESES_NOMES[int(mes)-1] if mes else ""
            except: mn_n = str(mes or "")
            periodo = f"{mn_n}/{ano_f}" if ano_f else mn_n
            v = float(valor or 0); total_geral += v

            if status == "PAGO":     pago += 1
            elif status == "ATRASADO": atrasado += 1
            else:                    pendente += 1

            row = [
                num or "",
                emp or "",
                periodo,
                v,
                int(qtd or 0),
                forma or "PIX",
                status or "PENDENTE",
                venc.strftime("%d/%m/%Y") if venc else "",
                dt_pag.strftime("%d/%m/%Y") if dt_pag else "",
                dt_cri.strftime("%d/%m/%Y") if dt_cri else "",
            ]
            for col, val in enumerate(row, 1):
                ws1.cell(cr, col, val)
            # Colorir por status
            from openpyxl.styles import PatternFill
            cor_map = {"PAGO": "D4EDDA", "PENDENTE": "FFF3CD", "ATRASADO": "F8D7DA"}
            fill_cor = cor_map.get(status, "FFFFFF")
            for col in range(1, len(hdrs1)+1):
                ws1.cell(cr, col).fill = PatternFill("solid", fgColor=fill_cor)
            cr += 1

        _fmt(ws1, sr, cr-1, 1, len(hdrs1)); cr += 2

        # Totalizadores
        ws1.cell(cr, 1, "TOTAL GERAL:"); ws1.cell(cr, 4, total_geral)
        ws1.cell(cr, 5, len(faturas))
        _fmt(ws1, cr, cr, 1, len(hdrs1), "total"); cr += 1
        ws1.cell(cr, 1, f"✅ PAGAS: {pago}  |  ⏳ PENDENTES: {pendente}  |  ❌ ATRASADAS: {atrasado}")
        _ajustar_colunas(ws1)

        # ── ABA 2: Itens por Fatura ───────────────────────────────────────────
        ws2 = wb.create_sheet("Itens por Fatura")
        hdrs2 = ["Nº Fatura","Empresa","Colaborador","Modo","Data Atend.","Valor"]
        cr2 = _titulo(ws2, 1, "ITENS POR FATURA — DETALHAMENTO", 1, len(hdrs2))
        for col, h in enumerate(hdrs2, 1):
            ws2.cell(cr2, col, h)
        _fmt(ws2, cr2, cr2, 1, len(hdrs2), "subheader"); cr2 += 1

        # Mapa fatura_id → numero_fatura e empresa
        fat_map = {f[0]: (f[1], f[2]) for f in faturas}

        for fid, its in itens_por_fatura.items():
            num_fat, emp_fat = fat_map.get(fid, ("?", "?"))
            for it in its:
                _, colab, modo, dt_at, val_at = it
                dt_str = dt_at.strftime("%d/%m/%Y") if dt_at else ""
                row2 = [num_fat, emp_fat, colab or "", modo or "",
                        dt_str, float(val_at or 0)]
                for col, val in enumerate(row2, 1):
                    ws2.cell(cr2, col, val)
                cr2 += 1
        _ajustar_colunas(ws2)

        nome = f"Faturas_Geradas_{ano}.xlsx"
        _salvar_abrir(wb, nome)
        show_status(f"✅ Faturas exportadas! {len(faturas)} faturas | R$ {total_geral:.2f} | Pagas:{pago} Pendentes:{pendente} Atrasadas:{atrasado}")
    except Exception as e:
        messagebox.showerror("Erro", str(e))
        import traceback; traceback.print_exc()


def gerar_relatorio_aso():
    """
    Relatório Excel de Vencimentos ASO — detalhado por colaborador.
    Abas: Todos | Vencidos | Próximos 60 dias | Em Dia
    """
    try:
        rows = executar_query("""
            SELECT
                a.colaborador,
                a.cpf_colaborador,
                COALESCE(e.nome, 'N/A') AS empresa,
                a.modo,
                a.data_atendimento,
                a.data_vencimento_aso,
                (a.data_vencimento_aso - CURRENT_DATE) AS dias_restantes
            FROM atendimentos a
            LEFT JOIN empresas e ON a.empresa_id = e.id
            WHERE a.data_vencimento_aso IS NOT NULL
              AND a.status = 'ATIVO'
            ORDER BY a.data_vencimento_aso ASC
        """, fetch=True) or []

        if not rows:
            messagebox.showinfo("Relatório ASO", "Nenhum ASO cadastrado ainda.")
            return

        wb = Workbook()

        def _aba_aso(ws, titulo, dados):
            hdrs = ["COLABORADOR","CPF","EMPRESA","TIPO ASO",
                    "DATA ATENDIMENTO","VENCIMENTO ASO","DIAS RESTANTES","STATUS"]
            cr = _titulo(ws, 1, titulo, 1, len(hdrs))
            for col, h in enumerate(hdrs, 1):
                ws.cell(cr, col, h)
            _fmt(ws, cr, cr, 1, len(hdrs), "subheader"); cr += 1; sr = cr

            from openpyxl.styles import PatternFill, Font
            for r in dados:
                colab, cpf, emp, modo, dt_aso, dt_venc, dias = r
                dias_int = int(dias) if dias is not None else 0
                if dias_int < 0:
                    status = f"VENCIDO ({abs(dias_int)}d)"
                    fill_cor = "F8D7DA"
                elif dias_int <= 30:
                    status = f"URGENTE ({dias_int}d)"
                    fill_cor = "FDEBD0"
                elif dias_int <= 60:
                    status = f"ATENÇÃO ({dias_int}d)"
                    fill_cor = "FEF9E7"
                elif dias_int <= 90:
                    status = f"PRÓXIMO ({dias_int}d)"
                    fill_cor = "FFFDE7"
                else:
                    status = f"EM DIA ({dias_int}d)"
                    fill_cor = "D4EDDA"

                row_data = [
                    colab or "",
                    formatar_cpf(cpf) if cpf else "",
                    emp or "",
                    modo or "",
                    dt_aso.strftime("%d/%m/%Y") if dt_aso else "",
                    dt_venc.strftime("%d/%m/%Y") if dt_venc else "",
                    dias_int,
                    status,
                ]
                for col, val in enumerate(row_data, 1):
                    ws.cell(cr, col, val)
                    ws.cell(cr, col).fill = PatternFill("solid", fgColor=fill_cor)
                cr += 1

            _fmt(ws, sr, cr-1, 1, len(hdrs))
            _ajustar_colunas(ws)

        # Aba 1: Todos
        ws1 = wb.active; ws1.title = "Todos"
        _aba_aso(ws1, f"RELATÓRIO ASO — TODOS OS COLABORADORES ({len(rows)})", rows)

        # Aba 2: Vencidos
        vencidos = [r for r in rows if (r[6] or 0) < 0]
        ws2 = wb.create_sheet("Vencidos")
        _aba_aso(ws2, f"ASO VENCIDOS ({len(vencidos)})", vencidos)

        # Aba 3: Próximos 60 dias
        proximos = [r for r in rows if 0 <= (r[6] or 0) <= 60]
        ws3 = wb.create_sheet("Próximos 60 dias")
        _aba_aso(ws3, f"ASO VENCENDO EM ATÉ 60 DIAS ({len(proximos)})", proximos)

        # Aba 4: Em dia
        em_dia = [r for r in rows if (r[6] or 0) > 60]
        ws4 = wb.create_sheet("Em Dia")
        _aba_aso(ws4, f"ASO EM DIA ({len(em_dia)})", em_dia)

        nome = f"Relatorio_ASO_{datetime.now().strftime('%d%m%Y')}.xlsx"
        _salvar_abrir(wb, nome)
        show_status(f"✅ Relatório ASO exportado! {len(rows)} colaboradores | {len(vencidos)} vencidos | {len(proximos)} próximos")

    except Exception as e:
        messagebox.showerror("Erro", str(e))
        import traceback; traceback.print_exc()


def _backup_automatico():
    """
    Backup automático semanal — exporta tabelas principais para CSV.
    Salva em pasta 'backups/' com data no nome.
    Agenda próximo backup em 7 dias.
    """
    try:
        import os, csv
        pasta = os.path.join(_diretorio_app(), "backups")
        os.makedirs(pasta, exist_ok=True)
        hoje = datetime.now().strftime("%Y%m%d_%H%M")

        tabelas = {
            "recepcao":     "SELECT * FROM recepcao WHERE excluido IS NOT TRUE ORDER BY data_ts DESC",
            "atendimentos": "SELECT * FROM atendimentos WHERE status='ATIVO' ORDER BY data_atendimento DESC",
            "faturas":      "SELECT * FROM faturas ORDER BY id DESC",
            "pacientes":    "SELECT * FROM pacientes ORDER BY nome",
            "empresas":     "SELECT * FROM empresas WHERE ativo=TRUE ORDER BY nome",
        }

        arquivos = []
        for nome_tab, query in tabelas.items():
            rows = executar_query(query, fetch=True) or []
            if rows:
                arq = os.path.join(pasta, f"{nome_tab}_{hoje}.csv")
                with open(arq, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(rows)
                arquivos.append(arq)

        log(f"✅ Backup automático: {len(arquivos)} tabelas salvas em {pasta}")

        # Limpar backups com mais de 30 dias
        try:
            from datetime import timedelta
            limite = datetime.now() - timedelta(days=30)
            for arq in os.listdir(pasta):
                caminho = os.path.join(pasta, arq)
                if os.path.getmtime(caminho) < limite.timestamp():
                    os.remove(caminho)
        except:
            pass

    except Exception as e:
        log(f"Erro backup automático: {e}")
    finally:
        # Agendar próximo backup em 7 dias (604800000 ms)
        try:
            app.after(604800000, _backup_automatico)
        except:
            pass


def criar_interface():
    global ent_data_r, ent_n_r, cb_t_r, ent_e_r, ent_ex_r, ent_v_r, cb_p_r
    global ent_t_r, ent_cpf_r, btn_salvar, scroll_rec, ent_busca_menu
    global scroll_fin, lbl_saldo_caixa, ent_desc_c, ent_val_c
    global cb_mes_relatorios, lbl_status
    global frame_recepcao, frame_caixa, frame_toxic, frame_faturamento
    global frame_faturas, frame_exames, frame_empresas, frame_vencimentos, frame_relatorios, frame_dashboard, frame_documentos
    global btn_recepcao, btn_caixa, btn_toxic, btn_relatorios, btn_documentos
    global ent_data_toxic, ent_nome_toxic, ent_cpf_toxic, ent_empresa_toxic
    global cb_enviado_toxic, cb_cobrado_toxic, btn_salvar_toxic, tree_toxic
    global tree_atendimentos, cb_empresa_filtro, cb_mes_filtro, lbl_total_empresa
    global tree_faturas, tree_exames, tree_empresas, scroll_vencimentos
    global sidebar, area_main, btn_hamburger
    global _ent_nome_atend, _ent_cpf_atend, _cb_modo_atend, _cb_empresa_atend
    global _ent_data_atend, _lbl_total_atend, _lbl_total_geral_atend
    global _frame_resumo_custos, _exames_vars_atend
    global _ent_nome_doc, _ent_cpf_doc, _cb_medico_doc, _var_periodo_doc

    log("🚀 Iniciando sistema APTUS integrado...")
    # OPÇÃO B: inicializar em background — UI abre imediatamente
    import threading
    def _init_bg():
        inicializar_banco()
        inserir_dados_basicos()
        # Lista de médicos na aba Documentos só faz sentido após tabelas/seed no banco
        gui_safe(atualizar_aba_documentos)
        # ── Auto-atualizar faturas vencidas para ATRASADO (1 UPDATE leve) ──
        try:
            executar("""
                UPDATE faturas
                SET status_pagamento = 'ATRASADO'
                WHERE status_pagamento = 'PENDENTE'
                  AND data_vencimento IS NOT NULL
                  AND data_vencimento < CURRENT_DATE
            """)
            log("✅ Faturas atrasadas atualizadas automaticamente.")
        except Exception as e:
            log(f"Erro ao auto-atualizar atrasadas: {e}", exc=True)
        # Cache pesado (centenas de nomes) — adiado para a UI abrir rápido
        gui_safe(lambda: app.after(8000, carregar_cache_nomes))
        gui_safe(lambda: app.after(2000, _alerta_aso_startup))
        # Backup em CSV — não compete com o arranque (3 min após abrir)
        gui_safe(lambda: app.after(180000, _backup_automatico))
    threading.Thread(target=_init_bg, daemon=True).start()

    # ── TOPO ──────────────────────────────────────────────────────────────────
    f_topo = ctk.CTkFrame(app, fg_color="#001F3F", height=65, corner_radius=0)
    f_topo.pack(fill="x"); f_topo.pack_propagate(False)

    btn_hamburger = ctk.CTkButton(f_topo, text="☰", width=48, height=48,
                                  font=("Arial", 20, "bold"), fg_color="#34495E",
                                  command=toggle_sidebar)
    btn_hamburger.place(x=10, y=8)

    ctk.CTkLabel(f_topo, text="APTUS MEDICINA DO TRABALHO",
                 font=("Arial", 20, "bold"), text_color="white").pack(pady=18)

    lbl_status = ctk.CTkLabel(f_topo, text="", font=("Arial", 10), text_color="#adb5bd")
    lbl_status.place(relx=0.99, rely=0.7, anchor="e")

    # ── LAYOUT ────────────────────────────────────────────────────────────────
    f_layout = ctk.CTkFrame(app, fg_color="transparent")
    f_layout.pack(fill="both", expand=True, padx=8, pady=8)

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    sidebar = ctk.CTkFrame(f_layout, width=130, fg_color="#F7F9FA")
    sidebar.pack_propagate(False)

    def _btn_menu(txt, cor, aba):
        return ctk.CTkButton(sidebar, text=txt, width=115, height=34,
                             font=("Arial", 10, "bold"), fg_color="#34495E",
                             command=lambda: mostrar_aba(aba))

    def _sep(txt):
        """Separador de grupo no menu lateral."""
        f = ctk.CTkFrame(sidebar, fg_color="#DEE2E6", height=1)
        f.pack(fill="x", padx=8, pady=(8,2))
        ctk.CTkLabel(sidebar, text=txt, font=("Arial", 8, "bold"),
                     text_color="#888").pack(pady=(0,2))

    # ── OPERACIONAL ──────────────────────────────────────────────────────────
    _sep("OPERACIONAL")
    btn_recepcao   = _btn_menu("👥 RECEPÇÃO",    "#1A5276", "recepcao");   btn_recepcao.pack(pady=2)
    btn_caixa      = _btn_menu("💰 CAIXA",       "#27AE60", "caixa");      btn_caixa.pack(pady=2)
    btn_toxic      = _btn_menu("🧪 TOXICOLÓGICO","#E67E22", "toxic");      btn_toxic.pack(pady=2)

    # ── GESTÃO ───────────────────────────────────────────────────────────────
    _sep("GESTÃO")
    btn_relatorios = _btn_menu("📊 RELATÓRIOS",  "#1A5276", "relatorios"); btn_relatorios.pack(pady=2)
    ctk.CTkButton(sidebar, text="📋 HISTÓRICO", width=115, height=34,
                  font=("Arial", 10, "bold"), fg_color="#6c757d",
                  command=abrir_historico_paciente).pack(pady=2)
    btn_documentos = _btn_menu("📄 DOCUMENTOS", "#5b4b8a", "documentos")
    btn_documentos.pack(pady=2)

    # ── ÁREA PRINCIPAL ────────────────────────────────────────────────────────
    area_main = ctk.CTkFrame(f_layout, fg_color="transparent")
    area_main.pack(side="left", fill="both", expand=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # ABA RECEPÇÃO
    # ═══════════════════════════════════════════════════════════════════════════
    frame_recepcao = ctk.CTkFrame(area_main, fg_color="transparent")

    f_inp = ctk.CTkFrame(frame_recepcao, fg_color="#f0f4f8", height=56)
    f_inp.pack(fill="x", padx=8, pady=(8, 4)); f_inp.pack_propagate(False)
    f_inp_inner = ctk.CTkFrame(f_inp, fg_color="transparent")
    f_inp_inner.pack(fill="both", expand=True, padx=8, pady=8)

    ent_data_r = ctk.CTkEntry(f_inp_inner, width=110, placeholder_text="DD/MM/AAAA")
    ent_data_r.insert(0, datetime.now().strftime("%d/%m/%Y"))
    ent_data_r.pack(side="left", padx=4)
    ent_data_r.bind("<KeyRelease>", debounce_busca)

    ent_n_r  = ctk.CTkEntry(f_inp_inner, placeholder_text="NOME", width=190); ent_n_r.pack(side="left", padx=4)

    # ── Seletor de Tipo — igual ao campo PAGAMENTO (readonly, sem digitar) ──
    cb_t_r = ctk.CTkComboBox(f_inp_inner, values=TIPOS_ATENDIMENTO, width=130, state="readonly")
    cb_t_r.set("ADM")
    cb_t_r.pack(side="left", padx=4)


    ent_e_r  = ctk.CTkEntry(f_inp_inner, placeholder_text="EMPRESA", width=150); ent_e_r.pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════════════════════
    # ComboBox inteligente de empresa — Toplevel sem borda
    # ══════════════════════════════════════════════════════════════════════════
    _emp_win  = [None]   # janela Toplevel atual

    def _fechar_emp():
        try:
            if _emp_win[0] and _emp_win[0].winfo_exists():
                _emp_win[0].destroy()
            _emp_win[0] = None
        except:
            _emp_win[0] = None



    _emp_idx      = [0]
    _emp_lista    = []
    _emp_btns_lst = []

    def _emp_highlight(idx):
        for i, b in enumerate(_emp_btns_lst):
            try:
                if i == idx:
                    b.configure(bg="#1A5276", fg="white")
                else:
                    b.configure(bg="white", fg="#1A5276")
            except:
                pass

    _emp_debounce_id = [None]   # controle do debounce

    def _atualizar_emp_popup(event=None):
        if event and event.keysym in ("Down","Up","Return","Escape","Tab"):
            return
        # Debounce: espera 500ms após parar de digitar
        if _emp_debounce_id[0]:
            app.after_cancel(_emp_debounce_id[0])
        _emp_debounce_id[0] = app.after(500, _buscar_emp)

    def _buscar_emp():
        termo = ent_e_r.get().strip()
        if len(termo) < 2:
            _fechar_emp(); return

        emps = executar_query(
            "SELECT nome FROM empresas WHERE UPPER(nome) LIKE UPPER(%s) AND ativo=TRUE ORDER BY nome LIMIT 12",
            (f"%{termo}%",), fetch=True) or []

        _emp_lista.clear()
        _emp_btns_lst.clear()
        _fechar_emp()

        if not emps:
            # Não encontrou — mini-form inline para cadastro rápido
            win = tk.Toplevel(app)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            _emp_win[0] = win

            tk.Label(win, text=f'  Empresa "{termo}" não encontrada.',
                     bg="#fff3cd", fg="#856404",
                     font=("Arial", 9)).pack(fill="x", padx=4, pady=(4,0))

            f_novo = tk.Frame(win, bg="white")
            f_novo.pack(fill="x", padx=4, pady=4)

            ent_novo_nome = tk.Entry(f_novo, font=("Arial", 10), width=22)
            ent_novo_nome.insert(0, termo.upper())
            ent_novo_nome.pack(side="left", padx=(0,4))
            ent_novo_nome.focus_set()

            def _salvar_nova_emp():
                nome_novo = ent_novo_nome.get().strip().upper()
                if not nome_novo:
                    return
                try:
                    executar_query(
                        "INSERT INTO empresas (nome, ativo) VALUES (%s, TRUE) ON CONFLICT DO NOTHING",
                        (nome_novo,)
                    )
                    ent_e_r.delete(0, "end")
                    ent_e_r.insert(0, nome_novo)
                    _fechar_emp()
                    try: ent_ex_r.focus_set()
                    except: pass
                except Exception as ex_err:
                    tk.Label(win, text=f"Erro: {ex_err}", bg="white",
                             fg="red", font=("Arial", 8)).pack()

            btn_salvar_emp = tk.Button(f_novo, text="✔ SALVAR",
                                       relief="flat", bg="#28a745", fg="white",
                                       font=("Arial", 9, "bold"),
                                       activebackground="#218838",
                                       cursor="hand2",
                                       command=_salvar_nova_emp)
            btn_salvar_emp.pack(side="left")
            ent_novo_nome.bind("<Return>", lambda e: _salvar_nova_emp())
            ent_novo_nome.bind("<Escape>", lambda e: _fechar_emp())

            app.update_idletasks()
            ex = ent_e_r.winfo_rootx()
            ey = ent_e_r.winfo_rooty() + ent_e_r.winfo_height() + 2
            win.geometry(f"300x68+{ex}+{ey}")
            return

        # Encontrou — mostrar lista
        win = tk.Toplevel(app)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        _emp_win[0] = win

        for (emp_nome,) in emps:
            _emp_lista.append(emp_nome)
            def _sel(n=emp_nome):
                ent_e_r.delete(0, "end"); ent_e_r.insert(0, n)
                _fechar_emp()
                try: ent_ex_r.focus_set()
                except: pass
            b = tk.Button(win, text=f"  {emp_nome}", anchor="w", relief="flat",
                          bg="white", fg="#1A5276",
                          font=("Arial", 10),
                          activebackground="#D6EAF8",
                          cursor="hand2", command=_sel)
            b.pack(fill="x", padx=2, pady=1)
            _emp_btns_lst.append(b)

        _emp_idx[0] = 0
        _emp_highlight(0)
        h = min(len(emps) * 34 + 4, 240)
        app.update_idletasks()
        ex = ent_e_r.winfo_rootx()
        ey = ent_e_r.winfo_rooty() + ent_e_r.winfo_height() + 2
        win.geometry(f"260x{h}+{ex}+{ey}")
        # Fechar ao clicar fora — via bind global no app
        app.bind("<Button-1>", _click_fora_emp, add="+")

    def _click_fora_emp(event):
        try:
            if not (_emp_win[0] and _emp_win[0].winfo_exists()): return
            wx = _emp_win[0].winfo_rootx(); wy = _emp_win[0].winfo_rooty()
            ww = _emp_win[0].winfo_width(); wh = _emp_win[0].winfo_height()
            if not (wx <= event.x_root <= wx+ww and wy <= event.y_root <= wy+wh):
                _fechar_emp()
        except: pass

    def _emp_key(event):
        if not (_emp_win[0] and _emp_win[0].winfo_exists()):
            return
        n = len(_emp_lista)
        if n == 0: return
        if event.keysym == "Down":
            _emp_idx[0] = (_emp_idx[0] + 1) % n
            _emp_highlight(_emp_idx[0])
        elif event.keysym == "Up":
            _emp_idx[0] = (_emp_idx[0] - 1) % n
            _emp_highlight(_emp_idx[0])
        elif event.keysym in ("Return", "Tab"):
            nome_sel = _emp_lista[_emp_idx[0]]
            ent_e_r.delete(0, "end"); ent_e_r.insert(0, nome_sel)
            _fechar_emp()
            try: ent_ex_r.focus_set()
            except: pass
        elif event.keysym == "Escape":
            _fechar_emp()

    ent_e_r.bind("<KeyRelease>", _atualizar_emp_popup)
    ent_e_r.bind("<Down>",       _emp_key)
    ent_e_r.bind("<Up>",         _emp_key)
    ent_e_r.bind("<Return>",     _emp_key)
    ent_e_r.bind("<Tab>",        _emp_key)
    ent_e_r.bind("<Escape>",     lambda e: _fechar_emp())
    def _emp_focusout(event):
        # Só fecha se o foco não foi para dentro do popup de empresa
        def _checar():
            try:
                fw = app.focus_get()
                if fw is None:
                    _fechar_emp(); return
                # Se o foco está dentro do popup, não fecha
                if _emp_win[0] and _emp_win[0].winfo_exists():
                    wx = _emp_win[0].winfo_rootx(); wy = _emp_win[0].winfo_rooty()
                    ww = _emp_win[0].winfo_width(); wh = _emp_win[0].winfo_height()
                    fx = fw.winfo_rootx(); fy = fw.winfo_rooty()
                    if wx <= fx <= wx+ww and wy <= fy <= wy+wh:
                        return  # foco dentro do popup — não fecha
                _fechar_emp()
            except: pass
        app.after(150, _checar)
    ent_e_r.bind("<FocusOut>", _emp_focusout)
    ent_ex_r = ctk.CTkEntry(f_inp_inner, placeholder_text="EXAMES", width=130); ent_ex_r.pack(side="left", padx=4)
    ent_v_r  = ctk.CTkEntry(f_inp_inner, placeholder_text="VALOR", width=90); ent_v_r.pack(side="left", padx=4)
    cb_p_r   = ctk.CTkComboBox(f_inp_inner, values=FORMAS_PAG_REC, width=100, state="readonly"); cb_p_r.set("DIN"); cb_p_r.pack(side="left", padx=4)
    ent_t_r  = ctk.CTkEntry(f_inp_inner, placeholder_text="FONE", width=110); ent_t_r.pack(side="left", padx=4)
    ent_cpf_r= ctk.CTkEntry(f_inp_inner, placeholder_text="CPF", width=110); ent_cpf_r.pack(side="left", padx=4)
    ent_cpf_r.bind("<KeyRelease>", _mascara_cpf)
    btn_salvar = ctk.CTkButton(f_inp_inner, text="💾 SALVAR", width=110, height=34,
                               fg_color="#1A5276", font=("Arial", 11, "bold"),
                               command=salvar_rec); btn_salvar.pack(side="left", padx=8)

    # ── Autocomplete Recepção ─────────────────────────────────────────────────
    _lb_rec = tk.Listbox(frame_recepcao, font=("Arial", 11), bg="white", fg="#1A5276",
                          selectbackground="#AED6F1", relief="solid", bd=1,
                          activestyle="none", highlightthickness=1,
                          highlightcolor="#1A5276", cursor="hand2", height=6)

    _job_rec = [None]

    def _fechar_rec(e=None):
        try: _lb_rec.place_forget()
        except: pass

    def _mostrar_rec(lista):
        if not lista:
            _fechar_rec(); return
        _lb_rec.delete(0, "end")
        for n in lista:
            _lb_rec.insert("end", "  " + n)
        _lb_rec.configure(height=min(len(lista), 7))
        app.update_idletasks()
        x  = ent_n_r.winfo_x()
        y  = ent_n_r.winfo_y()
        eh = ent_n_r.winfo_height()
        ew = ent_n_r.winfo_width()
        # subir pela hierarquia até frame_recepcao
        w = ent_n_r; rx, ry = 0, 0
        while w and w != frame_recepcao:
            try: rx += w.winfo_x(); ry += w.winfo_y(); w = w.master
            except: break
        _lb_rec.place(x=rx, y=ry + eh + 2, width=max(ew, 260))
        _lb_rec.lift()

    def _sel_rec(entrada_sel):
        entrada_sel = entrada_sel.strip()
        _fechar_rec()

        # Remover data se vier no formato "NOME  —  DD/MM/AAAA"
        if "  —  " in entrada_sel:
            nome_sel = entrada_sel.split("  —  ")[0].strip()
        elif " — " in entrada_sel:
            nome_sel = entrada_sel.split(" — ")[0].strip()
        else:
            nome_sel = entrada_sel

        # Preenche APENAS o nome — CPF e telefone devem ser digitados manualmente
        ent_n_r.delete(0, "end")
        ent_n_r.insert(0, nome_sel)
        show_status(f"✅ {nome_sel}")

    def _digitar_rec(event=None):
        if event and event.keysym in ("Up","Down","Return","Escape","Tab"): return
        texto = ent_n_r.get().strip()
        if len(texto) < 2:
            _fechar_rec(); return
        if _job_rec[0]: app.after_cancel(_job_rec[0])
        def _exec():
            sugs = buscar_nomes_colaboradores(texto)
            _mostrar_rec(sugs)
        _job_rec[0] = app.after(300, _exec)

    def _nav_rec(event):
        try:
            if not _lb_rec.winfo_ismapped(): return
            sel = _lb_rec.curselection(); size = _lb_rec.size()
            if event.keysym == "Down":
                novo = (sel[0]+1) if sel else 0; novo = min(novo, size-1)
            elif event.keysym == "Up":
                novo = (sel[0]-1) if sel else size-1; novo = max(novo, 0)
            elif event.keysym in ("Return","Tab"):
                if sel: _sel_rec(_lb_rec.get(sel[0]))
                return
            else: return
            _lb_rec.selection_clear(0,"end"); _lb_rec.selection_set(novo); _lb_rec.see(novo)
        except: pass

    ent_n_r.bind("<KeyRelease>", _digitar_rec)
    ent_n_r.bind("<Down>",       _nav_rec)
    ent_n_r.bind("<Up>",         _nav_rec)
    ent_n_r.bind("<Return>",     _nav_rec)
    ent_n_r.bind("<Escape>",     _fechar_rec)
    ent_n_r.bind("<FocusOut>",   lambda e: app.after(300, _fechar_rec))
    _lb_rec.bind("<ButtonRelease-1>",
        lambda e: _sel_rec(_lb_rec.get(_lb_rec.curselection()[0]).strip())
        if _lb_rec.curselection() else None)

    scroll_rec = ctk.CTkScrollableFrame(frame_recepcao, fg_color="#F2F3F4")
    scroll_rec.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ═══════════════════════════════════════════════════════════════════════════
    # ABA CAIXA
    # ═══════════════════════════════════════════════════════════════════════════
    frame_caixa = ctk.CTkFrame(area_main, fg_color="transparent")

    f_cx_hdr = ctk.CTkFrame(frame_caixa, fg_color="#27AE60", height=55)
    f_cx_hdr.pack(fill="x"); f_cx_hdr.pack_propagate(False)
    ctk.CTkLabel(f_cx_hdr, text="💰 CONTROLE DE CAIXA",
                 font=("Arial", 16, "bold"), text_color="white").pack(pady=14)

    f_cx_inp = ctk.CTkFrame(frame_caixa, fg_color="#f8f9fa", height=60)
    f_cx_inp.pack(fill="x", padx=12, pady=8); f_cx_inp.pack_propagate(False)
    f_cx_inner = ctk.CTkFrame(f_cx_inp, fg_color="transparent")
    f_cx_inner.pack(fill="both", expand=True, padx=12, pady=10)

    lbl_saldo_caixa = ctk.CTkLabel(f_cx_inner, text="Saldo: R$ 0,00",
                                   font=("Arial", 13, "bold"), text_color="#27AE60")
    lbl_saldo_caixa.pack(side="right", padx=12)

    ent_desc_c = ctk.CTkEntry(f_cx_inner, placeholder_text="DESCRIÇÃO", width=380)
    ent_desc_c.pack(side="left", padx=6)
    ent_val_c  = ctk.CTkEntry(f_cx_inner, placeholder_text="VALOR", width=110)
    ent_val_c.pack(side="left", padx=6)
    ctk.CTkButton(f_cx_inner, text="➕ ENTRADA", fg_color="#27AE60", width=110, height=34,
                  font=("Arial", 11, "bold"),
                  command=lambda: lancar_caixa("Entrada")).pack(side="left", padx=6)
    ctk.CTkButton(f_cx_inner, text="➖ SAÍDA", fg_color="#C0392B", width=110, height=34,
                  font=("Arial", 11, "bold"),
                  command=lambda: lancar_caixa("Saída")).pack(side="left", padx=6)

    scroll_fin = ctk.CTkScrollableFrame(frame_caixa, label_text="📋 HISTÓRICO DO MÊS", fg_color="#F2F3F4")
    scroll_fin.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ═══════════════════════════════════════════════════════════════════════════
    # ABA TOXICOLÓGICO
    # ═══════════════════════════════════════════════════════════════════════════
    frame_toxic = ctk.CTkFrame(area_main, fg_color="transparent")

    f_tx_hdr = ctk.CTkFrame(frame_toxic, fg_color="#001F3F", height=55)
    f_tx_hdr.pack(fill="x"); f_tx_hdr.pack_propagate(False)
    ctk.CTkLabel(f_tx_hdr, text="🧪 CONTROLE TOXICOLÓGICO",
                 font=("Arial", 16, "bold"), text_color="white").pack(pady=14)

    # ── Formulário de Cadastro ────────────────────────────────────────────────
    f_tx_inp = ctk.CTkFrame(frame_toxic, fg_color="#E8F6F3", corner_radius=8)
    f_tx_inp.pack(fill="x", padx=10, pady=(8, 4))
    ctk.CTkLabel(f_tx_inp, text="📝 CADASTRO", font=("Arial", 13, "bold")).pack(pady=(8, 4))

    gc = ctk.CTkFrame(f_tx_inp, fg_color="transparent")
    gc.pack(pady=(0, 10), padx=15)

    for col, lbl in enumerate(["Data Coleta","Nome Colaborador","CPF","Empresa","Enviado","Faturado",""]):
        ctk.CTkLabel(gc, text=lbl, font=("Arial", 10, "bold"),
                     text_color="#2C3E50").grid(row=0, column=col, sticky="w", padx=5, pady=(0,4))

    ent_data_toxic    = ctk.CTkEntry(gc, width=110)
    ent_data_toxic.insert(0, datetime.now().strftime("%d/%m/%Y"))
    ent_data_toxic.grid(row=1, column=0, padx=5)
    ent_nome_toxic    = ctk.CTkEntry(gc, width=190); ent_nome_toxic.grid(row=1, column=1, padx=5)
    ent_cpf_toxic     = ctk.CTkEntry(gc, width=120); ent_cpf_toxic.grid(row=1, column=2, padx=5)
    ent_cpf_toxic.bind("<KeyRelease>", _mascara_cpf)
    ent_empresa_toxic = ctk.CTkEntry(gc, width=150); ent_empresa_toxic.grid(row=1, column=3, padx=5)

    # ── Autocomplete empresa no Toxicológico ──────────────────────────────────
    _lb_emp_tx = tk.Listbox(frame_toxic, font=("Arial", 10), bg="white", fg="#1A5276",
                             selectbackground="#AED6F1", relief="solid", bd=1,
                             activestyle="none", highlightthickness=1,
                             highlightcolor="#1A5276", cursor="hand2", height=5)
    _job_emp_tx = [None]

    def _fechar_emp_tx(e=None):
        try: _lb_emp_tx.place_forget()
        except: pass

    def _mostrar_emp_tx(lista):
        if not lista:
            _fechar_emp_tx(); return
        _lb_emp_tx.delete(0, "end")
        for n in lista:
            _lb_emp_tx.insert("end", "  " + n)
        _lb_emp_tx.configure(height=min(len(lista), 6))
        app.update_idletasks()
        w = ent_empresa_toxic; rx, ry = 0, 0
        while w and w != frame_toxic:
            try: rx += w.winfo_x(); ry += w.winfo_y(); w = w.master
            except: break
        ew = ent_empresa_toxic.winfo_width()
        eh = ent_empresa_toxic.winfo_height()
        _lb_emp_tx.place(x=rx, y=ry + eh + 2, width=max(ew, 200))
        _lb_emp_tx.lift()

    def _sel_emp_tx(nome):
        nome = nome.strip()
        _fechar_emp_tx()
        ent_empresa_toxic.delete(0, "end")
        ent_empresa_toxic.insert(0, nome)

    def _digitar_emp_tx(event=None):
        if event and event.keysym in ("Up","Down","Return","Escape","Tab"): return
        termo = ent_empresa_toxic.get().strip().upper()
        if len(termo) < 2:
            _fechar_emp_tx(); return
        if _job_emp_tx[0]: app.after_cancel(_job_emp_tx[0])
        def _exec():
            try:
                r = executar_query(
                    "SELECT nome FROM empresas WHERE UPPER(nome) LIKE %s ORDER BY nome LIMIT 10",
                    (f"%{termo}%",), fetch=True) or []
                sugs = [row[0] for row in r if row[0]]
                _mostrar_emp_tx(sugs)
            except: pass
        _job_emp_tx[0] = app.after(300, _exec)

    def _nav_emp_tx(event):
        try:
            if not _lb_emp_tx.winfo_ismapped(): return
            sel = _lb_emp_tx.curselection(); size = _lb_emp_tx.size()
            if event.keysym == "Down":
                novo = (sel[0]+1) if sel else 0; novo = min(novo, size-1)
            elif event.keysym == "Up":
                novo = (sel[0]-1) if sel else size-1; novo = max(novo, 0)
            elif event.keysym in ("Return","Tab"):
                if sel: _sel_emp_tx(_lb_emp_tx.get(sel[0]))
                return
            else: return
            _lb_emp_tx.selection_clear(0,"end"); _lb_emp_tx.selection_set(novo); _lb_emp_tx.see(novo)
        except: pass

    ent_empresa_toxic.bind("<KeyRelease>", _digitar_emp_tx)
    ent_empresa_toxic.bind("<Down>",       _nav_emp_tx)
    ent_empresa_toxic.bind("<Up>",         _nav_emp_tx)
    ent_empresa_toxic.bind("<Return>",     _nav_emp_tx)
    ent_empresa_toxic.bind("<Escape>",     _fechar_emp_tx)
    ent_empresa_toxic.bind("<FocusOut>",   lambda e: app.after(300, _fechar_emp_tx))
    _lb_emp_tx.bind("<ButtonRelease-1>",
        lambda e: _sel_emp_tx(_lb_emp_tx.get(_lb_emp_tx.curselection()[0]).strip())
        if _lb_emp_tx.curselection() else None)

    cb_enviado_toxic  = ctk.CTkComboBox(gc, values=["NÃO","SIM"], width=75, state="readonly")
    cb_enviado_toxic.set("NÃO"); cb_enviado_toxic.grid(row=1, column=4, padx=5)
    cb_cobrado_toxic  = ctk.CTkComboBox(gc, values=["NÃO","SIM"], width=75, state="readonly")
    cb_cobrado_toxic.set("NÃO"); cb_cobrado_toxic.grid(row=1, column=5, padx=5)

    # Botões SALVAR + EDITAR lado a lado
    f_btns_tx = ctk.CTkFrame(gc, fg_color="transparent")
    f_btns_tx.grid(row=1, column=6, padx=6)
    btn_salvar_toxic = ctk.CTkButton(f_btns_tx, text="💾 SALVAR", width=105, height=32,
                                     fg_color="#27AE60", font=("Arial", 11, "bold"),
                                     command=salvar_toxic)
    btn_salvar_toxic.pack(side="left", padx=(0, 4))

    def _carregar_tx_selecionado():
        """Carrega o registro selecionado na tabela para edição no formulário."""
        try:
            item = tree_toxic.selection()[0]
            tid  = tree_toxic.item(item)["values"][0]
            d = executa("SELECT id, data_coleta_ts, data_coleta, nome_colaborador, empresa, cpf, enviado, cobrado FROM toxic WHERE id=%s",
                        (tid,), fetch=True)
            if d:
                d = d[0]
                global id_toxic_em_edicao
                id_toxic_em_edicao = d[0]
                ent_data_toxic.delete(0,"end");    ent_data_toxic.insert(0, d[2] or "")
                ent_nome_toxic.delete(0,"end");    ent_nome_toxic.insert(0, d[3] or "")
                ent_empresa_toxic.delete(0,"end"); ent_empresa_toxic.insert(0, d[4] or "")
                ent_cpf_toxic.delete(0,"end");     ent_cpf_toxic.insert(0, d[5] or "")
                cb_enviado_toxic.set("SIM" if d[6] else "NÃO")
                cb_cobrado_toxic.set("SIM" if d[7] else "NÃO")
                btn_salvar_toxic.configure(text="📝 ATUALIZAR", fg_color="#F39C12")
                show_status("✏️ Registro carregado — altere e clique ATUALIZAR")
        except IndexError:
            messagebox.showwarning("Aviso", "Selecione um registro na tabela!")
        except Exception as ex:
            log(f"Erro carregar tx: {ex}")

    ctk.CTkButton(f_btns_tx, text="✏️ EDITAR", width=105, height=32,
                  fg_color="#3498DB", font=("Arial", 11, "bold"),
                  command=_carregar_tx_selecionado).pack(side="left")

    # ── Filtro mensal + tabela ────────────────────────────────────────────────
    f_tx_filtro = ctk.CTkFrame(frame_toxic, fg_color="#F0F4F8", corner_radius=6, height=40)
    f_tx_filtro.pack(fill="x", padx=10, pady=(4, 2))
    f_tx_filtro.pack_propagate(False)

    ctk.CTkLabel(f_tx_filtro, text="📅 Mês:", font=("Arial", 10, "bold")).pack(side="left", padx=(12,4), pady=8)
    _meses_nomes = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    cb_mes_toxic_filtro = ctk.CTkComboBox(f_tx_filtro, values=_meses_nomes, width=120, state="readonly")
    cb_mes_toxic_filtro.set(_meses_nomes[datetime.now().month - 1])
    cb_mes_toxic_filtro.pack(side="left", padx=4, pady=8)

    ctk.CTkLabel(f_tx_filtro, text="Ano:", font=("Arial", 10, "bold")).pack(side="left", padx=(8,4))
    ent_ano_toxic_filtro = ctk.CTkEntry(f_tx_filtro, width=60)
    ent_ano_toxic_filtro.insert(0, str(datetime.now().year))
    ent_ano_toxic_filtro.pack(side="left", padx=4, pady=8)

    def _filtrar_toxic():
        try:
            mes = _meses_nomes.index(cb_mes_toxic_filtro.get()) + 1
            ano = int(ent_ano_toxic_filtro.get())
            atualizar_tabela_toxic(mes=mes, ano=ano)
        except Exception as ex:
            log(f"Filtro toxic: {ex}")

    ctk.CTkButton(f_tx_filtro, text="🔍 FILTRAR", width=90, height=28,
                  fg_color="#1A5276", font=("Arial", 10, "bold"),
                  command=_filtrar_toxic).pack(side="left", padx=8, pady=6)

    # Contador de pendentes (atualizado junto com a tabela)
    lbl_tx_contador = ctk.CTkLabel(f_tx_filtro, text="", font=("Arial", 10, "bold"),
                                   text_color="#C0392B")
    lbl_tx_contador.pack(side="right", padx=12)
    # Guardar referência para atualizar
    _atualizar_painel_pendentes.lbl_contador = lbl_tx_contador

    f_tx_tree = ctk.CTkFrame(frame_toxic, fg_color="white", corner_radius=8)
    f_tx_tree.pack(fill="both", expand=True, padx=10, pady=(2, 4))
    cols_tx = ("ID","Data","Nome","Empresa","CPF","Env.","Fat.","Prazo 7d","Situação")
    tree_toxic = ttk.Treeview(f_tx_tree, columns=cols_tx, show="headings", height=14)
    for c, w, anc in [("ID",50,"center"),("Data",95,"center"),("Nome",185,"w"),
                       ("Empresa",155,"w"),("CPF",115,"center"),("Env.",60,"center"),
                       ("Fat.",60,"center"),("Prazo 7d",90,"center"),("Situação",110,"center")]:
        tree_toxic.heading(c, text=c); tree_toxic.column(c, width=w, anchor=anc)
    sb_tx = ttk.Scrollbar(f_tx_tree, orient="vertical", command=tree_toxic.yview)
    tree_toxic.configure(yscrollcommand=sb_tx.set)
    tree_toxic.pack(side="left", fill="both", expand=True, padx=8, pady=8)
    sb_tx.pack(side="right", fill="y", pady=8)
    tree_toxic.bind("<Button-1>", on_treeview_click_toxic)

    # Barra de ações inferior (excluir)
    f_tx_acoes = ctk.CTkFrame(frame_toxic, fg_color="#E8F4FD", height=44)
    f_tx_acoes.pack(fill="x", padx=10, pady=(0, 8)); f_tx_acoes.pack_propagate(False)
    ctk.CTkLabel(f_tx_acoes, text="💡 Selecione um registro e clique EDITAR para alterar status",
                 font=("Arial", 10), text_color="#555").pack(side="left", padx=12, pady=12)

    def _excluir_tx():
        try:
            item = tree_toxic.selection()[0]
            acao_toxic("Excluir", tree_toxic.item(item)["values"][0])
        except IndexError:
            messagebox.showwarning("Aviso", "Selecione um registro!")

    ctk.CTkButton(f_tx_acoes, text="🗑️ EXCLUIR", width=100, height=30, fg_color="#E74C3C",
                  command=_excluir_tx).pack(side="right", padx=6, pady=7)

    # Abas removidas: Faturamento, Faturas, Vencimentos, Exames, Empresas (sem ecrã nem entradas no menu).

    # ═══════════════════════════════════════════════════════════════════════════
    # ABA RELATÓRIOS
    # ═══════════════════════════════════════════════════════════════════════════
    frame_relatorios = ctk.CTkFrame(area_main, fg_color="transparent")

    f_rel_hdr = ctk.CTkFrame(frame_relatorios, fg_color="#001F3F", height=55)
    f_rel_hdr.pack(fill="x"); f_rel_hdr.pack_propagate(False)
    ctk.CTkLabel(f_rel_hdr, text="📊 RELATÓRIOS EXCEL",
                 font=("Arial", 16, "bold"), text_color="white").pack(pady=14)

    f_rel_filtro = ctk.CTkFrame(frame_relatorios, fg_color="#E8F6F3", corner_radius=8)
    f_rel_filtro.pack(fill="x", padx=10, pady=10)
    ctk.CTkLabel(f_rel_filtro, text="📅 SELECIONAR MÊS",
                 font=("Arial", 14, "bold"), text_color="#2C3E50").pack(pady=(12, 6))
    f_rel_mes = ctk.CTkFrame(f_rel_filtro, fg_color="transparent")
    f_rel_mes.pack(pady=(0, 12))
    ctk.CTkLabel(f_rel_mes, text="Mês:", font=("Arial", 13, "bold")).pack(side="left", padx=10)
    cb_mes_relatorios = ctk.CTkComboBox(f_rel_mes, values=MESES_NOMES, width=150, font=("Arial", 12))
    cb_mes_relatorios.set(MESES_NOMES[datetime.now().month - 1]); cb_mes_relatorios.pack(side="left", padx=10)
    ctk.CTkLabel(f_rel_mes, text=f"Ano: {datetime.now().year}",
                 font=("Arial", 13, "bold")).pack(side="left", padx=10)

    f_rel_cards = ctk.CTkFrame(frame_relatorios, fg_color="#F8F9FA", corner_radius=8)
    f_rel_cards.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    ctk.CTkLabel(f_rel_cards, text="📋 RELATÓRIOS DISPONÍVEIS",
                 font=("Arial", 16, "bold"), text_color="#2C3E50").pack(pady=(16, 20))

    f_cards_row = ctk.CTkFrame(f_rel_cards, fg_color="transparent")
    f_cards_row.pack(pady=10)

    def _card_rel(parent, titulo, descricao, cor, fn_gerar):
        card = ctk.CTkFrame(parent, fg_color="white", corner_radius=12, width=270, height=190)
        card.pack(side="left", padx=12, pady=8); card.pack_propagate(False)
        ctk.CTkLabel(card, text=titulo, font=("Arial", 16, "bold"), text_color=cor).pack(pady=(14, 6))
        ctk.CTkLabel(card, text=descricao, font=("Arial", 10), text_color="#666",
                     justify="center").pack(pady=6, padx=10)
        ctk.CTkButton(card, text="📊 GERAR EXCEL", width=220, height=36,
                      fg_color=cor, font=("Arial", 12, "bold"),
                      command=fn_gerar).pack(pady=10)

    _card_rel(f_cards_row, "👥 RECEPÇÃO",
              "Lista completa de atendimentos\nEstatísticas por tipo e pagamento",
              "#3498DB", gerar_relatorio_recepcao)
    _card_rel(f_cards_row, "💰 CAIXA",
              "Movimentação financeira\nEntradas, saídas e saldo",
              "#27AE60", gerar_relatorio_caixa)
    _card_rel(f_cards_row, "🧪 TOXICOLÓGICO",
              "Controle de exames tox\nStatus por empresa",
              "#E67E22", gerar_relatorio_toxic)

    # ═══════════════════════════════════════════════════════════════════════════
    # ABA DOCUMENTOS (declarações e atestados — nome/CPF do banco + médico)
    # ═══════════════════════════════════════════════════════════════════════════
    frame_documentos = ctk.CTkFrame(area_main, fg_color="transparent")

    f_doc_hdr = ctk.CTkFrame(frame_documentos, fg_color="#5b4b8a", height=55)
    f_doc_hdr.pack(fill="x")
    f_doc_hdr.pack_propagate(False)
    ctk.CTkLabel(
        f_doc_hdr, text="📄 DOCUMENTOS CLÍNICOS",
        font=("Arial", 16, "bold"), text_color="white",
    ).pack(pady=14)

    scroll_doc = ctk.CTkScrollableFrame(frame_documentos, fg_color="#f5f6fa")
    scroll_doc.pack(fill="both", expand=True, padx=10, pady=(8, 10))

    sec_doc_pac = ctk.CTkFrame(scroll_doc, fg_color="#eef2ff", corner_radius=8)
    sec_doc_pac.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(
        sec_doc_pac, text="👤 PACIENTE / COLABORADOR (nome e CPF do cadastro)",
        font=("Arial", 12, "bold"), text_color="#1f4e79",
    ).pack(anchor="w", padx=12, pady=(10, 4))

    row_doc = ctk.CTkFrame(sec_doc_pac, fg_color="transparent")
    row_doc.pack(fill="x", padx=12, pady=(0, 10))

    fn_doc = ctk.CTkFrame(row_doc, fg_color="transparent")
    fn_doc.pack(side="left", fill="x", expand=True, padx=(0, 10))
    ctk.CTkLabel(
        fn_doc,
        text="Campo: Nome / Buscar",
        font=("Arial", 10, "bold"),
    ).pack(anchor="w")
    _ent_nome_doc = ctk.CTkEntry(fn_doc, placeholder_text="Nome conforme recepção / OFAT / pacientes...", height=34)
    _ent_nome_doc.pack(fill="x")

    fc_doc = ctk.CTkFrame(row_doc, fg_color="transparent")
    fc_doc.pack(side="left", padx=(0, 10))
    ctk.CTkLabel(fc_doc, text="CPF", font=("Arial", 10, "bold")).pack(anchor="w")
    _ent_cpf_doc = ctk.CTkEntry(fc_doc, placeholder_text="000.000.000-00", width=160, height=34)
    _ent_cpf_doc.pack()
    _ent_cpf_doc.bind("<KeyRelease>", _mascara_cpf)

    _lb_sug_doc = tk.Listbox(
        scroll_doc,
        font=("Arial", 11), bg="white", fg="#1A5276",
        selectbackground="#AED6F1", selectforeground="#1A5276",
        relief="solid", bd=1, activestyle="none",
        highlightthickness=1, highlightcolor="#1A5276",
        cursor="hand2",
    )

    def _fechar_sug_doc(e=None):
        try:
            _lb_sug_doc.place_forget()
        except Exception:
            pass

    def _mostrar_sug_doc(lista, texto_digitado=""):
        """Lista de sugestões + linha para usar/cadastrar o texto atual em pacientes."""
        linhas = list(lista) if lista else []
        td = (texto_digitado or "").strip()
        if len(td) >= 2:
            linhas.append(f"➕ Usar / cadastrar: {td.upper()}")
        if not linhas:
            _fechar_sug_doc()
            return
        _lb_sug_doc.delete(0, "end")
        for n in linhas:
            _lb_sug_doc.insert("end", "  " + n)
        qtd = min(len(linhas), 10)
        _lb_sug_doc.configure(height=qtd)
        app.update_idletasks()
        try:
            ex = _ent_nome_doc.winfo_rootx() - scroll_doc.winfo_rootx()
            ey = _ent_nome_doc.winfo_rooty() - scroll_doc.winfo_rooty()
        except Exception:
            ex = _ent_nome_doc.winfo_x()
            ey = _ent_nome_doc.winfo_y()
        ew = _ent_nome_doc.winfo_width()
        eh = _ent_nome_doc.winfo_height()
        _lb_sug_doc.place(x=ex, y=ey + eh + 2, width=max(ew, 320))
        _lb_sug_doc.lift()

    def _selecionar_colaborador_doc(entrada_sel):
        entrada_sel = entrada_sel.strip()
        _fechar_sug_doc()
        if "➕" in entrada_sel or "Usar / cadastrar:" in entrada_sel:
            if "Usar / cadastrar:" in entrada_sel:
                nome_novo = entrada_sel.split("Usar / cadastrar:", 1)[1].strip()
            else:
                nome_novo = entrada_sel.replace("➕", "").strip()
            nome_novo = nome_novo.upper()
            if len(nome_novo) < 2:
                return
            cadastrar_paciente_avulso_se_necessario(nome_novo)
            _ent_nome_doc.delete(0, "end")
            _ent_nome_doc.insert(0, nome_novo)
            _ent_nome_doc.focus_set()
            show_status("Nome confirmado — salvo em pacientes se era novo. Informe o CPF se necessário.")
            return
        if " — " in entrada_sel:
            nome_sel = entrada_sel.split(" — ")[0].strip()
        elif "  —  " in entrada_sel:
            nome_sel = entrada_sel.split("  —  ")[0].strip()
        else:
            nome_sel = entrada_sel.strip()
        _ent_nome_doc.delete(0, "end")
        _ent_nome_doc.insert(0, nome_sel)
        _ent_nome_doc.focus_set()
        try:
            dados_cache = _cache_dados_colaboradores.get(nome_sel.upper(), {})
            cpf_cache = dados_cache.get("cpf", "")
            if cpf_cache:
                _ent_cpf_doc.delete(0, "end")
                _ent_cpf_doc.insert(0, cpf_cache)
                show_status(f"✅ {nome_sel} — CPF do cadastro")
            else:
                def _buscar_cpf_bg():
                    try:
                        r = executar_query(
                            "SELECT cpf FROM pacientes WHERE UPPER(nome)=UPPER(%s) AND cpf IS NOT NULL LIMIT 1",
                            (nome_sel,), fetch=True,
                        )
                        if not r:
                            r = executar_query(
                                """SELECT cpf FROM recepcao WHERE UPPER(nome)=UPPER(%s) AND cpf IS NOT NULL
                                   ORDER BY data_ts DESC LIMIT 1""",
                                (nome_sel,), fetch=True,
                            )
                        if r and r[0][0]:
                            cpf_found = r[0][0]

                            def _aplicar_cpf_doc():
                                _ent_cpf_doc.delete(0, "end")
                                _ent_cpf_doc.insert(0, cpf_found)
                                show_status("✅ CPF encontrado")

                            gui_safe(_aplicar_cpf_doc)
                            if nome_sel.upper() in _cache_dados_colaboradores:
                                _cache_dados_colaboradores[nome_sel.upper()]["cpf"] = cpf_found
                    except Exception as ex:
                        log(f"Erro buscar CPF doc: {ex}")

                threading.Thread(target=_buscar_cpf_bg, daemon=True).start()
        except Exception as ex:
            log(f"Erro selecionar colaborador doc: {ex}")

    _job_nome_doc = [None]

    def _ao_digitar_nome_doc(event=None):
        if event and event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        texto = _ent_nome_doc.get().strip()
        if len(texto) < 2:
            _fechar_sug_doc()
            return
        if _job_nome_doc[0]:
            app.after_cancel(_job_nome_doc[0])

        def _exec_sug():
            sugestoes = buscar_nomes_colaboradores(texto)
            _mostrar_sug_doc(sugestoes, texto)

        _job_nome_doc[0] = app.after(150, _exec_sug)

    def _ao_navegar_sug_doc(event):
        try:
            if not _lb_sug_doc.winfo_ismapped():
                return
            sel = _lb_sug_doc.curselection()
            size = _lb_sug_doc.size()
            if event.keysym == "Down":
                novo = (sel[0] + 1) if sel else 0
                novo = min(novo, size - 1)
                _lb_sug_doc.selection_clear(0, "end")
                _lb_sug_doc.selection_set(novo)
                _lb_sug_doc.see(novo)
            elif event.keysym == "Up":
                novo = (sel[0] - 1) if sel else size - 1
                novo = max(novo, 0)
                _lb_sug_doc.selection_clear(0, "end")
                _lb_sug_doc.selection_set(novo)
                _lb_sug_doc.see(novo)
            elif event.keysym in ("Return", "Tab"):
                if sel:
                    _selecionar_colaborador_doc(_lb_sug_doc.get(sel[0]))
        except Exception:
            pass

    def _buscar_cpf_doc(e=None):
        cpf = _ent_cpf_doc.get().strip()
        if not cpf:
            return
        p = buscar_paciente_por_cpf(cpf)
        if p:
            nome = p["nome"].upper()
            _ent_nome_doc.delete(0, "end")
            _ent_nome_doc.insert(0, nome)
            show_status(f"✅ CPF encontrado: {nome}")
            return
        r = executar_query(
            """SELECT nome FROM recepcao
               WHERE cpf=%s AND nome IS NOT NULL
               ORDER BY data_ts DESC LIMIT 1""",
            (cpf,), fetch=True,
        )
        if r and r[0][0]:
            _ent_nome_doc.delete(0, "end")
            _ent_nome_doc.insert(0, r[0][0].upper())
            show_status(f"✅ CPF encontrado: {r[0][0].upper()}")

    _ent_nome_doc.bind("<KeyRelease>", _ao_digitar_nome_doc)
    _ent_nome_doc.bind("<Down>", _ao_navegar_sug_doc)
    _ent_nome_doc.bind("<Up>", _ao_navegar_sug_doc)
    _ent_nome_doc.bind("<Return>", _ao_navegar_sug_doc)
    _ent_nome_doc.bind("<Escape>", _fechar_sug_doc)
    _ent_nome_doc.bind("<FocusOut>", lambda e: app.after(300, _fechar_sug_doc))
    _ent_cpf_doc.bind("<FocusOut>", _buscar_cpf_doc)
    _lb_sug_doc.bind(
        "<ButtonRelease-1>",
        lambda e: _selecionar_colaborador_doc(_lb_sug_doc.get(_lb_sug_doc.curselection()[0]).strip())
        if _lb_sug_doc.curselection()
        else None,
    )

    sec_doc_med = ctk.CTkFrame(scroll_doc, fg_color="#fff8f0", corner_radius=8)
    sec_doc_med.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(
        sec_doc_med, text="🩺 MÉDICO (quem assina o documento)",
        font=("Arial", 12, "bold"), text_color="#1f4e79",
    ).pack(anchor="w", padx=12, pady=(10, 4))
    f_med_row = ctk.CTkFrame(sec_doc_med, fg_color="transparent")
    f_med_row.pack(fill="x", padx=12, pady=(0, 12))
    _cb_medico_doc = ctk.CTkComboBox(f_med_row, height=34, state="readonly")
    _cb_medico_doc.pack(fill="x")

    _var_periodo_doc = tk.StringVar(master=app, value="matutino")
    f_periodo_doc = ctk.CTkFrame(scroll_doc, fg_color="#e8f4fc", corner_radius=8)
    f_periodo_doc.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(
        f_periodo_doc,
        text="🕐 Período do atendimento (usado na Declaração de Comparecimento — impressão com período já marcado)",
        font=("Arial", 11, "bold"), text_color="#1f4e79",
    ).pack(anchor="w", padx=12, pady=(10, 4))
    f_rad_per = ctk.CTkFrame(f_periodo_doc, fg_color="transparent")
    f_rad_per.pack(fill="x", padx=12, pady=(0, 12))
    ctk.CTkRadioButton(
        f_rad_per, text="Matutino", variable=_var_periodo_doc, value="matutino",
        font=("Arial", 11), radiobutton_width=18, radiobutton_height=18,
    ).pack(side="left", padx=(0, 20))
    ctk.CTkRadioButton(
        f_rad_per, text="Vespertino", variable=_var_periodo_doc, value="vespertino",
        font=("Arial", 11), radiobutton_width=18, radiobutton_height=18,
    ).pack(side="left", padx=(0, 12))

    sec_doc_tipos = ctk.CTkFrame(scroll_doc, fg_color="#ffffff", corner_radius=8)
    sec_doc_tipos.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(
        sec_doc_tipos, text="📋 TIPO DE DOCUMENTO",
        font=("Arial", 12, "bold"), text_color="#1f4e79",
    ).pack(anchor="w", padx=12, pady=(12, 8))

    f_btns_doc = ctk.CTkFrame(sec_doc_tipos, fg_color="transparent")
    f_btns_doc.pack(fill="x", padx=12, pady=(0, 16))
    _doc_btn_style = {"width": 280, "height": 42, "font": ("Arial", 12, "bold")}

    ctk.CTkButton(
        f_btns_doc, text="Declaração de Comparecimento", fg_color="#1f4e79",
        command=lambda: emitir_documento_clinico("comparecimento"), **_doc_btn_style,
    ).pack(side="left", padx=6, pady=4)
    ctk.CTkButton(
        f_btns_doc, text="Acuidade Visual", fg_color="#2874a6",
        command=lambda: emitir_documento_clinico("acuidade"), **_doc_btn_style,
    ).pack(side="left", padx=6, pady=4)
    ctk.CTkButton(
        f_btns_doc, text="Acuidade + Ishihara", fg_color="#1f6f8b",
        command=lambda: emitir_documento_clinico("acuidade_ishihara"), **_doc_btn_style,
    ).pack(side="left", padx=6, pady=4)

    f_btns_doc2 = ctk.CTkFrame(sec_doc_tipos, fg_color="transparent")
    f_btns_doc2.pack(fill="x", padx=12, pady=(0, 16))
    ctk.CTkButton(
        f_btns_doc2, text="Teste de Romberg", fg_color="#148f77",
        command=lambda: emitir_documento_clinico("romberg"), **_doc_btn_style,
    ).pack(side="left", padx=6, pady=4)
    ctk.CTkButton(
        f_btns_doc2, text="Atestado Físico e Mental", fg_color="#6c3483",
        command=lambda: emitir_documento_clinico("atestado"), **_doc_btn_style,
    ).pack(side="left", padx=6, pady=4)

    # Evita corrida com inicializar_banco() em background: recarrega após o banco estar pronto
    app.after(200, atualizar_aba_documentos)
    app.after(2000, atualizar_aba_documentos)

    # ── RODAPÉ ────────────────────────────────────────────────────────────────
    f_rodape = ctk.CTkFrame(app, fg_color="#495057", height=36, corner_radius=0)
    f_rodape.pack(fill="x"); f_rodape.pack_propagate(False)
    ctk.CTkLabel(f_rodape, text="OFAT - SISTEMA DE GESTAO  |  DEVELOPED BY SARA SALES",
                 font=("Arial", 10), text_color="white").pack(side="left", padx=12, pady=10)

    # ── Indicador de conexão com o banco ──────────────────────────────────────
    lbl_conn = ctk.CTkLabel(f_rodape, text="🔴 Verificando...",
                            font=("Arial", 9), text_color="#adb5bd")
    lbl_conn.pack(side="right", padx=12, pady=10)

    def _rodape_ui_conectado_resumo(txt: str):
        lbl_conn.configure(text=txt, text_color="#2ECC71")

    def _rodape_ui_sem_ligacao():
        lbl_conn.configure(
            text="🔴 Sem Ligação — Dados Incompletos",
            text_color="#FF6B6B",
        )

    def _rodape_ui_conectado_curto():
        lbl_conn.configure(text="🟢 Conectado — Supabase", text_color="#2ECC71")

    def _callback_estado_conn(connected: bool):
        """Chamado pelo db_config.get_conn em falhas/recuperações (thread do pool)."""
        def _apply():
            if connected:
                _rodape_ui_conectado_curto()
            else:
                _rodape_ui_sem_ligacao()

        gui_safe(_apply)

    set_connection_status_callback(_callback_estado_conn)

    def _rodape_poll_worker():
        """SELECT 1 + sincronizar fila — só corre em thread (UI não trava)."""
        try:
            conn = get_conn()
            if not conn:
                raise RuntimeError("Sem conexão disponível no pool")
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            release_conn(conn)
            sincronizados = sincronizar_pendencias()
            pendentes = get_offline_queue_count()
            txt = f"🟢 Conectado — Supabase | Pendentes: {pendentes}"
            if sincronizados:
                txt += f" | Sync: +{sincronizados}"
            gui_safe(lambda t=txt: _rodape_ui_conectado_resumo(t))
        except Exception as e:
            audit_db_failure("_rodape_poll_worker", e)
            gui_safe(_rodape_ui_sem_ligacao)

        def _agendar_proxima():
            app.after(60000, lambda: threading.Thread(target=_rodape_poll_worker, daemon=True).start())

        gui_safe(_agendar_proxima)

    threading.Thread(target=_rodape_poll_worker, daemon=True).start()

    # ── INICIALIZAR ───────────────────────────────────────────────────────────
    sidebar_visible = False
    mostrar_aba("recepcao")
    # Dados já são pedidos em mostrar_aba("recepcao"); evitar segunda chamada (menos tráfego em rede fraca).

    def _exibir_janela_pronta():
        app.deiconify()
        try:
            _aplicar_icone_janela(app)
        except Exception:
            pass
        try:
            app.update_idletasks()
            app.state("zoomed")
        except Exception:
            try:
                app.attributes("-zoomed", True)
            except Exception:
                w, h = app.winfo_screenwidth(), app.winfo_screenheight()
                app.geometry(f"{min(1600, w - 80)}x{min(920, h - 80)}")
        try:
            app.lift()
            app.focus_force()
        except Exception:
            pass

    app.after(50, _exibir_janela_pronta)

    def _aviso_logo_documentos_obrigatoria():
        if not logo_documentos_configurada():
            messagebox.showwarning(
                "Logo obrigatória — documentos",
                "Sem a logo não é possível gerar documentos clínicos.\n\n" + _texto_local_logo_documentos(),
            )

    app.after(1800, _aviso_logo_documentos_obrigatoria)

    log("✅ Sistema APTUS integrado carregado!")
    log("📋 Abas: Recepção | Caixa | Toxicológico | Relatórios | Histórico | Documentos")


# =============================================================================
# EXECUÇÃO
# =============================================================================

if __name__ == "__main__":
    try:
        print("=" * 65)
        print("🚀 APTUS — SISTEMA INTEGRADO DE GESTÃO")
        print("   Recepção + Caixa + Toxicológico + Relatórios + Documentos")
        print("   Banco: PostgreSQL (Supabase) — Relacional Unificado")
        print("=" * 65)
        criar_interface()
        app.mainloop()
    except Exception as e:
        print(f"\n❌ ERRO FATAL: {e}")
        traceback.print_exc()
        err_txt = traceback.format_exc()
        try:
            p = os.path.join(_diretorio_app(), "aptus_startup_error.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{e}\n\n{err_txt}")
        except Exception:
            p = ""
        if getattr(sys, "frozen", False):
            try:
                r = tk.Tk()
                r.withdraw()
                messagebox.showerror(
                    "APTUS — erro ao iniciar",
                    f"O programa não conseguiu abrir.\n\n"
                    f"Detalhes guardados em:\n{p or '(falhou ao gravar)'}\n\n{e}",
                )
                r.destroy()
            except Exception:
                pass
        else:
            input("\nPressione Enter para sair...")
