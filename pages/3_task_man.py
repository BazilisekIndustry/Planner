import streamlit as st
from utils.common import *  # ← importuje VŠECHNO z common.py (nejjednodušší)
authenticator = get_authenticator()  # ← vytvoř čerstvě
# Kontrola přihlášení
if not st.session_state.get('authentication_status'):
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data
username = st.session_state.get('username')
name = st.session_state.get('name')
role = st.session_state.get('role', 'viewer')
read_only = (role == 'viewer')
# Render sidebaru – předej aktuální název stránky
render_sidebar(authenticator, "Prohlížet / Upravovat úkoly")

st.header("Prohlížet / Upravovat úkoly")
if read_only:
    st.warning("V režimu prohlížení nelze provádět úpravy.")

projects = get_projects()
if not projects:
    st.info("Nejprve přidejte alespoň jeden projekt.")
else:
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
                            st.error("Chyba při mazání.")# Hlavní obsah stránky