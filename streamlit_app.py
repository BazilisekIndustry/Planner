import streamlit as st
import streamlit_authenticator as stauth
import yaml
import os
from datetime import datetime, timedelta, date
import math
import re
import calendar
from supabase import create_client
import pandas as pd
from st_aggrid import AgGrid, GridUpdateMode, DataReturnMode

# ============================
# KONFIGURACE
# ============================
USERS_FILE = 'users.yaml'
SUPABASE_URL = st.secrets["supabase_url"]
SUPABASE_KEY = st.secrets["supabase_key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    return date_str.replace('.', '-').replace('/', '-')

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
    if not re.compile(r'^\d{2}-\d{2}-\d{4}$').match(normalized):
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
    pass  # Tabulky jsou v Supabase

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
    except:
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
    except:
        return False

def get_tasks(project_id):
    response = supabase.table('tasks').select('*').eq('project_id', project_id).order('order_number').execute()
    return response.data

def add_task(project_id, order_number, workplace_id, hours, mode, parent_ids=None, samples_count=1, start_ddmmyyyy=None, notes=''):
    if parent_ids is None:
        parent_ids = []

    if parent_ids:
        siblings_query = supabase.table('tasks').select('workplace_id').eq('project_id', project_id)
        for pid in parent_ids:
            siblings_query = siblings_query.contains('parent_ids', [pid])
        siblings = siblings_query.execute().data
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
        'notes': notes
    }

    response = supabase.table('tasks').insert(data).execute()
    task_id = response.data[0]['id']
    recalculate_from_task(task_id)
    return task_id

def update_task(task_id, field, value, is_internal=False):
    if field in ('start_date', 'end_date') and value and not is_internal:
        value = ddmmyyyy_to_yyyymmdd(value)
    supabase.table('tasks').update({field: value}).eq('id', task_id).execute()
    now = datetime.now().isoformat()
    supabase.table('change_log').insert({'task_id': task_id, 'change_time': now, 'description': f'Updated {field} to {value}'}).execute()

def get_task(task_id):
    response = supabase.table('tasks').select('*').eq('id', task_id).execute()
    return response.data[0] if response.data else None

def get_project_root_tasks(project_id):
    response = supabase.table('tasks').select('*').eq('project_id', project_id).eq('parent_ids', '{}').execute()
    return response.data

def recalculate_from_task(task_id):
    task = get_task(task_id)
    if not task:
        return

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
            new_start_str = new_start.strftime('%Y-%m-%d')
            update_task(task_id, 'start_date', new_start_str, is_internal=True)
        else:
            update_task(task_id, 'start_date', None, is_internal=True)
            update_task(task_id, 'end_date', None, is_internal=True)
            return

    if task['status'] != 'done' and task.get('start_date'):
        end_str = calculate_end_date(task['start_date'], task['hours'], task['capacity_mode'])
        update_task(task_id, 'end_date', end_str, is_internal=True)

    children_response = supabase.table('tasks').select('id').contains('parent_ids', [task_id]).execute()
    for child in children_response.data:
        recalculate_from_task(child['id'])

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
    response = supabase.table('tasks').select('project_id').eq('workplace_id', wp).neq('id', task_id).not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
    colliding = []
    for row in response.data:
        row_start = datetime.strptime(row['start_date'], '%Y-%m-%d').date()
        row_end = datetime.strptime(row['end_date'], '%Y-%m-%d').date()
        if not (end < row_start or start > row_end):
            colliding.append(row['project_id'])
    return colliding

def check_collisions(task_id):
    return len(get_colliding_projects(task_id)) > 0

def mark_all_collisions():
    response = supabase.table('tasks').select('id').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
    ids = [row['id'] for row in response.data]
    return {tid: check_collisions(tid) for tid in ids}

def delete_task(task_id):
    try:
        supabase.table('change_log').delete().eq('task_id', task_id).execute()
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
            supabase.table('tasks').delete().eq('id', task['id']).execute()
        supabase.table('projects').delete().eq('id', project_id).execute()
        return True
    except Exception as e:
        st.error(f"Chyba při mazání projektu: {str(e)}")
        return False
    
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

