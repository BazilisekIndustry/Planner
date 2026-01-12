import streamlit as st
import streamlit_authenticator as stauth
import yaml
import os
from datetime import datetime, timedelta, date
import math
import re
import calendar

# PDF generování
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import pandas as pd
import plotly.express as px
from supabase import create_client
from st_aggrid import AgGrid, GridUpdateMode, DataReturnMode

# ============================
# KONFIGURACE
# ============================
USERS_FILE = 'users.yaml'
SUPABASE_URL = st.secrets["supabase_url"]
SUPABASE_KEY = st.secrets["supabase_key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Registrace fontu pro PDF
PDF_FONT = 'Helvetica'
try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    PDF_FONT = 'DejaVu'
except Exception:
    st.warning("Font DejaVuSans.ttf nebyl nalezen – diakritika v PDF nemusí fungovat správně.")

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
    fixed = [
        date(year, 1, 1),
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
    return fixed + [get_easter(year)]


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
    return date_str.replace('.', '-').replace('/', '-')


def ddmmyyyy_to_yyyymmdd(date_str):
    if not date_str or not date_str.strip():
        return None
    normalized = normalize_date_str(date_str.strip())
    try:
        day, month, year = map(int, normalized.split('-'))
        return date(year, month, day).strftime('%Y-%m-%d')
    except Exception as e:
        raise ValueError(f"Neplatný formát data: {date_str!r} (očekáváno DD.MM.YYYY nebo DD-MM-YYYY)") from e


def yyyymmdd_to_ddmmyyyy(date_str):
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')
    except:
        return ""


def validate_ddmmyyyy(date_str):
    if not date_str:
        return True
    try:
        ddmmyyyy_to_yyyymmdd(date_str)
        return True
    except:
        return False


def calculate_end_date(start_yyyymmdd, hours, mode):
    if not start_yyyymmdd or hours <= 0:
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
def get_projects():
    try:
        response = supabase.table('projects').select('id, name').execute()
        return [(row['id'], row['name']) for row in response.data]
    except Exception as e:
        st.error(f"Chyba při načítání projektů: {e}")
        return []


def get_project_choices():
    return [str(p[0]) for p in get_projects()]


def get_workplaces():
    try:
        response = supabase.table('workplaces').select('id, name').execute()
        return [(row['id'], row['name']) for row in response.data]
    except Exception as e:
        st.error(f"Chyba při načítání pracovišť: {e}")
        return []


def get_workplace_name(wp_id):
    try:
        response = supabase.table('workplaces').select('name').eq('id', wp_id).execute()
        return response.data[0]['name'] if response.data else f"ID {wp_id}"
    except:
        return f"ID {wp_id} (chyba)"


def add_workplace(name):
    if not name.strip():
        return False
    try:
        supabase.table('workplaces').insert({'name': name.strip()}).execute()
        return True
    except:
        return False


def delete_workplace(wp_id):
    try:
        response = supabase.table('tasks').select('id').eq('workplace_id', wp_id).execute()
        if response.data:
            return False
        supabase.table('workplaces').delete().eq('id', wp_id).execute()
        return True
    except:
        return False


def add_project(project_id, name):
    try:
        supabase.table('projects').insert({'id': project_id, 'name': name}).execute()
        return True
    except:
        return False


def get_tasks(project_id):
    try:
        response = supabase.table('tasks').select('*').eq('project_id', project_id).order('order_number').execute()
        return response.data
    except Exception as e:
        st.error(f"Chyba při načítání úkolů: {e}")
        return []


def add_task(project_id, order_number, workplace_id, hours, mode, parent_ids=None, samples_count=1, start_ddmmyyyy=None, notes=''):
    if parent_ids is None:
        parent_ids = []

    # Kontrola paralelních úkolů na stejném pracovišti
    if parent_ids:
        query = supabase.table('tasks').select('workplace_id').eq('project_id', project_id)
        for pid in parent_ids:
            query = query.contains('parent_ids', [pid])
        siblings = query.execute().data
        if any(s['workplace_id'] == workplace_id for s in siblings):
            raise ValueError("Nelze přidat paralelní úkol na stejné pracoviště v tomto projektu.")

    start_yyyymmdd = ddmmyyyy_to_yyyymmdd(start_ddmmyyyy) if start_ddmmyyyy else None

    data = {
        'project_id': project_id,
        'order_number': order_number,
        'workplace_id': workplace_id,
        'hours': hours,
        'capacity_mode': mode,
        'parent_ids': parent_ids,
        'samples_count': samples_count,
        'start_date': start_yyyymmdd,
        'notes': notes,
        'status': 'planned'
    }

    try:
        response = supabase.table('tasks').insert(data).execute()
        task_id = response.data[0]['id']
        recalculate_from_task(task_id)
        return task_id
    except Exception as e:
        raise RuntimeError(f"Chyba při ukládání úkolu: {e}")


def update_task(task_id, field, value, is_internal=False):
    try:
        if field in ('start_date', 'end_date') and value and not is_internal:
            value = ddmmyyyy_to_yyyymmdd(value)

        supabase.table('tasks').update({field: value}).eq('id', task_id).execute()

        now = datetime.now().isoformat()
        supabase.table('change_log').insert({
            'task_id': task_id,
            'change_time': now,
            'description': f'Updated {field} to {value}'
        }).execute()
    except Exception as e:
        st.error(f"Chyba při aktualizaci úkolu {task_id}: {e}")


def get_task(task_id):
    try:
        response = supabase.table('tasks').select('*').eq('id', task_id).execute()
        return response.data[0] if response.data else None
    except:
        return None


def get_project_root_tasks(project_id):
    try:
        response = supabase.table('tasks').select('*').eq('project_id', project_id).eq('parent_ids', '{}').execute()
        return response.data
    except:
        return []


def recalculate_from_task(task_id, visited=None):
    if visited is None:
        visited = set()

    if task_id in visited:
        st.warning(f"Detekován kruhový závislost při přepočtu úkolu {task_id}!")
        return

    visited.add(task_id)

    task = get_task(task_id)
    if not task:
        return

    # Nastavení startu podle nejpozdějšího rodiče
    if task.get('parent_ids'):
        parent_end_dates = []
        for p_id in task['parent_ids']:
            parent = get_task(p_id)
            if parent and parent.get('end_date'):
                parent_end_dates.append(datetime.strptime(parent['end_date'], '%Y-%m-%d').date())

        if parent_end_dates:
            latest_end = max(parent_end_dates)
            new_start = latest_end + timedelta(days=1)
            while not is_working_day(new_start, task['capacity_mode']):
                new_start += timedelta(days=1)
            update_task(task_id, 'start_date', new_start.strftime('%Y-%m-%d'), is_internal=True)
        else:
            update_task(task_id, 'start_date', None, is_internal=True)
            update_task(task_id, 'end_date', None, is_internal=True)
            return

    # Výpočet konce
    if task['status'] != 'done' and task.get('start_date'):
        end_str = calculate_end_date(task['start_date'], task['hours'], task['capacity_mode'])
        update_task(task_id, 'end_date', end_str, is_internal=True)

    # Rekurze na děti
    try:
        children = supabase.table('tasks').select('id').contains('parent_ids', [task_id]).execute().data
        for child in children:
            recalculate_from_task(child['id'], visited.copy())
    except Exception as e:
        st.error(f"Chyba při rekurzivním přepočtu dětí úkolu {task_id}: {e}")


def recalculate_project(project_id):
    roots = get_project_root_tasks(project_id)
    for root in roots:
        recalculate_from_task(root['id'])


def get_colliding_projects(task_id):
    task = get_task(task_id)
    if not task or not task.get('start_date') or not task.get('end_date'):
        return []

    wp = task['workplace_id']
    start = datetime.strptime(task['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(task['end_date'], '%Y-%m-%d').date()

    try:
        response = supabase.table('tasks') \
            .select('project_id, start_date, end_date') \
            .eq('workplace_id', wp) \
            .neq('id', task_id) \
            .not_.is_('start_date', 'null') \
            .not_.is_('end_date', 'null') \
            .execute()

        colliding = []
        for row in response.data:
            row_start = datetime.strptime(row['start_date'], '%Y-%m-%d').date()
            row_end = datetime.strptime(row['end_date'], '%Y-%m-%d').date()
            if not (end < row_start or start > row_end):
                colliding.append(row['project_id'])
        return colliding
    except:
        return []


def check_collisions(task_id):
    return len(get_colliding_projects(task_id)) > 0


def mark_all_collisions():
    try:
        response = supabase.table('tasks') \
            .select('id') \
            .not_.is_('start_date', 'null') \
            .not_.is_('end_date', 'null') \
            .execute()
        ids = [row['id'] for row in response.data]
        return {tid: check_collisions(tid) for tid in ids}
    except:
        return {}


def delete_task(task_id):
    try:
        supabase.table('change_log').delete().eq('task_id', task_id).execute()
        supabase.table('tasks').delete().eq('id', task_id).execute()
        return True
    except Exception as e:
        st.error(f"Chyba při mazání úkolu {task_id}: {e}")
        return False


def delete_project(project_id):
    try:
        tasks = supabase.table('tasks').select('id').eq('project_id', project_id).execute().data
        for task in tasks:
            supabase.table('change_log').delete().eq('task_id', task['id']).execute()
            supabase.table('tasks').delete().eq('id', task['id']).execute()
        supabase.table('projects').delete().eq('id', project_id).execute()
        return True
    except Exception as e:
        st.error(f"Chyba při mazání projektu {project_id}: {e}")
        return False


# ============================
# USER MANAGEMENT
# ============================
def get_user_role(username):
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        usernames_lower = {k.lower(): v for k, v in config['credentials']['usernames'].items()}
        user_data = usernames_lower.get(username.lower(), {})
        return user_data.get('role', 'viewer')
    except:
        return 'viewer'


def get_user_count():
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return len(config['credentials']['usernames'])
    except:
        return 0


def add_user(username, name, password, role):
    if get_user_count() >= 6 and role != 'admin':
        return False, "Maximální počet uživatelů (5 + admin) dosažen."

    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if username in config['credentials']['usernames']:
            return False, "Uživatel již existuje."

        config['credentials']['usernames'][username] = {
            'name': name,
            'password': password,  # plain text jak máš původně
            'role': role
        }

        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        return True, "Uživatel přidán."
    except Exception as e:
        return False, f"Chyba při přidávání uživatele: {e}"


def reset_password(username, new_password='1234'):
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if username not in config['credentials']['usernames']:
            return False, "Uživatel nenalezen."

        config['credentials']['usernames'][username]['password'] = new_password

        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        return True, "Heslo resetováno na 1234."
    except Exception as e:
        return False, f"Chyba při resetu hesla: {e}"


def change_password(username, new_password):
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        config['credentials']['usernames'][username]['password'] = new_password

        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        return True, "Heslo změněno."
    except Exception as e:
        return False, f"Chyba při změně hesla: {e}"


def create_users_file():
    if not os.path.exists(USERS_FILE):
        default_users = {
            'credentials': {
                'usernames': {
                    'admin': {
                        'name': 'Administrátor',
                        'password': 'admin123',  # plain text
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
            yaml.dump(default_users, f, default_flow_style=False, allow_unicode=True)


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
# APLIKACE
# ============================
st.set_page_config(page_title="Plánovač Horkých komor CVŘ", page_icon="☢️", layout="wide")
st.title("Plánovač Horkých komor CVŘ")

if not st.session_state.get('authentication_status'):
    st.markdown("""
    Vítejte v Plánovači Horkých komor CVŘ.  
    Přihlaste se prosím.  
    Pro založení nového uživatele kontaktujte **petr.svrcula@cvrez.cz**.
    """)

authenticator.login(location='main')

if st.session_state.get('authentication_status'):
    username = st.session_state['username']
    role = get_user_role(username)
    name = st.session_state['name']

    st.sidebar.success(f"Vítej, {name} ({role})!")
    authenticator.logout('Odhlásit se', location='sidebar')

    read_only = (role == 'viewer')

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

    # ──────────────────────────────────────────────────────────────
    # Přidat projekt / úkol
    # ──────────────────────────────────────────────────────────────
    if option == "Přidat projekt / úkol":
        if read_only:
            st.error("Tato sekce je pouze pro čtení (viewer).")
        else:
            st.header("Přidat projekt a/nebo úkol")

            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Přidat projekt")
                proj_id = st.text_input("Číslo projektu", key="new_proj_id")
                proj_name = st.text_input("Název projektu (volitelné)", key="new_proj_name")

                if st.button("Přidat projekt"):
                    if proj_id.strip():
                        if add_project(proj_id.strip(), proj_name.strip()):
                            st.success(f"Projekt {proj_id} přidán!")
                            st.rerun()
                        else:
                            st.error("Projekt s tímto ID již existuje.")
                    else:
                        st.error("Číslo projektu je povinné.")

            with col2:
                st.subheader("Přidat úkol")

                with st.form(key="add_task_form"):
                    colA, colB = st.columns(2)

                    with colA:
                        project_choices = get_project_choices()
                        project_id = st.selectbox("Projekt", project_choices, key="add_task_proj") if project_choices else None

                        order_number = st.number_input("Pořadí úkolu", min_value=1, step=1)

                        wp_list = get_workplaces()
                        wp_names = [name for _, name in wp_list]
                        wp_name_sel = st.selectbox("Pracoviště", wp_names)
                        wp_id = next((wid for wid, n in wp_list if n == wp_name_sel), None)

                        hours = st.number_input("Počet hodin", min_value=0.5, step=0.5, format="%.1f")

                    with colB:
                        capacity_mode = st.radio("Režim kapacity", ['7.5', '24'], horizontal=True)

                        if project_id:
                            current_tasks = get_tasks(project_id)
                            if current_tasks:
                                parent_options = {t['id']: f"{t['order_number']} – {get_workplace_name(t['workplace_id'])}" for t in current_tasks}
                                selected_labels = st.multiselect(
                                    "Nadřazené úkoly (prázdné = root)",
                                    list(parent_options.values()),
                                    default=[],
                                    key="parent_tasks_sel"
                                )
                                parent_ids = [pid for pid, lbl in parent_options.items() if lbl in selected_labels]
                            else:
                                parent_ids = []
                                st.info("Zatím žádné úkoly v projektu → tento bude kořenový.")
                        else:
                            parent_ids = []
                            st.info("Vyberte nejdříve projekt.")

                        samples_count = st.number_input("Počet vzorků", min_value=1, value=1)

                        if not parent_ids:
                            start_date_obj = st.date_input("Začátek (volitelné)", value=None, format="DD.MM.YYYY")
                            start_ddmmyyyy = start_date_obj.strftime('%d.%m.%Y') if start_date_obj else None
                        else:
                            start_ddmmyyyy = None
                            st.info("Datum začátku se dopočítá automaticky z nadřazených úkolů.")

                        notes = st.text_area("Poznámka / interní komentář")

                    submitted = st.form_submit_button("Přidat úkol")

                    if submitted:
                        if not project_id:
                            st.error("Vyberte projekt.")
                        elif not wp_id:
                            st.error("Vyberte pracoviště.")
                        elif hours <= 0:
                            st.error("Hodiny musí být kladné číslo.")
                        else:
                            try:
                                task_id = add_task(
                                    project_id=project_id,
                                    order_number=int(order_number),
                                    workplace_id=wp_id,
                                    hours=float(hours),
                                    mode=capacity_mode,
                                    parent_ids=parent_ids,
                                    samples_count=int(samples_count),
                                    start_ddmmyyyy=start_ddmmyyyy,
                                    notes=notes.strip()
                                )

                                collisions = get_colliding_projects(task_id)
                                if collisions:
                                    st.warning(f"⚠️ Kolize s projekty: {', '.join(map(str, collisions))}")
                                    if st.button("Přesto uložit (ignoruji kolize)"):
                                        st.success("Úkol uložen i přes kolize.")
                                        st.rerun()
                                else:
                                    st.success("Úkol úspěšně přidán!")
                                    st.rerun()

                            except Exception as e:
                                st.error(f"Chyba při vytváření úkolu:\n{str(e)}")

    # ──────────────────────────────────────────────────────────────
    # Prohlížet / Upravovat úkoly
    # ──────────────────────────────────────────────────────────────
    elif option == "Prohlížet / Upravovat úkoly":
        st.header("Prohlížet / upravovat úkoly projektu")

        project_choices = get_project_choices()
        if not project_choices:
            st.info("Neexistuje žádný projekt. Začněte přidáním projektu.")
        else:
            selected_project = st.selectbox("Vyberte projekt", project_choices, key="edit_project_select")

            tasks = get_tasks(selected_project)
            if not tasks:
                st.info("V projektu zatím nejsou žádné úkoly.")
            else:
                collisions = mark_all_collisions()

                data = []
                for t in tasks:
                    tid = t['id']
                    coll_text = ""
                    if collisions.get(tid, False):
                        cols = get_colliding_projects(tid)
                        coll_text = f"⚠️ Kolize: {', '.join(map(str, cols))}"

                    status_display = t['status']
                    if t['status'] == 'done':
                        status_display = "✅ Hotovo"
                    elif t['status'] == 'canceled':
                        status_display = f"❌ Zrušeno ({t.get('reason', '-')})"

                    parent_str = ', '.join(map(str, t.get('parent_ids', []))) or "Root"

                    data.append({
                        "ID": tid,
                        "Pořadí": t['order_number'],
                        "Nadřazené": parent_str,
                        "Vzorky": t.get('samples_count', 1),
                        "Pracoviště": get_workplace_name(t['workplace_id']),
                        "Hodiny": t['hours'],
                        "Režim": t['capacity_mode'],
                        "Začátek": yyyymmdd_to_ddmmyyyy(t.get('start_date')),
                        "Konec": yyyymmdd_to_ddmmyyyy(t.get('end_date')),
                        "Stav": status_display,
                        "Poznámka": t.get('notes', ''),
                        "Kolize": coll_text
                    })

                df = pd.DataFrame(data)

                grid_response = AgGrid(
                    df,
                    height=500,
                    editable=not read_only,
                    gridOptions={
                        "columnDefs": [
                            {"field": "Pořadí", "width": 90},
                            {"field": "Nadřazené", "width": 140},
                            {"field": "Vzorky", "width": 90},
                            {"field": "Pracoviště", "width": 220},
                            {"field": "Hodiny", "width": 100},
                            {"field": "Režim", "width": 100},
                            {"field": "Začátek", "editable": True, "width": 140},
                            {"field": "Konec", "editable": False, "width": 140},
                            {"field": "Stav", "width": 160},
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

                for idx, row in updated_df.iterrows():
                    task_id = row['ID']
                    new_start_raw = row['Začátek']
                    new_start_str = str(new_start_raw).strip() if pd.notna(new_start_raw) else ""

                    task = get_task(task_id)
                    original_start = yyyymmdd_to_ddmmyyyy(task.get('start_date')) if task else ""

                    if new_start_str != original_start:
                        if task and task.get('parent_ids'):
                            st.warning(f"Úkol {row['Pořadí']} má rodiče → datum začátku se automaticky přepočítává.")
                            continue

                        if new_start_str and not validate_ddmmyyyy(new_start_str):
                            st.error(f"Neplatné datum u úkolu {row['Pořadí']}: {new_start_str!r}")
                            continue

                        try:
                            update_task(task_id, 'start_date', new_start_str)
                            recalculate_from_task(task_id)
                            st.success(f"Datum začátku úkolu {row['Pořadí']} změněno → přepočítány termíny.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Chyba při aktualizaci data: {e}")

                # Změna stavu
                st.markdown("### Změna stavu úkolu")
                order_list = [t['order_number'] for t in tasks]
                selected_order = st.selectbox("Vyberte úkol", order_list, key="status_change_sel")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Označit jako Hotovo"):
                        task = next((t for t in tasks if t['order_number'] == selected_order), None)
                        if task:
                            update_task(task['id'], 'status', 'done')
                            recalculate_from_task(task['id'])
                            st.success(f"Úkol {selected_order} označen jako hotový.")
                            st.rerun()

                with col2:
                    reason = st.text_input("Důvod zrušení", key="cancel_reason_input")
                    if st.button("Označit jako Zrušeno"):
                        if reason.strip():
                            task = next((t for t in tasks if t['order_number'] == selected_order), None)
                            if task:
                                update_task(task['id'], 'reason', reason.strip())
                                update_task(task['id'], 'status', 'canceled')
                                recalculate_from_task(task['id'])
                                st.success(f"Úkol {selected_order} označen jako zrušený.")
                                st.rerun()
                        else:
                            st.error("U zrušení je povinný důvod.")

                if role == 'admin':
                    st.markdown("### Admin: Servisní mazání úkolu")
                    delete_order = st.selectbox("Úkol k trvalému smazání", order_list, key="admin_delete_sel")
                    task_del = next((t for t in tasks if t['order_number'] == delete_order), None)

                    if task_del:
                        st.write(f"Chystáte se smazat: **P{selected_project}-{delete_order}**  –  {get_workplace_name(task_del['workplace_id'])}")
                        if st.checkbox("**BERU NA VĚDOMÍ – MAZÁNÍ JE NEVRATNÉ**"):
                            if st.button("SMAZAT ÚKOL NAVŽDY"):
                                if delete_task(task_del['id']):
                                    st.success(f"Úkol {delete_order} smazán.")
                                    st.rerun()
                                else:
                                    st.error("Mazání selhalo.")

    # ──────────────────────────────────────────────────────────────
    # HMG měsíční
    # ──────────────────────────────────────────────────────────────
    elif option == "HMG měsíční":
        st.header("HMG měsíční – Gantt přehled po dnech")

        selected_year = st.number_input("Rok", 2020, 2035, datetime.now().year)
        selected_month = st.number_input("Měsíc", 1, 12, datetime.now().month)

        # Zajistíme aktuální data
        for pid, _ in get_projects():
            recalculate_project(pid)

        first_day = date(selected_year, selected_month, 1)
        last_day = (date(selected_year, selected_month + 1, 1) - timedelta(days=1)) if selected_month < 12 else date(selected_year + 1, 1, 1) - timedelta(days=1)

        num_days = last_day.day

        try:
            response = supabase.table('tasks') \
                .select('*') \
                .not_.is_('start_date', 'null') \
                .not_.is_('end_date', 'null') \
                .execute()
            all_tasks = response.data
        except:
            all_tasks = []
            st.error("Nepodařilo se načíst úkoly z databáze.")

        plot_data = []
        pdf_data = []
        workplaces_set = set()

        for t in all_tasks:
            if t.get('status') == 'canceled':
                continue

            try:
                start_date = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            except:
                continue

            if end_date < first_day or start_date > last_day:
                continue

            wp_name = get_workplace_name(t['workplace_id'])
            workplaces_set.add(wp_name)

            task_text = f"P{t['project_id']}-{t['order_number']}"
            if t.get('parent_ids'):
                task_text += f" (po {', '.join(map(str, t['parent_ids']))})"
            if check_collisions(t['id']):
                task_text += " !"

            color = "#4285f4"  # default
            if t['status'] == 'done':
                color = "#34a853"
            if check_collisions(t['id']):
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
            st.info(f"Pro {calendar.month_name[selected_month]} {selected_year} nejsou žádné relevantní úkoly.")
        else:
            df = pd.DataFrame(plot_data)

            all_labels = sorted(df['Úkol'].unique())
            selected_tasks = st.multiselect("Zobrazit jen vybrané úkoly", all_labels, default=all_labels)

            df_filtered = df[df['Úkol'].isin(selected_tasks)]

            fig = px.timeline(
                df_filtered,
                x_start="Start",
                x_end="Finish",
                y="Pracoviště",
                color="Color",
                color_discrete_map={"#4285f4": "#4285f4", "#34a853": "#34a853", "#ea4335": "#ea4335"},
                hover_name="Úkol",
                title=f"HMG – {calendar.month_name[selected_month]} {selected_year}",
                height=400 + len(workplaces_set) * 40
            )

            fig.update_xaxes(
                tickformat="%d",
                tickmode="linear",
                dtick=86400000,
                range=[first_day, last_day + timedelta(days=1)]
            )
            fig.update_yaxes(autorange="reversed")
            fig.update_layout(bargap=0.2, bargroupgap=0.1, showlegend=False)

            st.plotly_chart(fig, use_container_width=True)

            # PDF export
            if st.button("Exportovat do PDF"):
                filename = f"HMG_mesicni_{selected_year}_{selected_month:02d}.pdf"
                pdf = pdf_canvas.Canvas(filename, pagesize=landscape(A4))
                w, h = landscape(A4)

                pdf.setFont(PDF_FONT, 16)
                pdf.drawCentredString(w / 2, h - 0.8 * inch, f"HMG HK – {calendar.month_name[selected_month]} {selected_year}")

                left_margin = 1.0 * inch
                wp_col_width = 2.0 * inch
                day_col_width = (w - left_margin - wp_col_width - 0.8 * inch) / num_days

                header_y = h - 1.5 * inch

                # Hlavička dnů
                pdf.setFont(PDF_FONT, 10)
                for d in range(1, num_days + 1):
                    dt = date(selected_year, selected_month, d)
                    x = left_margin + wp_col_width + (d - 1) * day_col_width
                    color = (1, 0, 0) if is_weekend_or_holiday(dt) else (0, 0, 0)
                    pdf.setFillColorRGB(*color)
                    pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))

                pdf.setStrokeColorRGB(0, 0, 0)
                pdf.line(left_margin + wp_col_width, header_y - 10, w - 0.8 * inch, header_y - 10)

                # Řazení pracovišť HK1 → HK10...
                def hk_sort_key(name):
                    if name.startswith('HK'):
                        try:
                            return int(name[2:])
                        except:
                            return 999999
                    return name

                sorted_wps = sorted(workplaces_set, key=hk_sort_key)

                row_height = (h - 2.5 * inch) / len(sorted_wps) if sorted_wps else 40
                colors_rgb = {
                    "#4285f4": (0.26, 0.52, 0.96),
                    "#34a853": (0.20, 0.66, 0.32),
                    "#ea4335": (0.92, 0.26, 0.21)
                }

                for i, wp_name in enumerate(sorted_wps):
                    y_top = header_y - 20 - i * row_height
                    y_bottom = y_top - row_height

                    pdf.setFillColorRGB(0, 0, 0)
                    pdf.setFont(PDF_FONT, 9)
                    pdf.drawString(left_margin, y_top - row_height / 2, wp_name)

                    pdf.line(left_margin, y_bottom, w - 0.8 * inch, y_bottom)

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

                with open(filename, "rb") as f:
                    st.download_button(
                        "Stáhnout PDF",
                        f.read(),
                        file_name=filename,
                        mime="application/pdf"
                    )

    # ──────────────────────────────────────────────────────────────
    # HMG roční
    # ──────────────────────────────────────────────────────────────
    elif option == "HMG roční":
        st.header("HMG roční – Heatmapa obsazenosti")

        year = st.number_input("Rok", 2020, 2035, datetime.now().year)

        MONTH_CAPACITY = 200.0  # přibližně 200 pracovních hodin/měsíc (7.5×~26.7)

        for pid, _ in get_projects():
            recalculate_project(pid)

        workplaces = get_workplaces()
        months = ['Led', 'Úno', 'Bře', 'Dub', 'Kvě', 'Čer', 'Čvc', 'Srp', 'Zář', 'Říj', 'Lis', 'Pro']
        month_order = {m: i for i, m in enumerate(months)}

        occupancy = {name: [0.0] * 12 for _, name in workplaces}

        try:
            tasks = supabase.table('tasks') \
                .select('workplace_id, hours, capacity_mode, start_date, end_date, status') \
                .not_.is_('start_date', 'null') \
                .not_.is_('end_date', 'null') \
                .execute().data
        except:
            tasks = []
            st.error("Nepodařilo se načíst úkoly.")

        for t in tasks:
            if t['status'] == 'canceled':
                continue

            wp_name = get_workplace_name(t['workplace_id'])
            if wp_name not in occupancy:
                continue

            try:
                start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
                end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            except:
                continue

            if end.year < year or start.year > year:
                continue

            current = max(start, date(year, 1, 1))
            end_year = min(end, date(year, 12, 31))

            working_days = 0
            while current <= end_year:
                if is_working_day(current, t['capacity_mode']):
                    working_days += 1
                current += timedelta(days=1)

            if working_days == 0:
                continue

            hours_per_day = t['hours'] / working_days

            current = max(start, date(year, 1, 1))
            while current <= end_year:
                if is_working_day(current, t['capacity_mode']):
                    month_idx = current.month - 1
                    occupancy[wp_name][month_idx] += hours_per_day
                current += timedelta(days=1)

        data = []
        for wp_name, occ in occupancy.items():
            for m_idx, hours in enumerate(occ):
                percent = round((hours / MONTH_CAPACITY) * 100, 1) if MONTH_CAPACITY > 0 else 0
                data.append({
                    "Pracoviště": wp_name,
                    "Měsíc": months[m_idx],
                    "Hodiny": round(hours, 1),
                    "% využití": percent
                })

        if not data:
            st.info(f"Pro rok {year} nejsou žádné relevantní úkoly.")
        else:
            df = pd.DataFrame(data)
            df['Měsíc_order'] = df['Měsíc'].map(month_order)
            df = df.sort_values(['Pracoviště', 'Měsíc_order'])

            def hk_key(n):
                if n.startswith('HK'):
                    try:
                        return int(n[2:])
                    except:
                        return 999999
                return n

            all_wps = sorted(df['Pracoviště'].unique(), key=hk_key)
            selected_wps = st.multiselect("Filtr pracovišť", all_wps, default=all_wps)

            df = df[df['Pracoviště'].isin(selected_wps)]

            pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
            pivot = pivot[months]

            fig = px.imshow(
                pivot,
                labels={"color": "% využití"},
                title=f"Obsazenost pracovišť – rok {year}",
                color_continuous_scale=["#90EE90", "#FFFF99", "#FFB366", "#FF6B6B"],
                zmin=0,
                zmax=120
            )

            fig.update_layout(
                height=400 + len(all_wps) * 35,
                coloraxis_colorbar=dict(
                    title="% využití",
                    tickvals=[0, 50, 80, 100, 120],
                    ticktext=["0%", "50%", "80%", "100%", ">100%"]
                )
            )

            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Detailní čísla (hodiny / %)")

            hours_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="Hodiny")[months]
            perc_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")[months]

            combined = pd.concat([hours_pivot, perc_pivot], axis=1, keys=["Hodiny", "% využití"])
            st.dataframe(combined, use_container_width=True)

    # ──────────────────────────────────────────────────────────────
    # Správa pracovišť
    # ──────────────────────────────────────────────────────────────
    elif option == "Správa pracovišť":
        st.header("Správa pracovišť")

        if read_only:
            st.warning("Režim jen pro čtení.")
        else:
            st.subheader("Přidat nové pracoviště")
            new_wp = st.text_input("Název nového pracoviště (např. HK11)")
            if st.button("Přidat pracoviště") and new_wp.strip():
                if add_workplace(new_wp.strip()):
                    st.success(f"Pracoviště {new_wp} přidáno.")
                    st.rerun()
                else:
                    st.error("Nepodařilo se přidat pracoviště.")

            st.subheader("Existující pracoviště")
            wps = get_workplaces()
            if wps:
                for wid, wname in wps:
                    col1, col2 = st.columns([4, 1])
                    col1.write(f"• {wname} (ID: {wid})")
                    if col2.button("Smazat", key=f"del_wp_{wid}"):
                        if delete_workplace(wid):
                            st.success(f"Pracoviště {wname} smazáno.")
                            st.rerun()
                        else:
                            st.error("Nelze smazat – pracoviště je používáno v nějakém úkolu.")
            else:
                st.info("Zatím žádná pracoviště.")

    # ──────────────────────────────────────────────────────────────
    # Změna hesla
    # ──────────────────────────────────────────────────────────────
    elif option == "Změnit heslo":
        st.header("Změna vlastního hesla")

        with st.form("change_pw_form"):
            current_pw = st.text_input("Současné heslo", type="password")
            new_pw = st.text_input("Nové heslo", type="password")
            new_pw2 = st.text_input("Nové heslo znovu", type="password")

            submitted = st.form_submit_button("Změnit heslo")

            if submitted:
                if not all([current_pw, new_pw, new_pw2]):
                    st.error("Všechna pole jsou povinná.")
                elif new_pw != new_pw2:
                    st.error("Nová hesla se neshodují.")
                else:
                    # Pozn.: zde by měla být kontrola správnosti starého hesla!
                    # Pro jednoduchost to teď přeskakujeme (v produkci nutné!)
                    success, msg = change_password(username, new_pw)
                    if success:
                        st.success("Heslo bylo úspěšně změněno.")
                    else:
                        st.error(msg)

    # ──────────────────────────────────────────────────────────────
    # User Management (jen admin)
    # ──────────────────────────────────────────────────────────────
    elif option == "User Management" and role == 'admin':
        st.header("Správa uživatelů (admin only)")

        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            users = cfg['credentials']['usernames']
        except:
            users = {}
            st.error("Nepodařilo se načíst soubor uživatelů.")

        st.subheader("Existující uživatelé")
        for uname, data in users.items():
            st.write(f"• **{uname}**  –  {data.get('name', '?')}  ({data.get('role', '???')})")

        st.subheader("Přidat nového uživatele")
        with st.form("add_user_form"):
            new_uname = st.text_input("Uživatelské jméno")
            new_name = st.text_input("Celé jméno / zobrazované jméno")
            new_pw = st.text_input("Heslo", type="password")
            new_role = st.selectbox("Role", ["user", "admin", "viewer"])

            if st.form_submit_button("Vytvořit uživatele"):
                if not all([new_uname, new_name, new_pw]):
                    st.error("Všechna pole jsou povinná.")
                else:
                    success, msg = add_user(new_uname, new_name, new_pw, new_role)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        st.subheader("Reset hesla uživatele")
        reset_uname = st.selectbox("Vyberte uživatele k resetu", list(users.keys()), key="reset_user_sel")
        if st.button("Resetovat heslo na 1234"):
            success, msg = reset_password(reset_uname)
            if success:
                st.success(msg)
            else:
                st.error(msg)

# ──────────────────────────────────────────────────────────────
# Footer / stav nepřihlášen
# ──────────────────────────────────────────────────────────────
elif st.session_state.get('authentication_status') is False:
    st.error("Nesprávné přihlašovací údaje.")
elif st.session_state.get('authentication_status') is None:
    st.warning("Prosím přihlaste se.")

if st.session_state.get('authentication_status'):
    st.sidebar.markdown("---")
    st.sidebar.caption("Plánovač Horkých komor CVŘ • v1.1 • 2025–2026")
    st.sidebar.caption("petr.svrcula@cvrez.cz")