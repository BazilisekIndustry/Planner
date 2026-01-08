import streamlit as st
import streamlit_authenticator as stauth
import yaml
import os
from datetime import datetime, timedelta, date
import math
import re
import calendar
import sqlite3
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import hashlib  # Pro hashování hesel

# ============================
# KONFIGURACE
# ============================
DB_FILE = 'planner.db'
USERS_FILE = 'users.yaml'
LOCK_FILE = 'planner.lock'

# Registrace fontu pro PDF
try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    PDF_FONT = 'DejaVu'
except:
    print("Varování: Font DejaVuSans.ttf nebyl nalezen – diakritika v PDF nemusí fungovat správně.")
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
    return easter_sunday + timedelta(days=1)

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

def normalize_date_str(date_str):
    if not date_str:
        return None
    normalized = date_str.replace('.', '-').replace('/', '-')
    return normalized

def ddmmyyyy_to_yyyymmdd(date_str):
    if not date_str or not date_str.strip():
        return None
    normalized = normalize_date_str(date_str.strip())
    try:
        day, month, year = map(int, normalized.split('-'))
        return date(year, month, day).strftime('%Y-%m-%d')
    except:
        raise ValueError("Neplatný formát data. Použijte DD.MM.YYYY nebo DD-MM-YYYY.")

def yyyymmdd_to_ddmmyyyy(date_str):
    if not date_str:
        return ""
    return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')

def validate_ddmmyyyy(date_str):
    if not date_str:
        return True
    normalized = normalize_date_str(date_str)
    pattern = re.compile(r'^\d{2}-\d{2}-\d{4}$')
    if not pattern.match(normalized):
        return False
    try:
        ddmmyyyy_to_yyyymmdd(normalized)
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