# Hlavn9 aplikace

st.set_page_config(page_title="Plánovač Horkých komor CVŘ", page_icon=":radioactive:", layout="wide")
st.title("Plánovač Horkých komor CVŘ")

if not st.session_state.get('authentication_status'):
    st.markdown("Vítejte v Plánovači Horkých komor CVŘ. Přihlaste se prosím.\n\nPro založení nového uživatele kontaktujte petr.svrcula@cvrez.cz.")

authenticator.login(location='main')

if st.session_state.get('authentication_status'):
    username = st.session_state['username']
    role = get_user_role(username)
    name = st.session_state['name']
    st.sidebar.success(f"Vítej, {name} ({role})!")
    authenticator.logout('Odhlásit se', location='sidebar')

    init_db()
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

    if option == "Přidat projekt / úkol":
        st.header("Přidat projekt a úkol")
        if role == 'viewer':
            st.error("Přístup jen pro administrátory a normální uživatele.")
        else:
            col1, col2 = st.columns(2)
            with col1:
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
                st.subheader("Přidat úkol")
                with st.form(key="add_task_form"):
                    col1_inner, col2_inner = st.columns(2)
                    with col1_inner:
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

                    with col2_inner:
                        capacity_mode = st.radio("Režim kapacity", ['7.5', '24'], horizontal=True)

                        current_tasks = get_tasks(project_id) if project_id else []
                        if current_tasks:
                            parent_options = {t['id']: f"{t['order_number']} - {get_workplace_name(t['workplace_id'])}" for t in current_tasks}
                            selected_labels = st.multiselect(
                                "Nadřazené úkoly (prázdné = první úkol, více = spojování)",
                                list(parent_options.values()),
                                default=[]
                            )
                            parent_ids = [pid for pid, label in parent_options.items() if label in selected_labels]
                        else:
                            parent_ids = []
                            st.info("Zatím žádné úkoly – tento bude první.")

                        samples_count = st.number_input("Počet vzorků v této větvi", min_value=1, value=1)

                        if not parent_ids:
                            start_date_obj = st.date_input("Začátek (volitelné)", value=None, format="DD.MM.YYYY")
                            start_ddmmyyyy = start_date_obj.strftime('%d.%m.%Y') if start_date_obj else None
                        else:
                            st.info("Datum začátku se přepočítá automaticky z nejpozdějšího dokončení nadřazených.")
                            start_ddmmyyyy = None

                        notes = st.text_area("Poznámka")

                    submitted = st.form_submit_button("Přidat úkol")
                    if submitted:
                        if not project_id:
                            st.error("Vyberte projekt.")
                        elif not wp_id:
                            st.error("Vyberte pracoviště.")
                        elif hours <= 0:
                            st.error("Zadejte platný počet hodin.")
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
                                        delete_task(task_id)
                                        st.info("Přidání zrušeno.")
                                else:
                                    st.success("Úkol úspěšně přidán!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Chyba při přidávání: {e}")

    elif option == "Prohlížet / Upravovat úkoly":
        st.header("Prohlížet / Upravovat úkoly")

        if read_only:
            st.warning("V režimu prohlížení nelze provádět úpravy.")

        project_choices = get_project_choices()
        if not project_choices:
            st.info("Nejprve přidejte projekt.")
        else:
            selected_project = st.selectbox("Vyberte projekt", project_choices, key="edit_proj")
            tasks = get_tasks(selected_project)

            if not tasks:
                st.info("Žádné úkoly v tomto projektu.")
            else:
                collisions = mark_all_collisions()

                data = []
                for t in tasks:
                    tid = t['id']
                    order = t['order_number']
                    wp_name = get_workplace_name(t['workplace_id'])
                    start_disp = yyyymmdd_to_ddmmyyyy(t.get('start_date')) if t.get('start_date') else ""
                    end_disp = yyyymmdd_to_ddmmyyyy(t.get('end_date')) if t.get('end_date') else ""

                    coll_text = ""
                    if collisions.get(tid, False):
                        colliding = get_colliding_projects(tid)
                        coll_text = f"⚠️ Kolize: {', '.join(colliding)}"

                    status_display = t['status']
                    if t['status'] == 'done':
                        status_display = "✅ Hotovo"
                    elif t['status'] == 'canceled':
                        status_display = f"❌ Zrušeno ({t.get('reason') or '-'})"

                    parent_display = ', '.join(map(str, t.get('parent_ids', []))) or "Root"
                    samples = t.get('samples_count', 1)

                    data.append({
                        "ID": tid,
                        "Pořadí": order,
                        "Nadřazené": parent_display,
                        "Vzorky": samples,
                        "Pracoviště": wp_name,
                        "Hodiny": t['hours'],
                        "Režim": t['capacity_mode'],
                        "Začátek": start_disp,
                        "Konec": end_disp,
                        "Stav": status_display,
                        "Poznámka": t.get('notes', "") or "",
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
                            {"field": "Začátek", "editable": lambda params: params.data["Nadřazené"] == "Root", "width": 140},
                            {"field": "Konec", "width": 140},
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

                for _, row in updated_df.iterrows():
                    task_id = row['ID']
                    new_start_raw = row['Začátek']
                    new_start_str = str(new_start_raw).strip() if pd.notna(new_start_raw) else ""

                    task = get_task(task_id)
                    original_start = yyyymmdd_to_ddmmyyyy(task.get('start_date')) if task.get('start_date') else ""

                    if new_start_str != original_start:
                        if task.get('parent_ids'):
                            st.warning(f"Ruční změna data začátku u úkolu {row['Pořadí']} není povolena – přepočítává se automaticky.")
                            continue

                        if new_start_str and not validate_ddmmyyyy(new_start_str):
                            st.error(f"Neplatné datum u úkolu {row['Pořadí']}: '{new_start_str}'. Použijte DD.MM.YYYY.")
                            continue

                        try:
                            update_task(task_id, 'start_date', new_start_str)
                            recalculate_from_task(task_id)
                            st.success(f"Datum začátku úkolu {row['Pořadí']} změněno → termíny přepočítány.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Chyba při úpravě: {e}")

                # Změna stavu
                st.markdown("### Změna stavu úkolu")
                selected_order = st.selectbox("Vyberte úkol podle pořadí", [t['order_number'] for t in tasks], key="status_change_order")

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
                    reason = st.text_input("Důvod zrušení", key="cancel_reason")
                    if st.button("Označit jako Zrušeno"):
                        if reason.strip():
                            task = next((t for t in tasks if t['order_number'] == selected_order), None)
                            if task:
                                update_task(task['id'], 'reason', reason.strip())
                                update_task(task['id'], 'status', 'canceled')
                                recalculate_from_task(task['id'])
                                st.success(f"Úkol {selected_order} zrušen.")
                                st.rerun()
                        else:
                            st.error("Zadejte důvod.")

                if role == 'admin':
                    st.markdown("### Servisní mazání úkolu (pouze admin)")
                    delete_order = st.selectbox("Vyberte úkol k smazání", [t['order_number'] for t in tasks], key="admin_delete")
                    task_to_delete = next((t for t in tasks if t['order_number'] == delete_order), None)
                    if task_to_delete:
                        st.write(f"Úkol: P{task_to_delete['project_id']}-{task_to_delete['order_number']} na pracovišti {get_workplace_name(task_to_delete['workplace_id'])}")
                        if st.checkbox("Potvrďte smazání (neodvolatelné!)"):
                            if st.button("SMAZAT ÚKOL"):
                                if delete_task(task_to_delete['id']):
                                    st.success(f"Úkol {delete_order} smazán.")
                                    st.rerun()
                                else:
                                    st.error("Chyba při mazání.")

#HMG měsíční
elif option == "HMG měsíční":
    st.header("HMG měsíční – Přehled úkolů po dnech")
    import plotly.express as px
    import pandas as pd

    selected_year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="hmg_year")
    selected_month = st.number_input("Měsíc", min_value=1, max_value=12, value=datetime.now().month, key="hmg_month")

    # Přepočet všech projektů – zajistíme aktuální data
    all_projects = get_projects()
    for proj_id, _ in all_projects:
        recalculate_project(proj_id)

    # Období měsíce
    first_day = date(selected_year, selected_month, 1)
    if selected_month == 12:
        last_day = date(selected_year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(selected_year, selected_month + 1, 1) - timedelta(days=1)
    num_days = last_day.day

    # Načtení všech relevantních úkolů
    response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
    all_tasks = response.data

    plot_data = []
    pdf_data = []
    workplaces_set = set()

    for t in all_tasks:
        if t['status'] == 'canceled':
            continue

        tid = t['id']
        pid = t['project_id']
        order = t['order_number']
        wp_id = t['workplace_id']
        hours = t['hours']
        mode = t['capacity_mode']
        start_int = t['start_date']
        end_int = t['end_date']
        status = t['status']

        start_date = datetime.strptime(start_int, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_int, '%Y-%m-%d').date()

        if end_date < first_day or start_date > last_day:
            continue

        wp_name = get_workplace_name(wp_id)
        workplaces_set.add(wp_name)

        # Hierarchický label pro lepší přehled
        parent_ids = t.get('parent_ids', [])
        task_text = f"P{pid}-{order}"
        if parent_ids:
            task_text += f" (po {', '.join(map(str, parent_ids))})"
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

        # Filtr větví/úkolů
        all_tasks_labels = sorted(set(df['Úkol']))
        selected_tasks = st.multiselect("Zobrazit jen tyto úkoly/větve", all_tasks_labels, default=all_tasks_labels)
        df = df[df['Úkol'].isin(selected_tasks)]

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

        st.plotly_chart(fig, use_container_width=True)

        # PDF export
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

            # Hlavička dnů
            pdf.setFont(PDF_FONT, 10)
            for d in range(1, num_days + 1):
                current_date = date(selected_year, selected_month, d)
                x = left_margin + wp_col_width + (d - 1) * day_col_width
                fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
                pdf.setFillColorRGB(*fill_color)
                pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))

            pdf.setStrokeColorRGB(0, 0, 0)
            pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)

            # Řazení pracovišť numericky (HK1 → HK9 → HK10)
            def hk_key(name):
                if name.startswith('HK'):
                    try:
                        return int(name[2:])
                    except:
                        return 999999
                return name

            sorted_workplaces = sorted(workplaces_set, key=hk_key)

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

