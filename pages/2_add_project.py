# pages/2_add_project.py
import streamlit as st
from datetime import datetime
from utils.auth_simple import check_login
from utils.common import *
st.set_page_config(page_title="Plánovač HK", layout="wide")
# Kontrola přihlášení
if not check_login():
    st.switch_page("Home.py")
    st.stop()
# Základní uživatelské info
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
render_sidebar("Přidat projekt / úkol")
st.header("Přidat projekt a úkol")
if role == "viewer":
    st.error("Tato stránka je dostupná jen pro administrátory a běžné uživatele.")
    st.stop()
# ──────────────────────────────────────────────────────────────
# ROZDĚLENÍ NA DVA SLOUPCE
# ──────────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1.4])
# ──────────────────────────────
# LEVÝ SLOUPEC – PŘIDAT PROJEKT
# ──────────────────────────────
with col1:
    st.subheader("Přidat projekt")
    with st.form(key="add_project_form", clear_on_submit=True):
        proj_id = st.text_input("Číslo projektu (povinné)", key="new_proj_id")
        proj_name = st.text_input("Název projektu (volitelné)", key="new_proj_name")
        colors_list = get_safe_project_colors()  # [ (label, hex), ... ]
        color_labels = [label for label, _ in colors_list]
        # Čistý selectbox bez HTML v položkách
        selected_label = st.selectbox(
            "Barva projektu",
            options=color_labels,
            index=0,
            key="new_project_color_select"
        )
        # Najdeme vybranou barvu
        selected_color = next(
            (color for label, color in colors_list if label == selected_label),
            "#4285F4"  # fallback
        )
        # Barevný čtvereček + název barvy vedle sebe (Varianta A)
        st.markdown(
            f'''
            <div style="display: flex; align-items: center; gap: 12px; margin-top: -4px; margin-bottom: 8px;">
                <div style="
                    width: 28px;
                    height: 28px;
                    background-color: {selected_color};
                    border-radius: 6px;
                    border: 1px solid #d0d0d0;
                    flex-shrink: 0;
                "></div>
                <span style="font-size: 15px; color: #333;">{selected_label}</span>
            </div>
            ''',
            unsafe_allow_html=True
        )
        submitted = st.form_submit_button("Přidat projekt", type="primary", use_container_width=True)
        if submitted:
            proj_id_clean = proj_id.strip()
            if not proj_id_clean:
                st.error("Číslo projektu je povinné!")
            else:
                # Kontrola existence
                exists = supabase.table("projects").select("id").eq("id", proj_id_clean).execute()
                if exists.data:
                    st.error(f"Projekt s číslem **{proj_id_clean}** již existuje!")
                else:
                    proj_name_clean = proj_name.strip() or None
                    try:
                        success = add_project(
                            project_id=proj_id_clean,
                            name=proj_name_clean,
                            color=selected_color
                        )
                        if success:
                            st.session_state["project_added_success"] = True
                            st.session_state["project_added_id"] = proj_id_clean
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Nepodařilo se uložit projekt do databáze.")
                    except Exception as e:
                        st.error(f"Chyba při přidávání projektu:\n{str(e)}")
# Úspěšná hláška + balónky
if st.session_state.get("project_added_success", False):
    pid = st.session_state["project_added_id"]
    st.success(f"Projekt **{pid}** byl úspěšně přidán! 🎉")
    st.balloons()
    # Automaticky vybrat nový projekt v sekci úkolů
    projects = get_projects()
    display_options = [
        (f"{p_id} – {name or 'bez názvu'}", p_id)
        for p_id, name, *_ in projects
    ]
    new_display = next((opt for opt in display_options if opt[1] == pid), None)
    if new_display:
        st.session_state["add_task_project"] = new_display
    del st.session_state["project_added_success"]
    st.session_state.pop("project_added_id", None)
