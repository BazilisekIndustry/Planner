import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import sqlite3
import os
from datetime import datetime, timedelta, date
import math
import re
import calendar
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ============================
# KONFIGURACE
# ============================
DB_FILE = 'planner.db'
USERS_FILE = 'users.yaml'
LOCK_FILE = 'planner.lock'  # Pro read-only režim (jako v původní appce)

# Registrace fontu pro PDF (česká diakritika)
try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    PDF_FONT = 'DejaVu'
except Exception as e:
    print("Varování: Font DejaVuSans.ttf nebyl nalezen – diakritika v PDF nemusí fungovat.")
    PDF_FONT = 'Helvetica'

# ============================
# ČESKÉ SVÁTKY A POMOCNÉ FUNKCE
# ============================
def get_easter(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = (19 * a + b - b // 4 - ((b - (b + 8) // 25 + 1) // 3) + 15) % 30
    e = (32 + 2 * (b % 4) + 2 * (c // 4) - d - (c % 4)) % 7
    f = d + e - 7 * ((a + 11 * d + 22 * e) // 451) + 114
    month = f // 31
    day = f % 31 + 1
    easter_sunday = date(year, month, day)
    return easter_sunday + timedelta(days=1)  # Velikonoční pondělí

def get_holidays(year):
    return [
        date(year, 1, 1),
        get_easter(year),
        date(year, 5, 1),
        date(year, 5, 8),
        date(year, 7, 5),
        date(year, 7, 6),
        date(year, 9, 28),
        date(year, 10, 28),
        date(year, 11, 17),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 26),
    ]

def is_holiday(dt):
    holidays = get_holidays(dt.year)
    if dt.month == 1: holidays += get_holidays(dt.year - 1)
    if dt.month == 12: holidays += get_holidays(dt.year + 1)
    return dt in holidays

def is_weekend_or_holiday(dt):
    return dt.weekday() >= 5 or is_holiday(dt)

def is_working_day(dt, mode):
    if mode == '7.5' and dt.weekday() >= 5:
        return False
    return not is_holiday(dt)

def ddmmyyyy_to_yyyymmdd(date_str):
    if not date_str.strip():
        return None
    try:
        day, month, year = map(int, date_str.split('-'))
        return date(year, month, day).strftime('%Y-%m-%d')
    except:
        raise ValueError("Neplatný formát data. Použijte DD-MM-YYYY.")

def yyyymmdd_to_ddmmyyyy(date_str):
    if not date_str:
        return ""
    return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d-%m-%Y')

def validate_ddmmyyyy(date_str):
    pattern = re.compile(r'^\d{2}-\d{2}-\d{4}$')
    if not pattern.match(date_str):
        return False
    try:
        ddmmyyyy_to_yyyymmdd(date_str)
        return True
    except:
        return False

def calculate_end_date(start_yyyymmdd, hours, mode):
    if not start_yyyymmdd:
        return None
    capacity = 7.5 if mode == '7.5' else 24.0
    days_needed = math.ceil(hours / capacity)
    current = datetime.strptime(start_yyyymmdd, '%Y-%m-%d').date()
    days_count = 0
    while days_count < days_needed:
        if is_working_day(current, mode):
            days_count += 1
        current += timedelta(days=1)
    return (current - timedelta(days=1)).strftime('%Y-%m-%d')

# ============================
# DATABÁZOVÉ FUNKCE
# ============================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS workplaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        order_number INTEGER,
        workplace_id INTEGER,
        hours REAL,
        capacity_mode TEXT,
        start_date TEXT,
        end_date TEXT,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        reason TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (workplace_id) REFERENCES workplaces(id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        change_time TEXT,
        description TEXT
    )''')
    default_workplaces = [
        "HK1 Materialografie", "HK2 Žíhací pec, CNC", "HK3 EDM", "HK4 Autokláv",
        "HK5 Lis, pyknometrie", "HK6 Přijímací", "HK7 Trhačka", "HK8 Cyklovačka",
        "HK9 Přesné měření", "HK10 Creep", "PHK SEM", "PHK NI", "Laboratoř RKB"
    ]
    for name in default_workplaces:
        cur.execute('INSERT OR IGNORE INTO workplaces (name) VALUES (?)', (name,))
    conn.commit()
    conn.close()

def get_projects():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM projects ORDER BY id')
    projects = cur.fetchall()
    conn.close()
    return projects

def get_project_choices():
    projects = get_projects()
    return [str(p[0]) for p in projects] if projects else []

def get_workplaces():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM workplaces ORDER BY id')
    wps = cur.fetchall()
    conn.close()
    return wps

def get_workplace_name(wp_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT name FROM workplaces WHERE id = ?', (wp_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else f"ID {wp_id}"

def add_workplace(name):
    if not name.strip():
        return False
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO workplaces (name) VALUES (?)', (name.strip(),))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_workplace(wp_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM tasks WHERE workplace_id = ?', (wp_id,))
    count = cur.fetchone()[0]
    if count > 0:
        conn.close()
        return False
    cur.execute('DELETE FROM workplaces WHERE id = ?', (wp_id,))
    conn.commit()
    conn.close()
    return True

def add_project(project_id, name):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO projects (id, name) VALUES (?, ?)', (project_id, name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# (Zbytek databázových funkcí – add_task, update_task, get_task atd. – pošlu v části 2)
# ============================
# POKRAČOVÁNÍ DATABÁZOVÝCH FUNKCÍ
# ============================
def get_tasks(project_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks WHERE project_id = ? ORDER BY order_number', (project_id,))
    tasks = cur.fetchall()
    conn.close()
    return tasks

def add_task(project_id, order_number, workplace_id, hours, mode, start_ddmmyyyy=None, notes=''):
    start_yyyymmdd = ddmmyyyy_to_yyyymmdd(start_ddmmyyyy) if start_ddmmyyyy else None
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''INSERT INTO tasks
        (project_id, order_number, workplace_id, hours, capacity_mode, start_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (project_id, order_number, workplace_id, hours, mode, start_yyyymmdd, notes))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    if start_yyyymmdd:
        recalculate_from_task(task_id)
    return task_id

def update_task(task_id, field, value, is_internal=False):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if field in ('start_date', 'end_date') and value and not is_internal:
        value = ddmmyyyy_to_yyyymmdd(value)
    cur.execute(f'UPDATE tasks SET {field} = ? WHERE id = ?', (value, task_id))
    conn.commit()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('INSERT INTO change_log (task_id, change_time, description) VALUES (?, ?, ?)',
                (task_id, now, f'Updated {field} to {value}'))
    conn.commit()
    conn.close()

def get_task(task_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task = cur.fetchone()
    conn.close()
    return task

def recalculate_from_task(start_task_id):
    task = get_task(start_task_id)
    if not task:
        return
    project_id = task[1]
    tasks_sorted = sorted(get_tasks(project_id), key=lambda t: t[2])
    try:
        idx = next(i for i, t in enumerate(tasks_sorted) if t[0] == start_task_id)
    except StopIteration:
        return
    current_start_yyyymmdd = task[6]
    for t in tasks_sorted[idx:]:
        tid, pid, order, wp, hours, mode, start_int, end_int, status, notes, reason = t
        if status == 'done' and end_int:
            current_start_yyyymmdd = (datetime.strptime(end_int, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            continue
        if current_start_yyyymmdd is None:
            update_task(tid, 'start_date', None, is_internal=True)
            update_task(tid, 'end_date', None, is_internal=True)
            continue
        update_task(tid, 'start_date', current_start_yyyymmdd, is_internal=True)
        end_yyyymmdd = calculate_end_date(current_start_yyyymmdd, hours, mode)
        update_task(tid, 'end_date', end_yyyymmdd, is_internal=True)
        current_start_yyyymmdd = (datetime.strptime(end_yyyymmdd, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')

def get_colliding_projects(task_id):
    task = get_task(task_id)
    if not task or not task[6] or not task[7]:
        return []
    wp = task[3]
    start = datetime.strptime(task[6], '%Y-%m-%d').date()
    end = datetime.strptime(task[7], '%Y-%m-%d').date()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''SELECT DISTINCT t.project_id FROM tasks t
                  WHERE t.workplace_id = ? AND t.id != ?
                  AND t.start_date IS NOT NULL AND t.end_date IS NOT NULL
                  AND NOT (datetime(t.end_date) < datetime(?) OR datetime(t.start_date) > datetime(?))''',
                (wp, task_id, task[6], task[7]))
    colliding = [row[0] for row in cur.fetchall()]
    conn.close()
    return colliding

def check_collisions(task_id):
    return len(get_colliding_projects(task_id)) > 0

def mark_all_collisions():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT id FROM tasks WHERE start_date IS NOT NULL AND end_date IS NOT NULL')
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return {tid: check_collisions(tid) for tid in ids}

# ============================
# AUTHENTICATION A LOCK SOUBOR
# ============================
def create_users_file():
    if not os.path.exists(USERS_FILE):
        # Výchozí admin uživatel – heslo "admin123"
        hashed = stauth.Hasher(['admin123']).generate()[0]
        users = {
            'credentials': {
                'usernames': {
                    'admin': {
                        'name': 'Administrátor',
                        'password': hashed
                    }
                }
            },
            'cookie': {
                'expiry_days': 30,
                'key': 'planner_streamlit_key',
                'name': 'planner_cookie'
            }
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(users, f, default_flow_style=False, allow_unicode=True)

create_users_file()

with open(USERS_FILE, encoding='utf-8') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# ============================
# HLAVNÍ STREAMLIT APLIKACE
# ============================
st.set_page_config(page_title="Plánovač Horkých komor CVŘ", layout="wide")
st.title("🔥 Plánovač Horkých komor CVŘ")

# Login
name, authentication_status, username = authenticator.login('Přihlásit se', 'main')

if authentication_status:
    st.sidebar.success(f"Vítej, {name}!")
    authenticator.logout('Odhlásit se', 'sidebar')

    # Inicializace DB
    init_db()

    # Lock soubor pro read-only režim (jako v původní verzi)
    if not os.path.exists(LOCK_FILE):
        open(LOCK_FILE, 'w').close()
        read_only = False
    else:
        read_only = True

    if read_only:
        st.sidebar.warning("Appka je v režimu pouze pro čtení (jiný uživatel ji má otevřenou k úpravám).")

    # Sidebar menu
    option = st.sidebar.radio("Navigace", [
        "Přidat / Správa pracovišť",
        "Prohlížet / Upravovat úkoly",
        "HMG měsíční",
        "HMG roční"
    ])

    # ============================
    # 1. PŘIDAT / SPRÁVA PRACOVIŠŤ
    # ============================
    if option == "Přidat / Správa pracovišť":
        st.header("Správa pracovišť a přidávání projektů/úkolů")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Přidat pracoviště")
            new_wp = st.text_input("Název nového pracoviště")
            if st.button("Přidat pracoviště") and not read_only:
                if new_wp.strip():
                    if add_workplace(new_wp):
                        st.success(f"Pracoviště '{new_wp}' přidáno!")
                    else:
                        st.error("Pracoviště s tímto názvem již existuje.")
                else:
                    st.error("Zadejte název.")

            st.subheader("Přidat projekt")
            proj_id = st.text_input("Číslo projektu (povinné)")
            proj_name = st.text_input("Název projektu (volitelné)")
            if st.button("Přidat projekt") and not read_only:
                if proj_id.strip():
                    if add_project(proj_id.strip(), proj_name.strip()):
                        st.success(f"Projekt {proj_id} přidán!")
                    else:
                        st.error("Projekt s tímto číslem již existuje.")
                else:
                    st.error("Zadejte číslo projektu.")

        with col2:
            st.subheader("Existující pracoviště")
            workplaces = get_workplaces()
            for wp_id, wp_name in workplaces:
                col_a, col_b = st.columns([4,1])
                col_a.write(wp_name)
                if col_b.button("Smazat", key=f"del_wp_{wp_id}") and not read_only:
                    if delete_workplace(wp_id):
                        st.success(f"Pracoviště {wp_name} smazáno.")
                        st.rerun()
                    else:
                        st.error("Pracoviště je použito v úkolech – nelze smazat.")

        st.markdown("---")
        st.subheader("Přidat úkol")
        # Zde přidáme formulář na úkol v dalším kroku

    # ============================
    # DALŠÍ ZÁLOŽKY (zatím prázdné)
    # ============================
    elif option == "Prohlížet / Upravovat úkoly":
        st.header("Prohlížení a úprava úkolů")
        st.info("V dalším kroku zde bude editovatelná tabulka s AgGrid.")

    elif option == "HMG měsíční":
        st.header("HMG měsíční")
        st.info("Zde bude interaktivní Gantt diagram (Plotly).")

    elif option == "HMG roční":
        st.header("HMG roční")
        st.info("Zde bude heatmap obsazenosti pracovišť.")

elif authentication_status is False:
    st.error("Nesprávné uživatelské jméno nebo heslo")
elif authentication_status is None:
    st.warning("Zadejte přihlašovací údaje")

# ============================
# FOOTER + UKONČENÍ
# ============================
if authentication_status:
    st.sidebar.markdown("---")
    st.sidebar.caption("Streamlit verze plánovače – 2026")
    if st.sidebar.button("Odstranit lock soubor (pouze pro test)"):
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            st.sidebar.success("Lock odstraněn – appka je opět editovatelná.")

# Při ukončení appky (pro lokální běh) – odstraní lock, pokud byl vytvořen
# Streamlit to neumí automaticky, ale pro více uživatelů později použijeme lepší řešení