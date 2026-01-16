# utils/common.py
import streamlit as st
from streamlit_authenticator import Authenticate
from streamlit_authenticator.utilities.hasher import Hasher
from supabase import create_client
from datetime import datetime, timedelta, date
import math
import re
import calendar
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import pandas as pd
from st_aggrid import AgGrid, GridUpdateMode, DataReturnMode
import plotly.express as px
import os

# ──────────────────────────────────────────────────────────────
# KONFIGURACE
# ──────────────────────────────────────────────────────────────
SUPABASE_URL = st.secrets["supabase_url"]
SUPABASE_KEY = st.secrets["supabase_key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

COOKIE_NAME = 'planner_auth_cookie'
COOKIE_KEY = st.secrets.get("cookie_key", "planner_streamlit_secret_key")
COOKIE_EXPIRY_DAYS = 30




# ──────────────────────────────────────────────────────────────
# HASHOVÁNÍ HESLA
# ──────────────────────────────────────────────────────────────
def hash_single_password(plain_password: str) -> str:
    temp_credentials = {
        "usernames": {"temp_user": {"name": "Temp", "password": plain_password}}
    }
    Hasher.hash_passwords(temp_credentials)
    return temp_credentials["usernames"]["temp_user"]["password"]

# ──────────────────────────────────────────────────────────────
# NAČÍTÁNÍ UŽIVATELŮ
# ──────────────────────────────────────────────────────────────
def load_users_from_db():
    try:
        response = supabase.table('app_users')\
                   .select("username, name, password_hash, role, email")\
                   .execute()
        users_dict = {}
        for row in response.data:
            users_dict[row['username']] = {
                'name': row['name'],
                'password': row['password_hash'],
                'role': row.get('role', 'viewer'),
            }
            if row.get('email'):
                users_dict[row['username']]['email'] = row['email']
        return {"usernames": users_dict}
    except Exception as e:
        print(f"[ERROR] Načítání uživatelů selhalo: {str(e)}")
        return {"usernames": {}}

#============================
# ČESKÉ SVÁTKY A POMOCNÉ FUNKCE
# ============================
# ... (zde zůstávají všechny původní funkce beze změny - get_easter, get_holidays, is_holiday, ... až po recalculate_project)
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
    if dt.month == 1:
        holidays += get_holidays(dt.year - 1)
    if dt.month == 12:
        holidays += get_holidays(dt.year + 1)
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
    return re.sub(r'[./]', '-', date_str.strip())

def ddmmyyyy_to_yyyymmdd(date_str):
    if not date_str or not date_str.strip():
        return None
    normalized = normalize_date_str(date_str)
    try:
        day, month, year = map(int, normalized.split('-'))
        dt = date(year, month, day)
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        raise ValueError("Neplatný formát data. Použijte např. 1.1.2026, 01.01.2026, 1-1-2026 apod.")

def yyyymmdd_to_ddmmyyyy(date_str):
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')
    except Exception:
        return ""

def validate_ddmmyyyy(date_str):
    if not date_str:
        return True
    normalized = normalize_date_str(date_str)
    pattern = re.compile(r'^(\d{1,2})-(\d{1,2})-(\d{4})$')
    match = pattern.match(normalized)
    if not match:
        return False
    try:
        day, month, year = map(int, match.groups())
        if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2100):
            return False
        return True
    except Exception:
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

def get_next_working_day_after(date_str, capacity_mode):
    if not date_str:
        return None
    current = datetime.strptime(date_str, '%Y-%m-%d').date() + timedelta(days=1)
    while not is_working_day(current, capacity_mode):
        current += timedelta(days=1)
    return current.strftime('%Y-%m-%d')
# ============================
# DATABÁZOVÉ FUNKCE
# ============================
# ... (zde zůstávají všechny původní funkce beze změny - init_db až po delete_project)
def init_db():
    pass

def get_projects():
    response = supabase.table('projects').select('id, name').execute()
    return [(row['id'], row['name']) for row in response.data]

def get_project_choices():
    projects = get_projects()
    return [str(p[0]) for p in projects] if projects else []

def get_workplaces():
    response = supabase.table('workplaces').select('id, name').execute()
    return [(row['id'], row['name']) for row in response.data]

def get_workplace_name(wp_id):
    response = supabase.table('workplaces').select('name').eq('id', wp_id).execute()
    return response.data[0]['name'] if response.data else f"ID {wp_id}"