# ──────────────────────────────
# PRAVÝ SLOUPEC – PŘIDAT ÚKOL
# ──────────────────────────────
with col2:
    st.subheader("Přidat úkol")
    with st.form(key="add_task_form", clear_on_submit=True):
        colA, colB = st.columns(2)
        with colA:
            projects = get_projects()
            if not projects:
                st.warning("Neexistuje žádný projekt. Nejprve vytvořte projekt vlevo.")
                project_id = None
            else:
                display_options = [
                    (f"{pid} – {name or 'bez názvu'}", pid)
                    for pid, name, *_ in projects
                ]
                _, project_id = st.selectbox(
                    "Projekt",
                    options=display_options,
                    format_func=lambda x: x[0],
                    index=0,
                    key="add_task_project"
                )
            parent_id = None
            if project_id:
                possible_parents = get_tasks(project_id)
                parent_options = ["Žádný (root)"] + [
                    f"P{project_id} - {get_workplace_name(t['workplace_id'])} | "
                    f"Start: {yyyymmdd_to_ddmmyyyy(t['start_date']) or 'bez data'} | "
                    f"{(t['notes'] or '')[:28]}{'...' if len(t['notes'] or '') > 28 else ''}"
                    for t in possible_parents
                ]
                parent_choice = st.selectbox(
                    "Nadřazený úkol (větev)",
                    parent_options,
                    key=f"add_task_parent_{project_id}"
                )
                if parent_choice != "Žádný (root)":
                    idx = parent_options.index(parent_choice) - 1
                    if 0 <= idx < len(possible_parents):
                        parent_id = possible_parents[idx]["id"]
            else:
                st.info("Vyberte projekt pro zobrazení možných nadřazených úkolů.")
            wp_names = [name for _, name in get_workplaces()]
            wp_name = st.selectbox("Pracoviště", wp_names, key="add_task_wp")
            wp_id = next((wid for wid, name in get_workplaces() if name == wp_name), None)
            hours = st.number_input("Počet hodin", min_value=1, step=1, format="%d", key="add_task_hours")
            bodies_count = st.number_input("Počet těles", min_value=1, step=1, key="add_task_bodies")
            is_active = st.radio(
                "Stav těles",
                ["Aktivní", "Neaktivní"],
                index=0,
                horizontal=True,
                key="add_task_active"
            ) == "Aktivní"
        with colB:
            capacity_mode = st.radio(
                "Režim kapacity", ["7.5", "24"], horizontal=True, key="add_task_mode"
            )
            start_date_obj = st.date_input(
                "Začátek (volitelné)",
                value=None,
                format="DD.MM.YYYY",
                key="add_task_start"
            )
            start_ddmmyyyy = start_date_obj.strftime("%d.%m.%Y") if start_date_obj else None
            notes = st.text_area("Poznámka", height=108, key="add_task_notes")
        submitted = st.form_submit_button("Přidat úkol", use_container_width=True, type="primary")
        if submitted:
            if not project_id:
                st.error("Vyberte projekt")
            elif not wp_id:
                st.error("Vyberte pracoviště")
            elif hours < 1:
                st.error("Počet hodin musí být kladný")
            elif parent_id and has_cycle(parent_id):
                st.error("Zakázáno vytvořit cyklus v závislostech!")
            else:
                try:
                    start_yyyymmdd = ddmmyyyy_to_yyyymmdd(start_ddmmyyyy) if start_ddmmyyyy else None
                    temp_end = (
                        calculate_end_date(start_yyyymmdd, float(hours), capacity_mode)
                        if start_yyyymmdd else None
                    )
                    conflict_in_project = False
                    if start_yyyymmdd and temp_end:
                        existing = (
                            supabase.table("tasks")
                            .select("id, start_date, end_date")
                            .eq("project_id", project_id)
                            .eq("workplace_id", wp_id)
                            .not_.is_("start_date", "null")
                            .not_.is_("end_date", "null")
                            .execute()
                            .data
                        )
                        new_start = datetime.strptime(start_yyyymmdd, "%Y-%m-%d").date()
                        new_end = datetime.strptime(temp_end, "%Y-%m-%d").date()
                        for ex in existing:
                            ex_start = datetime.strptime(ex["start_date"], "%Y-%m-%d").date()
                            ex_end = datetime.strptime(ex["end_date"], "%Y-%m-%d").date()
                            if not (new_end < ex_start or new_start > ex_end):
                                conflict_in_project = True
                                break
                    if conflict_in_project:
                        st.error(
                            "Kolize uvnitř stejného projektu na tomto pracovišti!\n"
                            "Upravte existující úkol(y) a zkuste znovu."
                        )
                    else:
                        colliding_projects = (
                            get_colliding_projects_simulated(wp_id, start_yyyymmdd, temp_end)
                            if start_yyyymmdd and temp_end else []
                        )
                        if colliding_projects:
                            st.session_state["pending_task_data"] = {
                                "project_id": project_id,
                                "workplace_id": wp_id,
                                "hours": float(hours),
                                "mode": capacity_mode,
                                "start_ddmmyyyy": start_ddmmyyyy,
                                "notes": notes,
                                "bodies_count": int(bodies_count),
                                "is_active": is_active,
                                "parent_id": parent_id,
                            }
                            st.session_state["colliding_projects"] = colliding_projects
                            st.session_state["show_collision_confirm"] = True
                            st.session_state["selected_project"] = st.session_state.get("add_task_project")
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
                                parent_id=parent_id,
                            )
                            if task_id:
                                st.session_state["task_added_success"] = True
                                st.session_state["task_added_details"] = {
                                    "project": project_id,
                                    "workplace": wp_name,
                                    "hours": hours,
                                    "mode": capacity_mode,
                                    "start": start_ddmmyyyy or "automaticky",
                                }
                                if parent_id:
                                    children_count = len(get_children(parent_id))
                                    if children_count > 1:
                                        st.session_state["fork_warning"] = children_count
                                st.session_state["selected_project"] = st.session_state.get("add_task_project")
                                st.cache_data.clear()
                                st.rerun()
                except Exception as e:
                    st.error(f"Chyba při přidávání úkolu:\n{str(e)}")
