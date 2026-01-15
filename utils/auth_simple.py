# utils/auth_simple.py
import streamlit as st
from streamlit_cookies_controller import CookieController
from streamlit_authenticator.utilities.hasher import Hasher
import time
from utils.common import supabase, load_users_from_db  # ← tvůj existující Supabase klient a funkce

# Inicializace cookie controlleru (globální)
cookie_controller = CookieController()

COOKIE_NAME = "planner_user_session"  # nový název cookie, aby se nepletl se starým

def hash_password(password: str) -> str:
    """Hash hesla stejně jako máš v add_user/reset_password"""
    return Hasher([password]).generate()[0]

def authenticate_user(username: str, password: str):
    """Ověří uživatele proti Supabase"""
    try:
        response = supabase.table('app_users')\
                   .select("id, username, name, role, password_hash")\
                   .eq("username", username)\
                   .execute()

        if not response.data:
            return None

        user = response.data[0]
        stored_hash = user['password_hash']
        input_hash = hash_password(password)

        if input_hash == stored_hash:
            return {
                "id": user['id'],
                "username": user['username'],
                "name": user['name'],
                "role": user.get('role', 'viewer')
            }
        else:
            return None
    except Exception as e:
        print(f"Chyba při autentizaci: {e}")
        return None

def login(username: str, password: str):
    user_data = authenticate_user(username, password)
    if user_data:
        # Ulož do cookie a session_state
        cookie_controller.set(COOKIE_NAME, user_data['id'], max_age=60*60*24*90)  # 90 dní
        st.session_state["user_id"] = user_data['id']
        st.session_state["username"] = user_data['username']
        st.session_state["name"] = user_data['name']
        st.session_state["role"] = user_data['role']
        st.session_state["authentication_status"] = True

        st.success("Přihlášeno úspěšně!")
        time.sleep(0.5)
        st.rerun()
    else:
        st.error("Nesprávné uživatelské jméno nebo heslo.")

def logout():
    cookie_controller.set(COOKIE_NAME, "", max_age=0)
    for key in ["user_id", "username", "name", "role", "authentication_status"]:
        st.session_state.pop(key, None)
    st.success("Odhlášeno úspěšně!")
    time.sleep(0.5)
    st.rerun()

def check_login():
    """Kontroluje, jestli je uživatel přihlášen (z cookie nebo session)"""
    user_id = cookie_controller.get(COOKIE_NAME)

    if user_id:
        # Pokud máme cookie, ale session_state je prázdná → obnov z DB
        if "username" not in st.session_state:
            try:
                response = supabase.table('app_users')\
                           .select("username, name, role")\
                           .eq("id", user_id)\
                           .execute()
                if response.data:
                    user = response.data[0]
                    st.session_state["user_id"] = user_id
                    st.session_state["username"] = user['username']
                    st.session_state["name"] = user['name']
                    st.session_state["role"] = user.get('role', 'viewer')
                    st.session_state["authentication_status"] = True
                    return True
            except Exception as e:
                print(f"Chyba při obnově session: {e}")
                return False
        return True
    return False