def add_workplace(name):
    if not name.strip():
        return False
    try:
        supabase.table('workplaces').insert({'name': name.strip()}).execute()
        return True
    except Exception:
        return False

def delete_workplace(wp_id):
    response = supabase.table('tasks').select('id').eq('workplace_id', wp_id).execute()
    if response.data:
        return False
    supabase.table('workplaces').delete().eq('id', wp_id).execute()
    return True

def add_project(project_id, name):
    try:
        supabase.table('projects').insert({'id': project_id, 'name': name}).execute()
        return True
    except Exception:
        return False

def get_tasks(project_id):
    response = supabase.table('tasks').select('*').eq('project_id', project_id).execute()
    return response.data

def add_task(project_id, workplace_id, hours, mode, start_ddmmyyyy=None, notes='', bodies_count=1, is_active=True, parent_id=None):
    start_yyyymmdd = ddmmyyyy_to_yyyymmdd(start_ddmmyyyy) if start_ddmmyyyy else None
    data = {
        'project_id': project_id,
        'workplace_id': workplace_id,
        'hours': hours,
        'capacity_mode': mode,
        'start_date': start_yyyymmdd,
        'notes': notes,
        'bodies_count': bodies_count,
        'is_active': is_active
    }
    response = supabase.table('tasks').insert(data).execute()
    task_id = response.data[0]['id']
    if parent_id:
        supabase.table('task_dependencies').insert({'task_id': task_id, 'parent_id': parent_id}).execute()
    if start_yyyymmdd:
        recalculate_from_task(task_id)
    return task_id

def update_task(task_id, field, value, is_internal=False):
    if field in ('start_date', 'end_date') and value and not is_internal:
        value = ddmmyyyy_to_yyyymmdd(value)
    supabase.table('tasks').update({field: value}).eq('id', task_id).execute()
    now = datetime.now().isoformat()
    supabase.table('change_log').insert({
        'task_id': task_id,
        'change_time': now,
        'description': f'Updated {field} to {value}',
        'changed_by': st.session_state.get('username', 'system')
    }).execute()

def get_task(task_id):
    response = supabase.table('tasks').select('*').eq('id', task_id).execute()
    return response.data[0] if response.data else None

def get_parent(task_id):
    response = supabase.table('task_dependencies').select('parent_id').eq('task_id', task_id).execute()
    return response.data[0]['parent_id'] if response.data else None

def get_children(parent_id):
    response = supabase.table('task_dependencies').select('task_id').eq('parent_id', parent_id).execute()
    return [row['task_id'] for row in response.data]

def has_cycle(task_id):
    visited = set()
    current = task_id
    while current:
        if current in visited:
            return True
        visited.add(current)
        current = get_parent(current)
    return False

def recalculate_from_task(task_id):
    task = get_task(task_id)
    if not task:
        return
    if task['status'] == 'canceled':
        update_task(task_id, 'end_date', None, is_internal=True)
        child_start = None
    else:
        if task['start_date']:
            end_date = calculate_end_date(
                task['start_date'],
                task['hours'],
                task['capacity_mode']
            )
            update_task(task_id, 'end_date', end_date, is_internal=True)
            child_start = get_next_working_day_after(end_date, task['capacity_mode'])
        else:
            update_task(task_id, 'end_date', None, is_internal=True)
            child_start = None
    children = get_children(task_id)
    for child_id in children:
        child = get_task(child_id)
        if not child or child['status'] == 'canceled':
            continue
        update_task(child_id, 'start_date', child_start, is_internal=True)
        recalculate_from_task(child_id)

def recalculate_project(project_id):
    tasks = get_tasks(project_id)
    root_ids = [t['id'] for t in tasks if not get_parent(t['id'])]
    incompletes = [rid for rid in root_ids if not get_task(rid)['start_date']]
    if incompletes:
        st.error(f"Chybí datum zahájení u root úkolů: {', '.join(map(str, incompletes))}")
        return
    for root_id in root_ids:
        recalculate_from_task(root_id)

def get_colliding_projects_simulated(workplace_id, start_date, end_date):
    if not start_date or not end_date:
        return []
    try:
        new_start = datetime.strptime(start_date, '%Y-%m-%d').date()
        new_end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except Exception:
        return []
    response = (
        supabase.table('tasks')
        .select('project_id, start_date, end_date')
        .eq('workplace_id', workplace_id)
        .not_.is_('start_date', 'null')
        .not_.is_('end_date', 'null')
        .execute()
    )
    colliding = []
    for row in response.data:
        try:
            row_start = datetime.strptime(row['start_date'], '%Y-%m-%d').date()
            row_end = datetime.strptime(row['end_date'], '%Y-%m-%d').date()
            if not (new_end < row_start or new_start > row_end):
                colliding.append(row['project_id'])
        except Exception:
            continue
    return list(set(colliding))

