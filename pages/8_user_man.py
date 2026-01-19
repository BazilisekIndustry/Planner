# pages/8_User_Management.py
import time
import streamlit as st
from utils.common import *  # ← add_user, reset_password, delete_project, get_project_choices, get_projects atd.
from utils.auth_simple import check_login, logout
st.set_page_config(page_title="User managment", layout="wide")
# Kontrola přihlášení
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")

# Sidebar
render_sidebar("User Management")

# Celý obsah jen pro adminy
if role != 'admin':
    st.error("Přístup jen pro administrátory.")
else:
    st.header("User Management – Pouze pro admin")

    # Načteme uživatele jednou (pro všechny sekce)
    try:
        users_response = supabase.table('app_users')\
                         .select("username, name, role, email")\
                         .execute()
        users = users_response.data or []
    except Exception as e:
        st.error(f"Chyba při načítání uživatelů: {e}")
        users = []

    # 1. Přidat nového uživatele
    st.subheader("Přidat nového uživatele")
    col1, col2 = st.columns(2)
    with col1:
        new_username = st.text_input("Uživatelské jméno (povinné)", key="new_u_username")
        new_name = st.text_input("Celé jméno (povinné)", key="new_u_name")
        new_email = st.text_input("Email (volitelné)", key="new_u_email")
    with col2:
        new_role = st.selectbox("Role", ["normal", "viewer"], key="new_u_role")
        default_pw = "1234"
        st.info(f"Výchozí heslo: **{default_pw}** (uživatel by ho měl ihned změnit po prvním přihlášení)")

    agree_add = st.checkbox("Souhlasím s přidáním nového uživatele s výchozím heslem 1234")
    if st.button("Přidat uživatele", type="primary", disabled=not agree_add):
        if not new_username.strip() or not new_name.strip():
            st.error("Uživatelské jméno a celé jméno jsou povinné.")
        else:
            try:
                success, message = add_user(
                    username=new_username.strip(),
                    name=new_name.strip(),
                    password=default_pw,
                    role=new_role,
                    email=new_email.strip()
                )
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
            except Exception as e:
                st.error(f"Neočekávaná chyba při přidávání uživatele: {e}")

    # 2. Resetovat heslo uživatele
    st.subheader("Resetovat heslo uživatele")
    if users:
        user_options = [f"{u['username']} ({u['name']})" for u in users]
        selected_user_str = st.selectbox("Vyberte uživatele k resetu hesla", user_options, key="reset_user_select")
        
        if selected_user_str:
            selected_username = selected_user_str.split(" (")[0]
            
            agree_reset = st.checkbox(f"Potvrzuji reset hesla uživatele **{selected_username}** na '1234'")
            if st.button("Resetovat heslo na 1234", type="primary", disabled=not agree_reset):
                try:
                    success, message = reset_password(selected_username)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
                except Exception as e:
                    st.error(f"Chyba při resetu hesla: {e}")
    else:
        st.info("Žádní uživatelé v databázi.")

    # 3. Aktuální uživatelé + Smazání uživatele
    st.subheader("Aktuální uživatelé")
    if users:
        df_users = pd.DataFrame(users)
        df_users = df_users.rename(columns={
            "username": "Uživatelské jméno",
            "name": "Jméno",
            "role": "Role",
            "email": "Email"
        })
        st.dataframe(df_users, use_container_width=True)
    else:
        st.info("V databázi zatím nejsou žádní uživatelé.")

    # Smazání uživatele (pod seznamem)
    st.markdown("### Smazání uživatele (neodvolatelné!)")
    if users:
        selected_user_str = st.selectbox("Vyberte uživatele k smazání", user_options, key="delete_user_select")
        
        if selected_user_str:
            selected_username = selected_user_str.split(" (")[0]
            
            agree_delete = st.checkbox(f"Potvrzuji trvalé smazání uživatele **{selected_username}** (nelze vrátit)")
            
            if st.button("SMAZAT UŽIVATELE", type="primary", disabled=not agree_delete):
                try:
                    response = supabase.table('app_users')\
                               .delete()\
                               .eq("username", selected_username)\
                               .execute()
                    if response.data:
                        st.success(f"Uživatel '{selected_username}' byl úspěšně smazán.")
                        st.rerun()
                    else:
                        st.error("Uživatel nenalezen nebo smazání selhalo.")
                except Exception as e:
                    st.error(f"Chyba při mazání uživatele: {e}")
    else:
        st.info("Žádní uživatelé k smazání.")

    # 4. Smazání celého projektu (zachováno)
    st.markdown("### Smazání celého projektu (neodvolatelné!)")
    project_choices = get_project_choices()
    if project_choices:
        proj_to_delete = st.selectbox(
            "Vyberte projekt k úplnému smazání",
            project_choices,
            key="admin_delete_project_select"
        )
        proj_name = "bez názvu"
        for pid, name, color in get_projects():
            if pid == proj_to_delete:
                proj_name = name
                break   
        st.warning(f"**Pozor!** Bude smazán projekt **{proj_to_delete} – {proj_name}** včetně všech úkolů a historie. Akce nelze vrátit!")
        
        agree_delete = st.checkbox("Potvrzuji trvalé smazání projektu i s úkoly")
        if st.button("SMAZAT CELÝ PROJEKT", type="primary", disabled=not agree_delete):
            try:
                if delete_project(proj_to_delete):
                    st.success(f"Projekt {proj_to_delete} kompletně smazán.")
                    st.rerun()
                else:
                    st.error("Smazání selhalo – zkuste to znovu nebo kontaktujte správce.")
            except Exception as e:
                st.error(f"Chyba při mazání projektu: {e}")
    else:
        st.info("Žádné projekty k smazání.")