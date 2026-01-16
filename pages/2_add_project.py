# pages/2_add_project.py
import streamlit as st
from utils.auth_simple import check_login, logout
from utils.common import *  # tvůj sidebar, pokud ho chceš zachovat

# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")
render_sidebar("Přidat projekt / úkol")

# Hlavní obsah stránky
st.header("Přidat projekt a úkol")
if role == 'viewer':
    st.error("Přístup jen pro administrátory a normální uživatele.")
else:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Přidat projekt")
        proj_id = st.text_input("Číslo projektu (povinné)", key="new_proj_id")
        proj_name = st.text_input("Název projektu (volitelné)", key="new_proj_name")
        colors_list = get_safe_project_colors()
        color_labels = [label for label, _ in colors_list]
        selected_label = st.selectbox("Barva projektu", color_labels, index=0)
        selected_color = next(color for label, color in colors_list if label == selected_label)
        
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
                            colliding_projects = []
                            if start_yyyymmdd and temp_end:
                                colliding_projects = get_colliding_projects_simulated(
                                    workplace_id=wp_id,
                                    start_date=start_yyyymmdd,
                                    end_date=temp_end
                                )

                            if colliding_projects:
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

    # Potvrzovací dialog pro kolizi
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
                    st.session_state['task_added_success'] = True
                    st.session_state['task_added_details'] = {
                        'project': pending['project_id'],
                        'workplace': get_workplace_name(pending['workplace_id']),
                        'hours': pending['hours'],
                        'mode': pending['mode'],
                        'start': pending['start_ddmmyyyy'] or 'automaticky'
                    }
                    if pending['parent_id']:
                        children_count = len(get_children(pending['parent_id']))
                        if children_count > 1:
                            st.session_state['fork_warning'] = children_count
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