def get_colliding_projects(task_id):
    task = get_task(task_id)
    if not task or not task.get('start_date') or not task.get('end_date'):
        return []
    wp = task['workplace_id']
    start = datetime.strptime(task['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(task['end_date'], '%Y-%m-%d').date()
    response = (
        supabase.table('tasks')
        .select('project_id, start_date, end_date')
        .eq('workplace_id', wp)
        .neq('id', task_id)
        .not_.is_('start_date', 'null')
        .not_.is_('end_date', 'null')
        .execute()
    )
    colliding = []
    for row in response.data:
        try:
            row_start = datetime.strptime(row['start_date'], '%Y-%m-%d').date()
            row_end = datetime.strptime(row['end_date'], '%Y-%m-%d').date()
            if not (end < row_start or start > row_end):
                colliding.append(row['project_id'])
        except Exception:
            continue
    return list(set(colliding))

def check_collisions(task_id):
    return len(get_colliding_projects(task_id)) > 0

def mark_all_collisions():
    response = supabase.table('tasks').select('id').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
    ids = [row['id'] for row in response.data]
    return {tid: check_collisions(tid) for tid in ids}

def delete_task(task_id):
    try:
        supabase.table('change_log').delete().eq('task_id', task_id).execute()
        supabase.table('task_dependencies').delete().eq('task_id', task_id).execute()
        supabase.table('task_dependencies').delete().eq('parent_id', task_id).execute()
        supabase.table('tasks').delete().eq('id', task_id).execute()
        return True
    except Exception as e:
        st.error(f"Chyba při mazání úkolu: {str(e)}")
        return False

def delete_project(project_id):
    try:
        tasks_response = supabase.table('tasks').select('id').eq('project_id', project_id).execute()
        for task in tasks_response.data:
            supabase.table('change_log').delete().eq('task_id', task['id']).execute()
            supabase.table('task_dependencies').delete().eq('task_id', task['id']).execute()
            supabase.table('task_dependencies').delete().eq('parent_id', task['id']).execute()
            supabase.table('tasks').delete().eq('id', task['id']).execute()
        supabase.table('projects').delete().eq('id', project_id).execute()
        return True
    except Exception as e:
        st.error(f"Chyba při mazání projektu {project_id}: {str(e)}")
        return False

# ============================
# USER MANAGEMENT FUNKCE – vše přes Supabase
# ============================

def delete_user(username: str):
    """
    Smaže uživatele z tabulky app_users podle username.
    Vrátí (True, "Úspěch") nebo (False, "Chyba / zpráva")
    """
    if not username.strip():
        return False, "Uživatelské jméno je prázdné."

    try:
        # 1. Najdi, jestli uživatel existuje (pro lepší zprávu)
        check = supabase.table('app_users')\
                 .select("username")\
                 .eq("username", username)\
                 .execute()

        if not check.data:
            return False, f"Uživatel '{username}' neexistuje."

        # 2. Smaž uživatele
        response = supabase.table('app_users')\
                   .delete()\
                   .eq("username", username)\
                   .execute()

        if response.data:
            # Vyčisti cache (pokud máš cachovanou funkci)
            # load_users_from_db.clear()  # ← odkomentuj jen pokud máš @st.cache_data

            return True, f"Uživatel '{username}' byl úspěšně smazán."
        else:
            return False, "Smazání selhalo (žádný řádek nebyl ovlivněn)."

    except Exception as e:
        return False, f"Chyba při mazání uživatele: {str(e)}"
    
def add_user(username, name, password, role, email=""):
    try:
        count_response = supabase.table('app_users').select("count", count="exact").execute()
        user_count = count_response.count
        if user_count >= 6 and role != 'admin':
            return False, "Maximální počet uživatelů (5 + admin) dosažen."
    except Exception as e:
        return False, f"Chyba při kontrole počtu uživatelů: {e}"

    check = supabase.table('app_users').select("username").eq("username", username).execute()
    if check.data:
        return False, "Uživatel s tímto uživatelským jménem již existuje."

    # Správné hashování pro verzi 0.4.2
    hashed_pw = hash_single_password(password)

    data = {
        "username": username,
        "name": name,
        "password_hash": hashed_pw,
        "role": role,
    }
    if email.strip():
        data["email"] = email.strip()

    try:
        response = supabase.table('app_users').insert(data).execute()
        if response.data:
            return True, "Uživatel úspěšně přidán do databáze."
        else:
            return False, "Nepodařilo se vložit uživatele."
    except Exception as e:
        return False, f"Chyba při vkládání: {str(e)}"


def reset_password(username, new_password='1234'):
    # Správné hashování pro verzi 0.4.2
    hashed_pw = hash_single_password(new_password)
    
    try:
        response = supabase.table('app_users')\
                   .update({"password_hash": hashed_pw})\
                   .eq("username", username)\
                   .execute()
        if response.data:
            return True, f"Heslo resetováno na '{new_password}' (doporučte změnu po přihlášení)."
        else:
            return False, "Uživatel nenalezen."
    except Exception as e:
        return False, f"Chyba při resetu hesla: {str(e)}"


def change_password(username, new_password):
    # Správné hashování pro verzi 0.4.2
    hashed_pw = hash_single_password(new_password)
    
    try:
        response = supabase.table('app_users')\
                   .update({"password_hash": hashed_pw})\
                   .eq("username", username)\
                   .execute()
        if response.data:
            return True, "Heslo úspěšně změněno."
        else:
            return False, "Uživatel nenalezen."
    except Exception as e:
        return False, f"Chyba při změně hesla: {str(e)}"
    
# utils/common.py
# ... ostatní importy a funkce ...

# utils/common.py (jen tato funkce – zbytek souboru nech tak, jak je)
def render_sidebar(current_page):
    """
    Vykreslí sidebar s uvítáním, logoutem a klikatelnou navigací.
    Funguje s auth_simple.py (cookies + Supabase).
    """
    # Načtení role z DB, pokud chybí nebo je viewer
    role = st.session_state.get('role')
    username = st.session_state.get('username')
    
    if username and (role is None or role == 'viewer'):
        try:
            response = supabase.table('app_users')\
                       .select('role')\
                       .eq('username', username)\
                       .execute()
            if response.data:
                role = response.data[0]['role']
                st.session_state['role'] = role
            else:
                role = 'viewer'
        except Exception as e:
            print(f"Chyba při načítání role: {e}")
            role = 'viewer'

    # Uvítání
    user_name = st.session_state.get('name', 'Uživatel')
    st.sidebar.success(f"Vítej, **{user_name}** ({role})")

    # Logout tlačítko (použijeme funkci z auth_simple.py)
    from utils.auth_simple import logout  # ← import zde (nebo nahoře v souboru)
    if st.sidebar.button("Odhlásit se"):
        logout()

    # Seznam položek navigace
    options = [
        "Přidat projekt / úkol",
        "Prohlížet / Upravovat úkoly",
        "HMG měsíční",
        "HMG roční",
        "Správa pracovišť",
        "Změnit heslo"
    ]
    if role == 'admin':
        options.append("User Management")

    # Mapování textu → název souboru (uprav si podle skutečných názvů tvých .py souborů!)
    page_map = {
        "Přidat projekt / úkol": "pages/2_add_project.py",
        "Prohlížet / Upravovat úkoly": "pages/3_task_man.py",
        "HMG měsíční": "pages/4_HMG_month.py",
        "HMG roční": "pages/5_HMG_year.py",
        "Správa pracovišť": "pages/6_WP_man.py",
        "Změnit heslo": "pages/7_pass_man.py",
        "User Management": "pages/8_user_man.py"
    }

    # Najdi index aktuální stránky
    try:
        current_index = options.index(current_page)
    except ValueError:
        current_index = 0
        st.sidebar.warning(f"Stránka '{current_page}' není v navigaci.")

    # Klikatelné radio menu
    selected = st.sidebar.radio(
        "Navigace",
        options,
        index=current_index,
        key="nav_radio"
        # Žádný disabled – uživatel může kliknout a přepnout
    )

    # Přesměrování při změně
    if selected != current_page:
        target_page = page_map.get(selected)
        if target_page:
            st.switch_page(target_page)
        else:
            st.sidebar.warning(f"Stránka '{selected}' není namapovaná.")

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("Plánovač Horkých komor v1.1")
    st.sidebar.caption("petr.svrcula@cvrez.cz")