# HGM roční
elif option == "HMG roční":
    st.header("HMG roční – Heatmap obsazenosti pracovišť")
    import plotly.express as px
    import pandas as pd

    year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="year_rocni")
    MONTH_CAPACITY = 200.0

    # Přepočet všech projektů
    all_projects = get_projects()
    for proj_id, _ in all_projects:
        recalculate_project(proj_id)

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

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
        except:
            continue  # špatný formát data → přeskočit

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
        df['Měsíc_order'] = df['Měsíc'].map(month_order)
        df = df.sort_values(['Pracoviště', 'Měsíc_order'])

        # Filtr pracovišť + numerické řazení HK1..HK10
        def hk_key(name):
            if name.startswith('HK'):
                try:
                    return int(name[2:])
                except:
                    return 999999
            return name

        all_workplaces = sorted(df['Pracoviště'].unique(), key=hk_key)
        selected_workplaces = st.multiselect("Filtr pracovišť", all_workplaces, default=all_workplaces)
        df = df[df['Pracoviště'].isin(selected_workplaces)]

        pivot_df = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
        pivot_df = pivot_df[months]  # správné pořadí měsíců

        fig = px.imshow(
            pivot_df,
            labels=dict(color="% využití"),
            title=f"Obsazenost pracovišť {year}",
            color_continuous_scale=["#90EE90", "#FFFF99", "#FFB366", "#FF6B6B"],
            zmin=0,
            zmax=120
        )

        fig.update_layout(
            height=400 + len(all_workplaces) * 35,
            coloraxis_colorbar=dict(
                title="% využití",
                tickvals=[0, 50, 80, 100, 120],
                ticktext=["0%", "50%", "80%", "100%", ">100%"]
            )
        )

        st.plotly_chart(fig, use_container_width=True)

        # Detailní přehled
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

        st.dataframe(combined, use_container_width=True)

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
