import streamlit as st
from utils.common import *  # ← importuje VŠECHNO z common.py (nejjednodušší)
from utils.auth_simple import check_login, logout
st.set_page_config(page_title="Plánovač HK", layout="wide")
# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()
# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")
# Render sidebaru – už bez authenticatoru!
render_sidebar("Prohlížet / Upravovat úkoly")
st.header("Prohlížet / Upravovat úkoly")
if read_only:
    st.warning("V režimu prohlížení nelze provádět úpravy.")
projects = get_projects()
if not projects:
    st.info("Nejprve přidejte alespoň jeden projekt.")
else:
    display_options = [
        (f"{pid} – {name or 'bez názvu'}", pid)
        for pid, name, color in projects   # ← přidáme color (i když ho nepoužijeme)
    ]
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
            parent_desc = "— (root)"
            if parent_id:
                parent_task = get_task(parent_id)
                if parent_task:
                    parent_wp = get_workplace_name(parent_task['workplace_id'])
                    parent_start = yyyymmdd_to_ddmmyyyy(parent_task['start_date']) or 'bez data'
                    parent_notes = parent_task['notes'][:30] or 'bez poznámky'
                    parent_desc = f"P{selected_project} – {parent_wp} – {parent_start} – {parent_notes}..."
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
                    {"field": "Poznámka", "editable": not read_only, "width": 250},
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
        for idx, row in updated_df.iterrows():  # Změna na iterrows() pro idx
            task_id = row['ID']
            task = get_task(task_id)
            # Úprava data zahájení
            new_start_raw = row['Začátek']
            new_start_str = str(new_start_raw).strip() if pd.notna(new_start_raw) else ""
            original_start = yyyymmdd_to_ddmmyyyy(task['start_date']) if task['start_date'] else ""
            # Úprava poznámky
            new_notes = row['Poznámka'].strip()
            original_notes = task.get('notes', "") or ""
            if new_notes != original_notes:
                try:
                    update_task(task_id, 'notes', new_notes)
                    log_action(username, 'update_notes', task_id, f"Změna poznámky z '{original_notes}' na '{new_notes}'")
                    changes_made = True
                except Exception as e:
                    st.error(f"Chyba při úpravě poznámky u úkolu {task_id}: {e}")
            if new_start_str == original_start:
                continue
            # Pokud je to kid a parent není done/canceled, nedovolit změnu
            parent_id = get_parent(task_id)
            if parent_id:
                parent_task = get_task(parent_id)
                if parent_task['status'] not in ['done', 'canceled']:
                    st.error(f"Nelze změnit datum u dětského úkolu {task_id}, protože parent není hotový nebo zrušený.")
                    continue
                else:
                    # Nastav flag custom_start při manuální změně u child
                    update_task(task_id, 'custom_start', True)
            if not new_start_str:
                try:
                    update_task(task_id, 'start_date', None)
                    log_action(username, 'update_start_date', task_id, "Datum zahájení vymazáno")
                    recalculate_from_task(task_id)
                    changes_made = True
                except Exception as e:
                    st.error(f"Chyba při vymazání data u úkolu {task_id}: {e}")
                continue
            if not validate_ddmmyyyy(new_start_str):
                st.error(f"Neplatné datum u úkolu {task_id}: '{new_start_str}'. Použijte např. 1.1.2026 nebo 15.03.2025")
                continue
            # Nový check kolize v projektu před updatem
            try:
                new_yyyymmdd = ddmmyyyy_to_yyyymmdd(new_start_str)
                temp_end = calculate_end_date(new_yyyymmdd, task['hours'], task['capacity_mode'])
                # Intra-projekt kolize (v rámci stejného projektu, stejné WP) - zakázat
                existing_in_project = supabase.table('tasks').select('id, start_date, end_date').eq('project_id', task['project_id']).eq('workplace_id', task['workplace_id']).neq('id', task_id).not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute().data
                new_start_date = datetime.strptime(new_yyyymmdd, '%Y-%m-%d').date()
                new_end_date = datetime.strptime(temp_end, '%Y-%m-%d').date()
                conflict_in_project = False
                for ex in existing_in_project:
                    ex_start = datetime.strptime(ex['start_date'], '%Y-%m-%d').date()
                    ex_end = datetime.strptime(ex['end_date'], '%Y-%m-%d').date()
                    if not (new_end_date < ex_start or new_start_date > ex_end):
                        conflict_in_project = True
                        break
                if conflict_in_project:
                    st.error(f"Kolize v rámci projektu u úkolu {task_id} na tomto pracovišti. Upravte datum a zkuste znovu.")
                    continue
                # Inter-projekt kolize (jiné projekty, stejné WP) - upozornit, ale povolit
                existing_out_project = supabase.table('tasks').select('id, start_date, end_date, project_id').neq('project_id', task['project_id']).eq('workplace_id', task['workplace_id']).not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute().data
                conflict_out_project = []
                for ex in existing_out_project:
                    ex_start = datetime.strptime(ex['start_date'], '%Y-%m-%d').date()
                    ex_end = datetime.strptime(ex['end_date'], '%Y-%m-%d').date()
                    if not (new_end_date < ex_start or new_start_date > ex_end):
                        conflict_out_project.append(f"P{ex['project_id']}")
                if conflict_out_project:
                    st.warning(f"Pozor, po změně dojde ke kolizi s jinými projekty na stejném pracovišti: {', '.join(set(conflict_out_project))}. Změna bude provedena, ale zkontrolujte kolize.")
                # Proveď update
                update_task(task_id, 'start_date', new_yyyymmdd)
                log_action(username, 'update_start_date', task_id, f"Změna data zahájení z '{original_start}' na '{new_start_str}'")
                recalculate_from_task(task_id)
                changes_made = True
            except Exception as e:
                st.error(f"Chyba při úpravě data u úkolu {task_id}: {e}")
        if changes_made:
            st.success("Změny uloženy a termíny přepočítány.")
            st.rerun()
        if tasks and not read_only:
            st.markdown("### Změna stavu úkolu")
            task_options = []
            for t in tasks:
                wp_name = get_workplace_name(t['workplace_id'])
                start = yyyymmdd_to_ddmmyyyy(t['start_date']) or 'bez data'
                status_icon = "✅ " if t['status'] == 'done' else "❌ " if t['status'] == 'canceled' else ""
                desc = f"P{selected_project} – {wp_name} – {start} – {t['hours']}h – {status_icon}{t['status']} – {t['notes'][:40] or 'bez poznámky'}..."
                task_options.append((desc, t['id']))
            selected_task_display = st.selectbox("Vyberte úkol", [opt[0] for opt in task_options], key="status_change_order")
            selected_task_id = next(opt[1] for opt in task_options if opt[0] == selected_task_display)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Označit jako Hotovo"):
                    update_task(selected_task_id, 'status', 'done')
                    log_action(username, 'mark_done', selected_task_id, "Úkol označen jako hotový")
                    # Možnost zadat nové datum pro kids
                    kids_ids = get_children(selected_task_id)
                    kids = [get_task(kid_id) for kid_id in kids_ids if get_task(kid_id)]
                    if kids:
                        st.markdown("### Nastavení nového data zahájení pro dětské úkoly")
                        for kid in kids:
                            kid_desc = f"Úkol {kid['id']}: {get_workplace_name(kid['workplace_id'])} – {yyyymmdd_to_ddmmyyyy(kid['start_date']) or 'bez data'}"
                            new_kid_start = st.text_input(f"Nové datum zahájení pro {kid_desc} (dd.mm.yyyy)", key=f"new_start_{kid['id']}")
                            if new_kid_start and validate_ddmmyyyy(new_kid_start):
                                new_kid_yyyymmdd = ddmmyyyy_to_yyyymmdd(new_kid_start)
                                update_task(kid['id'], 'start_date', new_kid_yyyymmdd)
                                update_task(kid['id'], 'custom_start', True)  # Nastav flag pro custom start
                                log_action(username, 'update_kid_start', kid['id'], f"Nové datum zahájení po hotovém parentu: {new_kid_start}")
                    recalculate_from_task(selected_task_id)
                    st.success("Úkol označen jako hotový.")
                    st.rerun()
            with col2:
                reason = st.text_input("Důvod zrušení", key="cancel_reason_input")
                if st.button("Označit jako Zrušeno"):
                    if reason.strip():
                        update_task(selected_task_id, 'reason', reason.strip())
                        update_task(selected_task_id, 'status', 'canceled')
                        log_action(username, 'mark_canceled', selected_task_id, f"Úkol zrušen s důvodem: {reason.strip()}")
                        # Možnost zadat nové datum pro kids
                        kids_ids = get_children(selected_task_id)
                        kids = [get_task(kid_id) for kid_id in kids_ids if get_task(kid_id)]
                        if kids:
                            st.markdown("### Nastavení nového data zahájení pro dětské úkoly")
                            for kid in kids:
                                kid_desc = f"Úkol {kid['id']}: {get_workplace_name(kid['workplace_id'])} – {yyyymmdd_to_ddmmyyyy(kid['start_date']) or 'bez data'}"
                                new_kid_start = st.text_input(f"Nové datum zahájení pro {kid_desc} (dd.mm.yyyy)", key=f"new_start_cancel_{kid['id']}")
                                if new_kid_start and validate_ddmmyyyy(new_kid_start):
                                    new_kid_yyyymmdd = ddmmyyyy_to_yyyymmdd(new_kid_start)
                                    update_task(kid['id'], 'start_date', new_kid_yyyymmdd)
                                    update_task(kid['id'], 'custom_start', True)  # Nastav flag pro custom start
                                    log_action(username, 'update_kid_start', kid['id'], f"Nové datum zahájení po zrušeném parentu: {new_kid_start}")
                        recalculate_from_task(selected_task_id)
                        st.success("Úkol zrušen.")
                        st.rerun()
                    else:
                        st.error("Zadejte důvod zrušení.")
            if role == 'admin':
                st.markdown("### Servisní mazání úkolu (pouze admin)")
                delete_display = st.selectbox("Vyberte úkol k smazání", [opt[0] for opt in task_options], key="admin_delete")
                delete_task_id = next(opt[1] for opt in task_options if opt[0] == delete_display)
                if st.checkbox("Potvrďte smazání tohoto úkolu (neodvolatelné!)"):
                    if st.button("SMAZAT ÚKOL"):
                        if delete_task(delete_task_id):
                            log_action(username, 'delete_task', delete_task_id, "Úkol smazán adminem")
                            st.success("Úkol smazán.")
                            st.rerun()
                        else:
                            st.error("Chyba při mazání.")