# Obnovit vybraný projekt po přidání
if "selected_project" in st.session_state:
    st.session_state["add_task_project"] = st.session_state["selected_project"]
    del st.session_state["selected_project"]
# ──────────────────────────────────────────────────────────────
# POTVRZENÍ PŘI KOLIZI MEZI PROJEKTY
# ──────────────────────────────────────────────────────────────
if st.session_state.get("show_collision_confirm", False):
    pending = st.session_state["pending_task_data"]
    colliding_str = ", ".join(map(str, st.session_state.get("colliding_projects", [])))
    st.warning(
        f"**VAROVÁNÍ – KOLIZE MEZI PROJEKTY!**\n\n"
        f"Nový úkol bude kolidovat s projekty: **{colliding_str}**\n"
        f"na pracovišti **{get_workplace_name(pending['workplace_id'])}**.\n\n"
        "Opravdu chcete úkol přidat i přes tuto kolizi?"
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Ano, přidat přesto", type="primary"):
            task_id = add_task(**pending)
            if task_id:
                st.success("Úkol přidán i přes kolizi.")
                st.session_state["task_added_success"] = True
                st.session_state["task_added_details"] = {
                    "project": pending["project_id"],
                    "workplace": get_workplace_name(pending["workplace_id"]),
                    "hours": pending["hours"],
                    "mode": pending["mode"],
                    "start": pending["start_ddmmyyyy"] or "automaticky",
                }
                if pending.get("parent_id"):
                    cc = len(get_children(pending["parent_id"]))
                    if cc > 1:
                        st.session_state["fork_warning"] = cc
                projects = get_projects()
                name = next((n for pid, n, *_ in projects if pid == pending['project_id']), 'bez názvu')
                st.session_state["selected_project"] = (f"{pending['project_id']} – {name or 'bez názvu'}", pending['project_id'])
                st.cache_data.clear()
            for k in ["pending_task_data", "colliding_projects", "show_collision_confirm"]:
                st.session_state.pop(k, None)
            st.rerun()
    with c2:
        if st.button("Ne, zrušit"):
            st.info("Přidání úkolu zrušeno.")
            for k in ["pending_task_data", "colliding_projects", "show_collision_confirm"]:
                st.session_state.pop(k, None)
            st.rerun()
# ──────────────────────────────────────────────────────────────
# ÚSPĚŠNÉ HLÁŠKY
# ──────────────────────────────────────────────────────────────
if st.session_state.get("task_added_success", False):
    d = st.session_state["task_added_details"]
    st.success(
        f"**Úkol úspěšně přidán!** ✅\n\n"
        f"Projekt: **{d['project']}**\n"
        f"Pracoviště: **{d['workplace']}**\n"
        f"Hodiny: **{d['hours']}**   |   Režim: **{d['mode']}**\n"
        f"Začátek: **{d['start']}**"
    )
    st.toast("Nový úkol je připraven!", icon="🎉")
    del st.session_state["task_added_success"]
    st.session_state.pop("task_added_details", None)
if "fork_warning" in st.session_state:
    st.warning(
        f"Vytvořili jste **fork/split** – nadřazený úkol má nyní "
        f"**{st.session_state['fork_warning']}** potomků."
    )
    del st.session_state["fork_warning"]