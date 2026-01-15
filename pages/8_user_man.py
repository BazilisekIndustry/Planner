# pages/8_User_Management.py
import streamlit as st
from utils.common import *  # ← všechno (add_user, reset_password, delete_project atd.)

authenticator = get_authenticator()  # ← čerstvý autentizátor

# Kontrola přihlášení
if not st.session_state.get('authentication_status'):
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data
username = st.session_state.get('username')
name = st.session_state.get('name')
role = st.session_state.get('role', 'viewer')

# Sidebar
render_sidebar(authenticator, "User Management")

# Celý obsah jen pro adminy
if role != 'admin':
    st.error("Přístup jen pro administrátory.")
else:
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
                    load_users_from_db.clear()
                    st.rerun()
                else:
                    st.error(message)
            except Exception as e:
                st.error(f"Neočekávaná chyba při přidávání uživatele: {e}")

    st.subheader("Resetovat heslo uživatele")
    try:
        users_response = supabase.table('app_users')\
                        .select("username, name")\
                        .execute()
        
        if users_response.data:
            user_options = [f"{row['username']} ({row['name']})" for row in users_response.data]
            selected_user_str = st.selectbox("Vyberte uživatele k resetu hesla", user_options, key="reset_user_select")
            
            if selected_user_str:
                selected_username = selected_user_str.split(" (")[0]
                
                agree_reset = st.checkbox(f"Potvrzuji reset hesla uživatele **{selected_username}** na '1234'")
                if st.button("Resetovat heslo na 1234", type="primary", disabled=not agree_reset):
                    try:
                        success, message = reset_password(selected_username)
                        if success:
                            st.success(message)
                            load_users_from_db.clear()
                            st.rerun()
                        else:
                            st.error(message)
                    except Exception as e:
                        st.error(f"Chyba při resetu hesla: {e}")
        else:
            st.info("Žádní uživatelé v databázi.")
    except Exception as e:
        st.error(f"Chyba při načítání uživatelů pro reset: {e}")

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
            st.dataframe(df_users, width='stretch')
        else:
            st.info("V databázi zatím nejsou žádní uživatelé.")
    except Exception as e:
        st.error(f"Chyba při načítání seznamu uživatelů: {e}")

    st.markdown("### Smazání celého projektu (neodvolatelné!)")
    project_choices = get_project_choices()
    if project_choices:
        proj_to_delete = st.selectbox(
            "Vyberte projekt k úplnému smazání",
            project_choices,
            key="admin_delete_project_select"
        )
        proj_name = "bez názvu"
        for pid, pname in get_projects():
            if pid == proj_to_delete:
                proj_name = pname
                break
        
        st.warning(f"**Pozor!** Bude smazán projekt **{proj_to_delete} – {proj_name}** včetně všech úkolů, závislostí a historie. Akce nelze vrátit!")
        
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