def get_tasks(project_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks WHERE project_id = ? ORDER BY order_number', (project_id,))
    tasks = cur.fetchall()
    conn.close()
    return tasks

def is_order_unique(project_id, order_number, task_id=None):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if task_id:
        cur.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ? AND order_number = ? AND id != ?', (project_id, order_number, task_id))
    else:
        cur.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ? AND order_number = ?', (project_id, order_number))
    count = cur.fetchone()[0]
    conn.close()
    return count == 0

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

# Servisní funkce pro smazání úkolu (pro testování)
def delete_task(task_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    return True
# ============================
# USER MANAGEMENT FUNKCE
# ============================
def get_user_role(username):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    # Normalizace na lowercase pro case-insensitive porovnání
    usernames_lower = {k.lower(): v for k, v in config['credentials']['usernames'].items()}
    user_data = usernames_lower.get(username.lower(), {})
    return user_data.get('role', 'viewer')

def get_user_count():
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return len(config['credentials']['usernames'])

def add_user(username, name, password, role):
    if get_user_count() >= 6 and role != 'admin':  # Limit 5 + admin
        return False, "Maximální počet uživatelů (5 + admin) dosažen."
    # Odstraněno hashování – heslo jako plain text
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    if username in config['credentials']['usernames']:
        return False, "Uživatel již existuje."

    config['credentials']['usernames'][username] = {
        'name': name,
        'password': password,  # Plain text
        'role': role
    }

    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return True, "Uživatel přidán."

def reset_password(username, new_password='1234'):
    # Odstraněno hashování – heslo jako plain text
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    if username not in config['credentials']['usernames']:
        return False, "Uživatel nenalezen."

    config['credentials']['usernames'][username]['password'] = new_password  # Plain text

    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return True, "Heslo resetováno na 1234."

def change_password(username, new_password):
    # Odstraněno hashování – heslo jako plain text
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config['credentials']['usernames'][username]['password'] = new_password  # Plain text

    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return True, "Heslo změněno."

def create_users_file():
    if not os.path.exists(USERS_FILE):
        # Heslo jako plain text
        users = {
            'credentials': {
                'usernames': {
                    'admin': {
                        'name': 'Administrátor',
                        'password': 'admin123',  # Plain text
                        'role': 'admin'
                    }
                }
            },
            'cookie': {
                'expiry_days': 30,
                'key': 'planner_streamlit_secret_key',
                'name': 'planner_auth_cookie'
            },
            'preauthorized': []
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(users, f, default_flow_style=False, allow_unicode=True)

create_users_file()

with open(USERS_FILE, encoding='utf-8') as file:
    config = yaml.safe_load(file)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# ============================
# HLAVNÍ APLIKACE
# ============================
st.set_page_config(page_title="Plánovač Horkých komor CVŘ", page_icon=":radioactive:",layout="wide")
st.title("Plánovač Horkých komor CVŘ")

st.markdown("Vítejte v Plánovači Horkých komor CVŘ. Přihlaste se prosím. \n\n Pro založení nového uživatele kontaktuje petr.svrcula@cvrez.cz.")

authenticator.login(location='main')

if st.session_state.get('authentication_status'):
    username = st.session_state['username']
    role = get_user_role(username)
    name = st.session_state['name']

    st.sidebar.success(f"Vítej, {name} ({role})!")
    authenticator.logout('Odhlásit se', location='sidebar')

    init_db()

    read_only = (role == 'viewer')

    # Menu závisí na roli
    options = [
        "Přidat / Správa pracovišť",
        "Prohlížet / Upravovat úkoly",
        "HMG měsíční",
        "HMG roční",
        "Změnit heslo"
    ]
    if role == 'admin':
        options.append("User Management")

    option = st.sidebar.radio("Navigace", options)

    # ============================
    # 1. PŘIDAT / SPRÁVA PRACOVIŠŤ
    # ============================
    if option == "Přidat / Správa pracovišť":
        st.header("Správa pracovišť a přidávání projektů")

        if read_only:
            st.warning("V režimu prohlížení nelze provádět úpravy.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Přidat pracoviště")
                new_wp_name = st.text_input("Název nového pracoviště")
                if st.button("Přidat pracoviště"):
                    if new_wp_name.strip():
                        if add_workplace(new_wp_name.strip()):
                            st.success(f"Pracoviště '{new_wp_name}' přidáno!")
                            st.rerun()
                        else:
                            st.error("Pracoviště již existuje.")
                    else:
                        st.error("Zadejte název.")

                st.subheader("Přidat projekt")
                proj_id = st.text_input("Číslo projektu (povinné)")
                proj_name = st.text_input("Název projektu (volitelné)")
                if st.button("Přidat projekt"):
                    if proj_id.strip():
                        if add_project(proj_id.strip(), proj_name.strip()):
                            st.success(f"Projekt {proj_id} přidán!")
                            st.rerun()
                        else:
                            st.error("Projekt již existuje.")
                    else:
                        st.error("Zadejte číslo projektu.")

            with col2:
                st.subheader("Existující pracoviště")
                workplaces = get_workplaces()
                if workplaces:
                    for wp_id, wp_name in workplaces:
                        c1, c2 = st.columns([4,1])
                        c1.write(wp_name)
                        if c2.button("Smazat", key=f"del_{wp_id}"):
                            if delete_workplace(wp_id):
                                st.success(f"Pracoviště {wp_name} smazáno.")
                                st.rerun()
                            else:
                                st.error("Pracoviště je použito v úkolech.")
                else:
                    st.info("Žádné pracoviště.")

        st.markdown("---")
        st.subheader("Přidat úkol")

        if read_only:
            st.warning("V režimu prohlížení nelze přidávat úkoly.")
        else:
            with st.form(key="add_task_form"):
                col1, col2 = st.columns(2)

                with col1:
                    project_choices = get_project_choices()
                    if not project_choices:
                        st.warning("Nejprve přidejte projekt.")
                        project_id = None
                    else:
                        project_id = st.selectbox("Projekt", project_choices, key="add_proj")

                    order_number = st.number_input("Pořadí úkolu", min_value=1, step=1)

                    wp_names = [name for _, name in get_workplaces()]
                    wp_name = st.selectbox("Pracoviště", wp_names)
                    wp_id = next((wid for wid, name in get_workplaces() if name == wp_name), None)

                    hours = st.number_input("Počet hodin", min_value=0.5, step=0.5, format="%.1f")

                with col2:
                    capacity_mode = st.radio("Režim kapacity", ['7.5', '24'], horizontal=True)

                    start_date_obj = st.date_input("Začátek (volitelné)", value=None, format="DD.MM.YYYY")
                    start_ddmmyyyy = start_date_obj.strftime('%d.%m.%Y') if start_date_obj else None

                    notes = st.text_area("Poznámka")

                submitted = st.form_submit_button("Přidat úkol")
                if submitted:
                    if not project_id:
                        st.error("Vyberte projekt.")
                    elif not wp_id:
                        st.error("Vyberte pracoviště.")
                    elif hours <= 0:
                        st.error("Zadejte platný počet hodin.")
                    elif not is_order_unique(project_id, int(order_number)):
                        st.error(f"Pořadí {order_number} v projektu {project_id} již existuje – zadejte unikátní pořadí.")
                    else:
                        try:
                            task_id = add_task(
                                project_id=project_id,
                                order_number=int(order_number),
                                workplace_id=wp_id,
                                hours=float(hours),
                                mode=capacity_mode,
                                start_ddmmyyyy=start_ddmmyyyy,
                                notes=notes
                            )

                            if check_collisions(task_id):
                                colliding = get_colliding_projects(task_id)
                                st.warning(f"⚠️ Kolize s projekty: {', '.join(colliding)}")
                                col_y, col_n = st.columns(2)
                                if col_y.button("Přesto přidat"):
                                    st.success("Úkol přidán i přes kolizi.")
                                    st.rerun()
                                if col_n.button("Zrušit"):
                                    conn = sqlite3.connect(DB_FILE)
                                    cur = conn.cursor()
                                    cur.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
                                    conn.commit()
                                    conn.close()
                                    st.info("Přidání zrušeno.")
                            else:
                                st.success("Úkol úspěšně přidán!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Chyba: {e}")

    # ============================
    # 2. PROHLÍŽET / UPRAVOVAT ÚKOLY
    # ============================
    elif option == "Prohlížet / Upravovat úkoly":
        st.header("Prohlížet / Upravovat úkoly")

        if read_only:
            st.warning("V režimu prohlížení nelze provádět úpravy.")
        else:
            project_choices = get_project_choices()
            if not project_choices:
                st.info("Nejprve přidejte projekt.")
            else:
                selected_project = st.selectbox("Vyberte projekt", project_choices, key="edit_proj")

                tasks = get_tasks(selected_project)
                if not tasks:
                    st.info("Žádné úkoly.")
                else:
                    from st_aggrid import AgGrid, GridUpdateMode, DataReturnMode
                    import pandas as pd

                    data = []
                    collisions = mark_all_collisions()

                    for t in tasks:
                        tid, pid, order, wp_id, hours, mode, start_int, end_int, status, notes, reason = t
                        wp_name = get_workplace_name(wp_id)
                        start_disp = yyyymmdd_to_ddmmyyyy(start_int) if start_int else ""
                        end_disp = yyyymmdd_to_ddmmyyyy(end_int) if end_int else ""

                        coll_text = ""
                        if collisions.get(tid):
                            colliding = get_colliding_projects(tid)
                            coll_text = f"⚠️ Kolize: {', '.join(colliding)}"

                        status_display = status
                        if status == 'done':
                            status_display = "✅ Hotovo"
                        elif status == 'canceled':
                            status_display = f"❌ Zrušeno ({reason or '-'})"

                        data.append({
                            "ID": tid,
                            "Pořadí": order,
                            "Pracoviště": wp_name,
                            "Hodiny": hours,
                            "Režim": mode,
                            "Začátek": start_disp,
                            "Konec": end_disp,
                            "Stav": status_display,
                            "Poznámka": notes or "",
                            "Kolize": coll_text
                        })

                    df = pd.DataFrame(data)

                    grid_response = AgGrid(
                        df,
                        height=500,
                        editable=True,
                        gridOptions={
                            "columnDefs": [
                                {"field": "Pořadí", "width": 90},
                                {"field": "Pracoviště", "width": 220},
                                {"field": "Hodiny", "width": 100},
                                {"field": "Režim", "width": 100},
                                {"field": "Začátek", "editable": True, "width": 140},
                                {"field": "Konec", "width": 140},
                                {"field": "Stav", "width": 160},  # Opraveno: Přidána čárka za "Stav" a správný formát
                                {"field": "Poznámka", "width": 250},
                                {"field": "Kolize", "cellStyle": {"color": "red", "fontWeight": "bold"}, "width": 220}
                            ],
                            "defaultColDef": {"resizable": True, "sortable": True, "filter": True}
                        },
                        update_mode=GridUpdateMode.VALUE_CHANGED,
                        data_return_mode=DataReturnMode.AS_INPUT,
                        fit_columns_on_grid_load=True,
                        theme="streamlit"
                    )

                    updated_df = grid_response['data']

                    for _, row in updated_df.iterrows():
                        task_id = row['ID']
                        new_start_raw = row['Začátek']
                        new_start_str = str(new_start_raw).strip() if pd.notna(new_start_raw) else ""

                        original_task = get_task(task_id)
                        original_start = yyyymmdd_to_ddmmyyyy(original_task[6]) if original_task[6] else ""

                        if new_start_str != original_start:
                            if new_start_str and not validate_ddmmyyyy(new_start_str):
                                st.error(f"Neplatné datum u úkolu {row['Pořadí']}: '{new_start_str}'. Použijte DD.MM.YYYY nebo DD-MM-YYYY (např. 08.01.2026)")
                            else:
                                try:
                                    update_task(task_id, 'start_date', new_start_str)
                                    recalculate_from_task(task_id)
                                    st.success(f"Datum začátku úkolu {row['Pořadí']} změněno na {new_start_str} → termíny přepočítány.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Chyba při úpravě: {e}")

                    st.markdown("### Změna stavu úkolu")
                    selected_order = st.selectbox("Vyberte úkol", [row['Pořadí'] for _, row in df.iterrows()])
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Označit jako Hotovo"):
                            task = next(t for t in tasks if t[2] == selected_order)
                            update_task(task[0], 'status', 'done')
                            recalculate_from_task(task[0])
                            st.success("Úkol označen jako hotový.")
                            st.rerun()
                    with col2:
                        reason = st.text_input("Důvod zrušení")
                        if st.button("Označit jako Zrušeno"):
                            if reason.strip():
                                task = next(t for t in tasks if t[2] == selected_order)
                                update_task(task[0], 'reason', reason.strip())
                                update_task(task[0], 'status', 'canceled')
                                recalculate_from_task(task[0])
                                st.success("Úkol zrušen.")
                                st.rerun()
                            else:
                                st.error("Zadejte důvod.")

                    if role == 'admin':
                        st.markdown("### Servisní mazání úkolu (pouze pro admin)")
                        if tasks:
                            delete_order = st.selectbox("Vyberte úkol k smazání (podle pořadí)", [t[2] for t in tasks], key="delete_order")
                            task_to_delete = next(t for t in tasks if t[2] == delete_order)

                            st.write(f"Úkol: P{task_to_delete[1]}-{task_to_delete[2]} na pracovišti {get_workplace_name(task_to_delete[3])}")

                            if st.checkbox("Potvrďte smazání tohoto úkolu (neodvolatelné!)"):
                                if st.button("SMAZAT ÚKOL"):
                                    if delete_task(task_to_delete[0]):
                                        st.success(f"Úkol {delete_order} byl smazán.")
                                        recalculate_from_task(task_to_delete[0])  # Jen pro jistotu
                                        st.rerun()
                                    else:
                                        st.error("Chyba při mazání.")
                        else:
                            st.info("Žádné úkoly k mazání.")

    # ============================
    # ZMĚNIT HESLO
    # ============================
    elif option == "Změnit heslo":
        st.header("Změnit heslo")

        new_password = st.text_input("Nové heslo", type="password")
        confirm_password = st.text_input("Potvrďte nové heslo", type="password")

        if st.button("Změnit heslo"):
            if new_password == confirm_password and new_password.strip():
                success, message = change_password(username, new_password.strip())
                if success:
                    st.success(message)
                else:
                    st.error("Chyba při změně hesla.")
            else:
                st.error("Hesla se neshodují nebo jsou prázdná.")

    # ============================
    # USER MANAGEMENT (jen pro admin)
    # ============================
    elif option == "User Management" and role == 'admin':
        st.header("User Management – Pouze pro admin")

        # Přidat nového uživatele
        st.subheader("Přidat nového uživatele")
        new_username = st.text_input("Uživatelské jméno (povinné)")
        new_name = st.text_input("Jméno (povinné)")
        new_role = st.selectbox("Role", ["normal", "viewer"])
        if st.button("Přidat uživatele"):
            if new_username.strip() and new_name.strip():
                success, message = add_user(new_username.strip(), new_name.strip(), '1234', new_role)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
            else:
                st.error("Zadejte jméno a uživatelské jméno.")

        # Reset hesla
        st.subheader("Resetovat heslo uživatele")
        users = list(config['credentials']['usernames'].keys())
        reset_username = st.selectbox("Vyberte uživatele", users, key="reset_user")
        if st.button("Resetovat heslo na 1234"):
            success, message = reset_password(reset_username)
            if success:
                st.success(message)
            else:
                st.error(message)

        # Přehled uživatelů
        st.subheader("Aktuální uživatelé")
        users_data = []
        for u, details in config['credentials']['usernames'].items():
            users_data.append({
                "Uživatelské jméno": u,
                "Jméno": details.get('name'),
                "Role": details.get('role', 'viewer')
            })
        st.table(users_data)

    # ============================
    # 3. HMG MĚSÍČNÍ – Gantt + plný export do PDF
    # ============================
    elif option == "HMG měsíční":
        st.header("HMG měsíční – Přehled úkolů po dnech")

        import plotly.express as px
        import pandas as pd

        selected_year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="hmg_year")
        selected_month = st.number_input("Měsíc", min_value=1, max_value=12, value=datetime.now().month, key="hmg_month")

        # Vytvoř seznam všech dní v měsíci
        first_day = date(selected_year, selected_month, 1)
        if selected_month == 12:
            last_day = date(selected_year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(selected_year, selected_month + 1, 1) - timedelta(days=1)
        num_days = last_day.day

        # Načti úkoly
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute('SELECT * FROM tasks WHERE start_date IS NOT NULL AND end_date IS NOT NULL')
        all_tasks = cur.fetchall()
        conn.close()

        plot_data = []
        pdf_data = []  # Pro reportlab export
        workplaces_set = set()

        for t in all_tasks:
            tid, pid, order, wp_id, hours, mode, start_int, end_int, status, notes, reason = t
            if status == 'canceled':
                continue

            wp_name = get_workplace_name(wp_id)
            workplaces_set.add(wp_name)

            start_date = datetime.strptime(start_int, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_int, '%Y-%m-%d').date()

            if end_date < first_day or start_date > last_day:
                continue

            task_text = f"P{pid}-{order}"
            if check_collisions(tid):
                task_text += " !"

            color = "#4285f4"  # modrá
            if status == 'done':
                color = "#34a853"  # zelená
            if check_collisions(tid):
                color = "#ea4335"  # červená

            display_start = max(start_date, first_day)
            display_end = min(end_date, last_day)

            plot_data.append({
                "Pracoviště": wp_name,
                "Úkol": task_text,
                "Start": display_start,
                "Finish": display_end + timedelta(days=1),
                "Color": color
            })

            # Data pro PDF (stejný formát jako v původní appce)
            pdf_data.append({
                "wp_name": wp_name,
                "task_text": task_text,
                "start_day": display_start.day,
                "end_day": display_end.day,
                "color": color
            })

        if not plot_data:
            st.info(f"Žádné úkoly pro {calendar.month_name[selected_month]} {selected_year}.")
        else:
            df = pd.DataFrame(plot_data)

            fig = px.timeline(
                df,
                x_start="Start",
                x_end="Finish",
                y="Pracoviště",
                color="Color",
                color_discrete_map={"#4285f4": "#4285f4", "#34a853": "#34a853", "#ea4335": "#ea4335"},
                hover_name="Úkol",
                title=f"HMG HK – {calendar.month_name[selected_month]} {selected_year}",
                height=400 + len(workplaces_set) * 40
            )

            fig.update_xaxes(
                tickformat="%d",
                tickmode="linear",
                dtick=86400000.0,
                range=[first_day, last_day + timedelta(days=1)]
            )
            fig.update_yaxes(autorange="reversed")
            fig.update_layout(bargap=0.2, bargroupgap=0.1, showlegend=False)

            st.plotly_chart(fig, width='stretch')

            # ============================
            # EXPORT DO PDF (plný reportlab jako v původní verzi)
            # ============================
            if st.button("Exportovat HMG měsíční do PDF"):
                file_name = f"HMG_mesicni_{selected_year}_{selected_month:02d}.pdf"
                pdf = pdf_canvas.Canvas(file_name, pagesize=landscape(A4))
                width, height = landscape(A4)

                # Název
                pdf.setFont(PDF_FONT, 16)
                pdf.drawCentredString(width / 2, height - 0.8 * inch, f"HMG HK – {calendar.month_name[selected_month]} {selected_year}")

                # Parametry layoutu
                left_margin = 1.0 * inch
                wp_col_width = 2.0 * inch
                day_col_width = (width - left_margin - wp_col_width - 0.8 * inch) / num_days
                header_y = height - 1.5 * inch
                row_height = (height - 2.5 * inch) / len(workplaces_set) if workplaces_set else 40

                # Hlavička dnů
                pdf.setFont(PDF_FONT, 10)
                for d in range(1, num_days + 1):
                    current_date = date(selected_year, selected_month, d)
                    x = left_margin + wp_col_width + (d - 1) * day_col_width
                    fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
                    pdf.setFillColorRGB(*fill_color)
                    pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))

                # Čáry
                pdf.setStrokeColorRGB(0, 0, 0)
                pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)

                # Seřazená pracoviště (shora dolů)
                sorted_workplaces = sorted(workplaces_set)

                colors_rgb = {
                    "#4285f4": (0.26, 0.52, 0.96),  # modrá
                    "#34a853": (0.20, 0.66, 0.32),  # zelená
                    "#ea4335": (0.92, 0.26, 0.21)   # červená
                }

                for i, wp_name in enumerate(sorted_workplaces):
                    y_top = header_y - 20 - i * row_height
                    y_bottom = y_top - row_height

                    # Název pracoviště
                    pdf.setFillColorRGB(0, 0, 0)
                    pdf.setFont(PDF_FONT, 9)
                    pdf.drawString(left_margin, y_top - row_height / 2, wp_name)

                    # Vodorovná čára
                    pdf.line(left_margin, y_bottom, width - 0.8 * inch, y_bottom)

                    # Úkoly na tomto pracovišti
                    for item in pdf_data:
                        if item["wp_name"] != wp_name:
                            continue
                        x1 = left_margin + wp_col_width + (item["start_day"] - 1) * day_col_width
                        x2 = left_margin + wp_col_width + item["end_day"] * day_col_width
                        rgb = colors_rgb.get(item["color"], (0.26, 0.52, 0.96))
                        pdf.setFillColorRGB(*rgb)
                        pdf.rect(x1, y_bottom + 5, x2 - x1, row_height - 10, fill=1, stroke=1)

                        # Text úkolu
                        pdf.setFillColorRGB(1, 1, 1)
                        pdf.setFont(PDF_FONT, 8)
                        pdf.drawCentredString((x1 + x2) / 2, y_bottom + row_height / 2, item["task_text"])

                pdf.save()

                with open(file_name, "rb") as f:
                    st.download_button(
                        label="Stáhnout PDF s HMG",
                        data=f.read(),
                        file_name=file_name,
                        mime="application/pdf"
                    )

        # ============================
    # 4. HMG ROČNÍ – HEATMAP s správnými barvami
    # ============================
        # ============================
    # 4. HMG ROČNÍ – Heatmap s chronologickým pořadím měsíců
    # ============================
    elif option == "HMG roční":
        st.header("HMG roční – Heatmap obsazenosti pracovišť")

        import plotly.express as px
        import pandas as pd

        year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="year_rocni")

        MONTH_CAPACITY = 200.0

        workplaces = get_workplaces()
        # Chronologické pořadí měsíců (důležité!)
        months = ['Led', 'Úno', 'Bře', 'Dub', 'Kvě', 'Čer', 'Čvc', 'Srp', 'Zář', 'Říj', 'Lis', 'Pro']
        month_order = {m: i for i, m in enumerate(months)}  # Mapa pro správné řazení

        occupancy = {wp_name: [0.0 for _ in range(12)] for _, wp_name in workplaces}

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute('SELECT id, workplace_id, hours, capacity_mode, start_date, end_date, status FROM tasks WHERE start_date IS NOT NULL AND end_date IS NOT NULL')
        tasks = cur.fetchall()
        conn.close()

        for t in tasks:
            tid, wp_id, total_hours, mode, start_str, end_str, status = t
            if status == 'canceled':
                continue
            wp_name = get_workplace_name(wp_id)
            if wp_name not in occupancy:
                continue

            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

            if end_date.year < year or start_date.year > year:
                continue

            current = max(start_date, date(year, 1, 1))
            end_in_year = min(end_date, date(year, 12, 31))
            working_days = 0
            while current <= end_in_year:
                if is_working_day(current, mode):
                    working_days += 1
                current += timedelta(days=1)

            if working_days == 0:
                continue

            hours_per_day = total_hours / working_days
            current = max(start_date, date(year, 1, 1))
            while current <= end_in_year:
                if is_working_day(current, mode):
                    month_idx = current.month - 1
                    occupancy[wp_name][month_idx] += hours_per_day
                current += timedelta(days=1)

        # Převod na DataFrame
        data = []
        for wp_name, occ in occupancy.items():
            for m_idx, occ_hours in enumerate(occ):
                percent = round((occ_hours / MONTH_CAPACITY) * 100, 1)
                data.append({
                    "Pracoviště": wp_name,
                    "Měsíc": months[m_idx],
                    "Hodiny": round(occ_hours, 1),
                    "% využití": percent
                })

        if not data:
            st.info(f"Žádné úkoly pro rok {year}.")
        else:
            df = pd.DataFrame(data)
            # Zajistíme chronologické pořadí měsíců
            df['Měsíc_order'] = df['Měsíc'].map(month_order)
            df = df.sort_values(['Pracoviště', 'Měsíc_order'])

            pivot_df = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
            # Zajistíme správné pořadí sloupců
            pivot_df = pivot_df[months]

            fig = px.imshow(
                pivot_df,
                labels=dict(color="% využití"),
                title=f"Obsazenost pracovišť {year}",
                color_continuous_scale=["#90EE90", "#FFFF99", "#FFB366", "#FF6B6B"],
                zmin=0,
                zmax=120
            )

            fig.update_layout(
                height=400 + len(workplaces) * 35,
                coloraxis_colorbar=dict(
                    title="% využití",
                    tickvals=[0, 50, 80, 100, 120],
                    ticktext=["0%", "50%", "80%", "100%", ">100%"]
                )
            )

            st.plotly_chart(fig, width='stretch')

            # Přehledová tabulka s chronologickým pořadím
                        # Přehledová tabulka s chronologickým pořadím – opravená pro multi-level sloupce
            st.subheader("Detailní přehled (hodiny / %)")
            
            # Pivot pro hodiny
            hours_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="Hodiny")
            hours_pivot = hours_pivot[months]  # Chronologické pořadí
            
            # Pivot pro % využití
            percent_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
            percent_pivot = percent_pivot[months]
            
            # Spojíme do jednoho DataFrame s multi-level sloupci
            combined = pd.concat([hours_pivot, percent_pivot], axis=1, keys=["Hodiny", "% využití"])
            
            # Seřadíme sloupce podle měsíců
            combined_columns = []
            for month in months:
                if ("Hodiny", month) in combined.columns:
                    combined_columns.append(("Hodiny", month))
                if ("% využití", month) in combined.columns:
                    combined_columns.append(("% využití", month))
            combined = combined[combined_columns]
            
            st.dataframe(combined, width='stretch')

elif st.session_state.get('authentication_status') is False:
    st.error("Nesprávné přihlašovací údaje")

elif st.session_state.get('authentication_status') is None:
    st.warning("Přihlaste se prosím")

# ============================
# FOOTER
# ============================
if st.session_state.get('authentication_status'):
    st.sidebar.markdown("---")
    st.sidebar.markdown("Plánovač Horkých komor v1.0")
    st.sidebar.caption("petr.svrcula@cvrez.cz")
    