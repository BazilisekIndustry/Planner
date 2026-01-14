import streamlit as st
from streamlit_authenticator import Authenticate
import yaml
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
from supabase import create_client
import pandas as pd
from st_aggrid import AgGrid, GridUpdateMode, DataReturnMode
import plotly.express as px
from streamlit_authenticator.utilities.hasher import Hasher

# ============================
# KONFIGURACE
# ============================

SUPABASE_URL = st.secrets["supabase_url"]
SUPABASE_KEY = st.secrets["supabase_key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

COOKIE_NAME = 'planner_auth_cookie'
COOKIE_KEY = st.secrets.get("cookie_key", "planner_streamlit_secret_key")  # fallback
COOKIE_EXPIRY_DAYS = 30

# Načítání uživatelů z databáze (bez cache, bez widgetů uvnitř funkce)
@st.cache_data(ttl=600)  # 10 minut cache – dostatečné pro malý počet uživatelů
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

credentials = load_users_from_db()

if not credentials.get("usernames", {}):
    st.warning("V databázi nejsou žádní uživatelé nebo došlo k chybě při načítání.")


# Cookie config
COOKIE_NAME = 'planner_auth_cookie'
COOKIE_KEY = st.secrets.get("cookie_key", "planner_streamlit_secret_key")
COOKIE_EXPIRY_DAYS = 30


@st.cache_resource
def create_authenticator():
    creds = load_users_from_db()  # znovu načteme – cache zaručí rychlost
    return Authenticate(
        credentials=creds,
        cookie_name=COOKIE_NAME,
        key=COOKIE_KEY,
        cookie_expiry_days=COOKIE_EXPIRY_DAYS,
        location='main'
    )


# Pouze jednou za session vytvoříme instanci
if 'authenticator' not in st.session_state:
    st.session_state.authenticator = create_authenticator()

authenticator = st.session_state.authenticator


# ──────────────────────────────────────────────────────────────
# LOGIN – spouštíme jen pokud ještě není stav přihlášení
# ──────────────────────────────────────────────────────────────
if 'authentication_status' not in st.session_state:
    st.session_state.authentication_status = None

# Login formulář – jen pokud nejsme přihlášeni
if st.session_state.authentication_status is None:
    authenticator.login(location='main')


# Registrace fontu pro PDF




try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    PDF_FONT = 'DejaVu'
except Exception:
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
        'changed_by': st.session_state['username']
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
    """
    Simulovaná kontrola kolizí pro ještě nepřidaný úkol (bez použití task_id).
    Vrátí seznam project_id, se kterými by nový úkol kolidoval.
    """
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
# USER MANAGEMENT FUNKCE
# ============================
def get_user_role(username):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    usernames_lower = {k.lower(): v for k, v in config['credentials']['usernames'].items()}
    user_data = usernames_lower.get(username.lower(), {})
    return user_data.get('role', 'viewer')


def get_user_count():
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return len(config['credentials']['usernames'])


def add_user(username, name, password, role, email=""):
    """
    Přidá nového uživatele do Supabase tabulky app_users.
    Vrátí (success: bool, message: str)
    """
    # Kontrola maximálního počtu uživatelů (volitelné omezení, můžeš odstranit)
    try:
        count_response = supabase.table('app_users').select("count", count="exact").execute()
        user_count = count_response.count
        if user_count >= 6 and role != 'admin':
            return False, "Maximální počet uživatelů (5 + admin) dosažen."
    except Exception as e:
        return False, f"Chyba při kontrole počtu uživatelů: {e}"

    # Kontrola, zda uživatel již existuje
    check = supabase.table('app_users').select("username").eq("username", username).execute()
    if check.data:
        return False, "Uživatel s tímto uživatelským jménem již existuje."

    # Hash hesla (výchozí heslo bude '1234', pokud není zadáno jiné)
    hashed_pw = Hasher.hash(password)

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
            return False, "Nepodařilo se vložit uživatele (neznámá chyba)."
    except Exception as e:
        return False, f"Chyba při vkládání do databáze: {str(e)}"

def reset_password(username, new_password='1234'):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    if username not in config['credentials']['usernames']:
        return False, "Uživatel nenalezen."
    
    # Hash nového hesla (použijeme static metodu)
    hashed_pw = Hasher.hash(new_password)
    
    config['credentials']['usernames'][username]['password'] = hashed_pw
    
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    return True, f"Heslo resetováno na '{new_password}' (po přihlášení doporučte změnu!)"


def change_password(username, new_password):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    if username not in config['credentials']['usernames']:
        return False, "Uživatel nenalezen."
    
    # Hash nového hesla (použijeme static metodu)
    hashed_pw = Hasher.hash(new_password)
    
    config['credentials']['usernames'][username]['password'] = hashed_pw
    
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    return True, "Heslo úspěšně změněno."

def create_users_file():
    if not os.path.exists(USERS_FILE):
        users = {
            'credentials': {
                'usernames': {
                    'admin': {
                        'name': 'Administrátor',
                        'password': 'admin123',
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

# Načteme uživatele z databáze místo YAML
credentials = load_users_from_db()

# Cookie nastavení (může zůstat stejné)
cookie_config = {
    'name': 'planner_auth_cookie',
    'key': 'planner_streamlit_secret_key',  # lepší z secrets.toml!
    'expiry_days': 30,
}

authenticator = Authenticate(
    credentials,
    cookie_config['name'],
    cookie_config['key'],
    cookie_config['expiry_days']
)


# ──────────────────────────────────────────────────────────────
# HLAVNÍ APLIKACE – po autentizaci
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Plánovač Horkých komor CVŘ",
    page_icon=":radioactive:",
    layout="wide"
)

st.title("Plánovač Horkých komor CVŘ")

# Inicializace stavu přihlášení (pokud ještě není)
if 'authentication_status' not in st.session_state:
    st.session_state.authentication_status = None

# Zobrazení uvítací zprávy, pokud nejsme přihlášeni
if st.session_state.authentication_status is None:
    st.markdown(
        "Vítejte v Plánovači Horkých komor CVŘ. Přihlaste se prosím.\n\n"
        "Pro založení nového uživatele kontaktujte petr.svrcula@cvrez.cz."
    )

# Login formulář – spouštíme JEN pokud ještě není stav přihlášení rozhodnut
if st.session_state.authentication_status is None:
    authenticator.login(location='main')

# ──────────────────────────────────────────────────────────────
# PŘIHLÁŠENÝ UŽIVATEL
# ──────────────────────────────────────────────────────────────
if st.session_state.get('authentication_status'):
    username = st.session_state['username']
    name = st.session_state['name']
    
    # Role získáme přímo z credentials (bezpečnější, bez YAML)
    role = authenticator.credentials["usernames"]\
                      .get(username, {})\
                      .get('role', 'viewer')
    
    st.sidebar.success(f"Vítej, {name} ({role})!")
    authenticator.logout('Odhlásit se', location='sidebar')
    
    init_db()
    read_only = (role == 'viewer')

# ──────────────────────────────────────────────────────────────
# NEPŘIHLÁŠENÝ / CHYBNÉ PŘIHLÁŠENÍ
# ──────────────────────────────────────────────────────────────
elif st.session_state.authentication_status is False:
    st.error("Nesprávné přihlašovací údaje")

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

    option = st.sidebar.radio("Navigace", options)

    if option == "Přidat projekt / úkol":
        st.header("Přidat projekt a úkol")

        if role == 'viewer':
            st.error("Přístup jen pro administrátory a normální uživatele.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Přidat projekt")
                proj_id = st.text_input("Číslo projektu (povinné)", key="new_proj_id")
                proj_name = st.text_input("Název projektu (volitelné)", key="new_proj_name")

                if st.button("Přidat projekt"):
                    if proj_id.strip():
                        try:
                            if add_project(proj_id.strip(), proj_name.strip()):
                                st.session_state['project_added_success'] = True
                                st.session_state['project_added_id'] = proj_id.strip()
                                st.rerun()
                            else:
                                st.error("Projekt již existuje nebo chyba při vkládání.")
                        except Exception as e:
                            st.error(f"Chyba při přidávání projektu: {e}")
                    else:
                        st.error("Zadejte číslo projektu.")

            if st.session_state.get('project_added_success', False):
                proj_id = st.session_state['project_added_id']
                st.success(f"Projekt {proj_id} úspěšně přidán! 🎉")
                st.balloons()
                del st.session_state['project_added_success']
                if 'project_added_id' in st.session_state:
                    del st.session_state['project_added_id']

            with col2:
                st.subheader("Přidat úkol")
                with st.form(key="add_task_form"):
                    colA, colB = st.columns(2)
                    with colA:
                        project_choices = get_project_choices()
                        if not project_choices:
                            st.warning("Nejprve přidejte projekt.")
                            project_id = None
                        else:
                            projects = get_projects()
                            display_options = [(f"{pid} – {name or 'bez názvu'}", pid) for pid, name in projects]
                            selected_display, project_id = st.selectbox(
                                "Projekt",
                                options=display_options,
                                format_func=lambda x: x[0],
                                index=0,
                                key="add_task_proj"
                            )

                        parent_id = None
                        if project_id:
                            possible_parents = get_tasks(project_id)
                            parent_options = ["Žádný (root)"] + [
                                f"P{project_id} - Pracoviště: {get_workplace_name(t['workplace_id'])} - "
                                f"Start: {yyyymmdd_to_ddmmyyyy(t['start_date']) or 'bez data'} - "
                                f"Poznámka: {t['notes'][:30] or 'bez poznámky'}..."
                                for t in possible_parents
                            ]
                            parent_choice = st.selectbox("Nadřazený úkol (větev)", parent_options)
                            if parent_choice != "Žádný (root)":
                                idx = parent_options.index(parent_choice) - 1
                                if 0 <= idx < len(possible_parents):
                                    parent_id = possible_parents[idx]['id']
                        else:
                            st.info("Vyberte projekt pro zobrazení možných nadřazených úkolů.")

                        wp_names = [name for _, name in get_workplaces()]
                        wp_name = st.selectbox("Pracoviště", wp_names)
                        wp_id = next((wid for wid, name in get_workplaces() if name == wp_name), None)

                        hours = st.number_input("Počet hodin", min_value=1, step=1, format="%d")
                        bodies_count = st.number_input("Počet těles", min_value=1, step=1)

                        active_choice = st.radio(
                            "Stav těles",
                            ["Aktivní", "Neaktivní"],
                            index=0,
                            horizontal=True
                        )
                        is_active = (active_choice == "Aktivní")

                    with colB:
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
                        elif parent_id and has_cycle(parent_id):
                            st.error("Vytvoření cyklu zakázáno.")
                        else:
                            try:
                                start_yyyymmdd = ddmmyyyy_to_yyyymmdd(start_ddmmyyyy) if start_ddmmyyyy else None
                                temp_end = calculate_end_date(start_yyyymmdd, float(hours), capacity_mode) if start_yyyymmdd else None

                                # 1. Kontrola kolizí v rámci stejného projektu → tvrdé zastavení
                                conflict_in_project = False
                                if start_yyyymmdd and temp_end:
                                    existing_in_project = (
                                        supabase.table('tasks')
                                        .select('id, start_date, end_date')
                                        .eq('project_id', project_id)
                                        .eq('workplace_id', wp_id)
                                        .not_.is_('start_date', 'null')
                                        .not_.is_('end_date', 'null')
                                        .execute()
                                        .data
                                    )

                                    new_start_date = datetime.strptime(start_yyyymmdd, '%Y-%m-%d').date()
                                    new_end_date = datetime.strptime(temp_end, '%Y-%m-%d').date()

                                    for ex in existing_in_project:
                                        ex_start = datetime.strptime(ex['start_date'], '%Y-%m-%d').date()
                                        ex_end = datetime.strptime(ex['end_date'], '%Y-%m-%d').date()
                                        if not (new_end_date < ex_start or new_start_date > ex_end):
                                            conflict_in_project = True
                                            break

                                if conflict_in_project:
                                    st.error(
                                        "Kolize v rámci stejného projektu na tomto pracovišti. "
                                        "Upravte existující úkol(y) a zkuste znovu."
                                    )
                                else:
                                    # 2. Kontrola cross-projektových kolizí
                                    colliding_projects = []
                                    if start_yyyymmdd and temp_end:
                                        colliding_projects = get_colliding_projects_simulated(
                                            workplace_id=wp_id,
                                            start_date=start_yyyymmdd,
                                            end_date=temp_end
                                        )

                                    if colliding_projects:
                                        # Uložení pro dialog
                                        st.session_state['pending_task_data'] = {
                                            'project_id': project_id,
                                            'workplace_id': wp_id,
                                            'hours': float(hours),
                                            'mode': capacity_mode,
                                            'start_ddmmyyyy': start_ddmmyyyy,
                                            'notes': notes,
                                            'bodies_count': int(bodies_count),
                                            'is_active': is_active,
                                            'parent_id': parent_id
                                        }
                                        st.session_state['colliding_projects'] = colliding_projects
                                        st.session_state['show_collision_confirm'] = True
                                        st.rerun()
                                    else:
                                        # Přímé přidání bez kolize
                                        task_id = add_task(
                                            project_id=project_id,
                                            workplace_id=wp_id,
                                            hours=float(hours),
                                            mode=capacity_mode,
                                            start_ddmmyyyy=start_ddmmyyyy,
                                            notes=notes,
                                            bodies_count=int(bodies_count),
                                            is_active=is_active,
                                            parent_id=parent_id
                                        )
                                        if task_id:
                                            st.session_state['task_added_success'] = True
                                            st.session_state['task_added_details'] = {
                                                'project': project_id,
                                                'workplace': wp_name,
                                                'hours': hours,
                                                'mode': capacity_mode,
                                                'start': start_ddmmyyyy or 'automaticky'
                                            }
                                            if parent_id:
                                                children_count = len(get_children(parent_id))
                                                if children_count > 1:
                                                    st.session_state['fork_warning'] = children_count
                                            st.rerun()

                            except Exception as e:
                                st.error(f"Chyba při kontrole/přidávání úkolu: {e}")

            # Potvrzovací dialog pro cross-projektovou kolizi
            if st.session_state.get('show_collision_confirm', False):
                pending = st.session_state['pending_task_data']
                colliding_str = ', '.join(map(str, st.session_state.get('colliding_projects', [])))

                st.warning(
                    f"**Pozor – kolize mezi projekty!**\n\n"
                    f"Tento nový úkol bude kolidovat s projekty: **{colliding_str}**\n"
                    f"na pracovišti {get_workplace_name(pending['workplace_id'])}.\n\n"
                    "Opravdu chcete úkol přidat přesto?"
                )

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Ano, přidat přesto", type="primary"):
                        task_id = add_task(
                            project_id=pending['project_id'],
                            workplace_id=pending['workplace_id'],
                            hours=pending['hours'],
                            mode=pending['mode'],
                            start_ddmmyyyy=pending['start_ddmmyyyy'],
                            notes=pending['notes'],
                            bodies_count=pending['bodies_count'],
                            is_active=pending['is_active'],
                            parent_id=pending['parent_id']
                        )
                        if task_id:
                            st.success("Úkol přidán přesto (s kolizí).")
                            # ← KLÍČOVÁ OPRAVA – nastavíme i detaily pro notifikaci
                            st.session_state['task_added_success'] = True
                            st.session_state['task_added_details'] = {
                                'project': pending['project_id'],
                                'workplace': get_workplace_name(pending['workplace_id']),
                                'hours': pending['hours'],
                                'mode': pending['mode'],
                                'start': pending['start_ddmmyyyy'] or 'automaticky'
                            }
                            # Volitelně fork warning
                            if pending['parent_id']:
                                children_count = len(get_children(pending['parent_id']))
                                if children_count > 1:
                                    st.session_state['fork_warning'] = children_count

                        # Vyčistíme stav
                        del st.session_state['pending_task_data']
                        del st.session_state['colliding_projects']
                        del st.session_state['show_collision_confirm']
                        st.rerun()

                with col2:
                    if st.button("Ne, zrušit"):
                        st.info("Přidání úkolu zrušeno.")
                        del st.session_state['pending_task_data']
                        del st.session_state['colliding_projects']
                        del st.session_state['show_collision_confirm']
                        st.rerun()

            # Notifikace pro úspěšné přidání
            if st.session_state.get('task_added_success', False):
                details = st.session_state['task_added_details']
                st.success(
                    f"Úkol úspěšně přidán! ✅\n\n"
                    f"Projekt: {details['project']}\n"
                    f"Pracoviště: {details['workplace']}\n"
                    f"Hodiny: {details['hours']}\n"
                    f"Režim: {details['mode']}\n"
                    f"Začátek: {details['start']}"
                )
                st.toast("Nový úkol je připraven!", icon="🎉")
                del st.session_state['task_added_success']
                if 'task_added_details' in st.session_state:
                    del st.session_state['task_added_details']

            if 'fork_warning' in st.session_state:
                st.warning(f"Vytvořili jste fork/split – nadřazený úkol má nyní {st.session_state['fork_warning']} potomků.")
                del st.session_state['fork_warning']

    # ──────────────────────────────────────────────────────────────
    # Prohlížet / Upravovat úkoly
    # ──────────────────────────────────────────────────────────────
    elif option == "Prohlížet / Upravovat úkoly":
        st.header("Prohlížet / Upravovat úkoly")
        if read_only:
            st.warning("V režimu prohlížení nelze provádět úpravy.")

        projects = get_projects()
        if not projects:
            st.info("Nejprve přidejte alespoň jeden projekt.")
            st.stop()

        display_options = [(f"{pid} – {name or 'bez názvu'}", pid) for pid, name in projects]
        selected_display, selected_project = st.selectbox(
            "Vyberte projekt",
            options=display_options,
            format_func=lambda x: x[0],
            index=0,
            key="edit_proj"
        )

        if st.button("Rekalkulovat projekt"):
            recalculate_project(selected_project)
            st.success("Projekt přepočítán.")

            tasks = get_tasks(selected_project)
            collisions = mark_all_collisions()
            colliding_tasks = [tid for tid, has_coll in collisions.items() if has_coll and get_task(tid)['project_id'] == selected_project]
            if colliding_tasks:
                colliding_info = []
                for tid in colliding_tasks:
                    coll_projects = get_colliding_projects(tid)
                    colliding_info.append(f"Úkol {tid}: kolize s {', '.join(coll_projects)}")
                st.warning("Po rekalkulaci detekovány kolize:\n" + "\n".join(colliding_info))

            st.rerun()

        tasks = get_tasks(selected_project)
        if not tasks:
            st.info(f"V projektu {selected_display} zatím nejsou žádné úkoly.")
        else:
            collisions = mark_all_collisions()
            data = []
            for t in tasks:
                wp_name = get_workplace_name(t['workplace_id'])
                start_disp = yyyymmdd_to_ddmmyyyy(t['start_date'])
                end_disp = yyyymmdd_to_ddmmyyyy(t['end_date'])
                coll_text = ""
                if collisions.get(t['id'], False):
                    colliding = get_colliding_projects(t['id'])
                    coll_text = f"⚠️ Kolize: {', '.join(colliding)}"

                status_display = t['status']
                status_icon = ""
                if t['status'] == 'done':
                    status_display = "Hotovo"
                    status_icon = "✅ "
                elif t['status'] == 'canceled':
                    status_display = "Zrušeno"
                    status_icon = "❌ "
                else:
                    status_display = "Pending"

                parent_id = get_parent(t['id'])
                if parent_id:
                    parent_task = get_task(parent_id)
                    if parent_task:
                        parent_wp = get_workplace_name(parent_task['workplace_id'])
                        parent_start = yyyymmdd_to_ddmmyyyy(parent_task['start_date']) or 'bez data'
                        parent_notes = parent_task['notes'][:30] or 'bez poznámky'
                        parent_desc = f"P{selected_project} – {parent_wp} – {parent_start} – {parent_notes}..."
                    else:
                        parent_desc = f"ID {parent_id[:8]}... (nenalezen)"
                else:
                    parent_desc = "— (root)"

                task_desc = (
                    f"P{selected_project} – {wp_name} – {start_disp} – {t['hours']}h – "
                    f"{status_icon}{status_display} – {t['notes'][:40] or 'bez poznámky'}..."
                )

                data.append({
                    "ID": t['id'],
                    "Parent úkol": parent_desc,
                    "Popis": task_desc,
                    "Pracoviště": wp_name,
                    "Hodiny": t['hours'],
                    "Režim": t['capacity_mode'],
                    "Začátek": start_disp,
                    "Konec": end_disp,
                    "Stav": status_display,
                    "Poznámka": t.get('notes', "") or "",
                    "Kolize": coll_text,
                    "Počet těles": t['bodies_count'],
                    "Aktivní": "Ano" if t['is_active'] else "Ne"
                })

            df = pd.DataFrame(data)

            custom_css = {
                ".conflict-row": {
                    "background-color": "#ffcccc !important",
                }
            }

            grid_response = AgGrid(
                df,
                height=500,
                editable=not read_only,
                gridOptions={
                    "columnDefs": [
                        {"field": "Parent úkol", "width": 300},
                        {"field": "Popis", "width": 400},
                        {"field": "Pracoviště", "width": 220},
                        {"field": "Hodiny", "width": 100},
                        {"field": "Režim", "width": 100},
                        {"field": "Začátek", "editable": not read_only, "width": 140},
                        {"field": "Konec", "width": 140},
                        {"field": "Stav", "width": 160},
                        {"field": "Poznámka", "width": 250},
                        {"field": "Kolize", "cellStyle": {"color": "red", "fontWeight": "bold"}, "width": 220},
                        {"field": "Počet těles", "width": 120},
                        {"field": "Aktivní", "width": 100}
                    ],
                    "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
                    "rowClassRules": {
                        "conflict-row": "params.data && params.data['Kolize'] && params.data['Kolize'].trim() !== ''"
                    }
                },
                update_mode=GridUpdateMode.VALUE_CHANGED,
                data_return_mode=DataReturnMode.AS_INPUT,
                fit_columns_on_grid_load=True,
                theme="streamlit",
                custom_css=custom_css,
                allow_unsafe_jscode=False
            )

            updated_df = grid_response['data']
            changes_made = False

            for _, row in updated_df.iterrows():
                task_id = row['ID']
                new_start_raw = row['Začátek']
                new_start_str = str(new_start_raw).strip() if pd.notna(new_start_raw) else ""

                task = get_task(task_id)
                original_start = yyyymmdd_to_ddmmyyyy(task['start_date']) if task['start_date'] else ""

                if new_start_str == original_start:
                    continue

                if not new_start_str:
                    try:
                        update_task(task_id, 'start_date', None)
                        recalculate_from_task(task_id)
                        changes_made = True
                    except Exception as e:
                        st.error(f"Chyba při vymazání data u úkolu {task_id}: {e}")
                    continue

                if not validate_ddmmyyyy(new_start_str):
                    st.error(f"Neplatné datum u úkolu {task_id}: '{new_start_str}'. Použijte např. 1.1.2026 nebo 15.03.2025")
                    continue

                try:
                    update_task(task_id, 'start_date', new_start_str)
                    recalculate_from_task(task_id)
                    changes_made = True
                except Exception as e:
                    st.error(f"Chyba při úpravě data u úkolu {task_id}: {e}")

            if changes_made:
                st.success("Změny uloženy a termíny přepočítány.")
                st.rerun()

            if tasks:
                st.markdown("### Změna stavu úkolu")
                task_options = []
                for t in tasks:
                    wp_name = get_workplace_name(t['workplace_id'])
                    start = yyyymmdd_to_ddmmyyyy(t['start_date']) or 'bez data'
                    status_icon = "✅ " if t['status'] == 'done' else "❌ " if t['status'] == 'canceled' else ""
                    desc = f"P{selected_project} – {wp_name} – {start} – {t['hours']}h – {status_icon}{t['status']} – {t['notes'][:40] or 'bez poznámky'}..."
                    task_options.append(desc)

                selected_task_display = st.selectbox("Vyberte úkol", task_options, key="status_change_order")
                selected_task_idx = task_options.index(selected_task_display)
                selected_task_id = tasks[selected_task_idx]['id']

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Označit jako Hotovo"):
                        update_task(selected_task_id, 'status', 'done')
                        recalculate_from_task(selected_task_id)
                        st.success("Úkol označen jako hotový.")
                        st.rerun()

                with col2:
                    reason = st.text_input("Důvod zrušení", key="cancel_reason_input")
                    if st.button("Označit jako Zrušeno"):
                        if reason.strip():
                            update_task(selected_task_id, 'reason', reason.strip())
                            update_task(selected_task_id, 'status', 'canceled')
                            recalculate_from_task(selected_task_id)
                            st.success("Úkol zrušen.")
                            st.rerun()
                        else:
                            st.error("Zadejte důvod zrušení.")

                if role == 'admin':
                    st.markdown("### Servisní mazání úkolu (pouze admin)")
                    delete_display = st.selectbox("Vyberte úkol k smazání", task_options, key="admin_delete")
                    delete_idx = task_options.index(delete_display)
                    delete_task_id = tasks[delete_idx]['id']
                    if st.checkbox("Potvrďte smazání tohoto úkolu (neodvolatelné!)"):
                        if st.button("SMAZAT ÚKOL"):
                            if delete_task(delete_task_id):
                                st.success("Úkol smazán.")
                                st.rerun()
                            else:
                                st.error("Chyba při mazání.")

    # ──────────────────────────────────────────────────────────────
    # Zbývající sekce (HMG měsíční, HMG roční, Správa pracovišť, Změnit heslo, User Management)
    # ──────────────────────────────────────────────────────────────
    # ... (zde vlož zbytek svého kódu pro tyto sekce – jsou v pořádku, jen je potřeba správně odsadit)
    # Pokud chceš, pošli mi ty části samostatně a já je opravím a přidám do celku.

    # Příklad pro HMG měsíční (pokračování):
    elif option == "Správa pracovišť":
        if role != 'admin':
            st.error("Přístup jen pro administrátory.")
        else:
            st.header("Správa pracovišť")
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

    elif option == "User Management" and role == 'admin':
        st.header("User Management – Pouze pro admin")
        
        st.subheader("Přidat nového uživatele")
        
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input("Uživatelské jméno (povinné)", key="new_u_username")
            new_name = st.text_input("Celé jméno (povinné)", key="new_u_name")
            new_email = st.text_input("Email (volitelné)", key="new_u_email")
        
        with col2:
            new_role = st.selectbox("Role", ["normal", "viewer"], key="new_u_role")
            default_pw = "1234"
            st.info(f"Výchozí heslo: **{default_pw}** (uživatel by ho měl ihned změnit)")

        if st.button("Přidat uživatele"):
            if not new_username.strip() or not new_name.strip():
                st.error("Uživatelské jméno a celé jméno jsou povinné.")
            else:
                success, message = add_user(
                    username=new_username.strip(),
                    name=new_name.strip(),
                    password=default_pw,
                    role=new_role,
                    email=new_email.strip()
                )
                if success:
                    st.success(message)
                    # Vyčistíme cache → nový uživatel se objeví
                    cached_load_users.clear()
                    st.rerun()
                else:
                    st.error(message)
        
        # Zobrazení aktuálních uživatelů (opravené width)
        st.subheader("Aktuální uživatelé")
        try:
            users_response = supabase.table('app_users')\
                            .select("username, name, role, email")\
                            .execute()
            
            if users_response.data:
                df_users = pd.DataFrame(users_response.data)
                df_users = df_users.rename(columns={
                    "username": "Uživatelské jméno",
                    "name": "Jméno",
                    "role": "Role",
                    "email": "Email"
                })
                # Nahrazení deprecated use_container_width
                st.dataframe(df_users, width='stretch')  # nebo 'content' podle potřeby
            else:
                st.info("V databázi zatím nejsou žádní uživatelé.")
        except Exception as e:
            st.error(f"Chyba při načítání seznamu: {e}")
        #st.table(users_data)
        st.markdown("### Smazání celého projektu (neodvolatelné!)")
        project_choices = get_project_choices()
        if project_choices:
            proj_to_delete = st.selectbox(
                "Vyberte projekt k úplnému smazání (včetně všech úkolů)",
                project_choices,
                key="admin_delete_project_select"
            )
            proj_name = "bez názvu"
            for pid, pname in get_projects():
                if pid == proj_to_delete:
                    proj_name = pname
                    break
            st.warning(f"**Pozor!** Bude smazán celý projekt **{proj_to_delete} – {proj_name}** včetně všech úkolů a záznamů v historii změn. Tuto akci nelze vrátit zpět!")
            if st.checkbox("Potvrzuji, že chci trvale smazat tento projekt i s úkoly", key="confirm_proj_delete"):
                if st.button("SMAZAT CELÝ PROJEKT", type="primary"):
                    if delete_project(proj_to_delete):
                        st.success(f"Projekt {proj_to_delete} byl úspěšně a kompletně smazán.")
                        st.rerun()

    elif option == "HMG měsíční":
        st.header("HMG měsíční – Přehled úkolů po dnech")
        selected_year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="hmg_year")
        selected_month = st.number_input("Měsíc", min_value=1, max_value=12, value=datetime.now().month, key="hmg_month")
        first_day = date(selected_year, selected_month, 1)
        if selected_month == 12:
            last_day = date(selected_year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(selected_year, selected_month + 1, 1) - timedelta(days=1)
        num_days = last_day.day
        response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
        all_tasks = response.data
        plot_data = []
        pdf_data = []
        workplaces_set = set()
        for t in all_tasks:
            tid = t['id']
            pid = t['project_id']
            wp_id = t['workplace_id']
            hours = t['hours']
            mode = t['capacity_mode']
            start_int = t['start_date']
            end_int = t['end_date']
            status = t['status']
            notes = t['notes']
            if status == 'canceled':
                continue
            wp_name = get_workplace_name(wp_id)
            workplaces_set.add(wp_name)
            start_date = datetime.strptime(start_int, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_int, '%Y-%m-%d').date()
            if end_date < first_day or start_date > last_day:
                continue
            task_text = f"P{pid}"
            if check_collisions(tid):
                task_text += " !"
            color = "#4285f4"
            if status == 'done':
                color = "#34a853"
            if check_collisions(tid):
                color = "#ea4335"
            display_start = max(start_date, first_day)
            display_end = min(end_date, last_day)
            plot_data.append({
                "Pracoviště": wp_name,
                "Úkol": task_text,
                "Start": display_start,
                "Finish": display_end + timedelta(days=1),
                "Color": color
            })
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
            if st.button("Exportovat HMG měsíční do PDF"):
                file_name = f"HMG_mesicni_{selected_year}_{selected_month:02d}.pdf"
                pdf = pdf_canvas.Canvas(file_name, pagesize=landscape(A4))
                width, height = landscape(A4)
                pdf.setFont(PDF_FONT, 16)
                pdf.drawCentredString(width / 2, height - 0.8 * inch, f"HMG HK – {calendar.month_name[selected_month]} {selected_year}")
                left_margin = 1.0 * inch
                wp_col_width = 2.0 * inch
                day_col_width = (width - left_margin - wp_col_width - 0.8 * inch) / num_days
                header_y = height - 1.5 * inch
                row_height = (height - 2.5 * inch) / len(workplaces_set) if workplaces_set else 40
                pdf.setFont(PDF_FONT, 10)
                for d in range(1, num_days + 1):
                    current_date = date(selected_year, selected_month, d)
                    x = left_margin + wp_col_width + (d - 1) * day_col_width
                    fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
                    pdf.setFillColorRGB(*fill_color)
                    pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))
                pdf.setStrokeColorRGB(0, 0, 0)
                pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)
                sorted_workplaces = sorted(workplaces_set)
                colors_rgb = {
                    "#4285f4": (0.26, 0.52, 0.96),
                    "#34a853": (0.20, 0.66, 0.32),
                    "#ea4335": (0.92, 0.26, 0.21)
                }
                for i, wp_name in enumerate(sorted_workplaces):
                    y_top = header_y - 20 - i * row_height
                    y_bottom = y_top - row_height
                    pdf.setFillColorRGB(0, 0, 0)
                    pdf.setFont(PDF_FONT, 9)
                    pdf.drawString(left_margin, y_top - row_height / 2, wp_name)
                    pdf.line(left_margin, y_bottom, width - 0.8 * inch, y_bottom)
                    for item in pdf_data:
                        if item["wp_name"] != wp_name:
                            continue
                        x1 = left_margin + wp_col_width + (item["start_day"] - 1) * day_col_width
                        x2 = left_margin + wp_col_width + item["end_day"] * day_col_width
                        rgb = colors_rgb.get(item["color"], (0.26, 0.52, 0.96))
                        pdf.setFillColorRGB(*rgb)
                        pdf.rect(x1, y_bottom + 5, x2 - x1, row_height - 10, fill=1, stroke=1)
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

    elif option == "HMG roční":
        st.header("HMG roční – Heatmap obsazenosti pracovišť")
        year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="year_rocni")
        MONTH_CAPACITY = 200.0
        workplaces = get_workplaces()
        months = ['Led', 'Úno', 'Bře', 'Dub', 'Kvě', 'Čer', 'Čvc', 'Srp', 'Zář', 'Říj', 'Lis', 'Pro']
        month_order = {m: i for i, m in enumerate(months)}
        occupancy = {wp_name: [0.0 for _ in range(12)] for _, wp_name in workplaces}
        response = supabase.table('tasks').select('id, workplace_id, hours, capacity_mode, start_date, end_date, status').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
        tasks = response.data
        for t in tasks:
            if t['status'] == 'canceled':
                continue
            wp_id = t['workplace_id']
            total_hours = t['hours']
            mode = t['capacity_mode']
            start_str = t['start_date']
            end_str = t['end_date']
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
            df['Měsíc_order'] = df['Měsíc'].map(month_order)
            df = df.sort_values(['Pracoviště', 'Měsíc_order'])
            pivot_df = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
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
            st.subheader("Detailní přehled (hodiny / %)")
            hours_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="Hodiny")
            hours_pivot = hours_pivot[months]
            percent_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
            percent_pivot = percent_pivot[months]
            combined = pd.concat([hours_pivot, percent_pivot], axis=1, keys=["Hodiny", "% využití"])
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

# Footer
if st.session_state.get('authentication_status'):
    st.sidebar.markdown("---")
    st.sidebar.markdown("Plánovač Horkých komor v1.1")
    st.sidebar.caption("petr.svrcula@cvrez.cz")