# utils/auth_simple.py
import streamlit as st
from streamlit_cookies_controller import CookieController
from streamlit_authenticator.utilities.hasher import Hasher
import time
from utils.common import supabase

cookie_controller = CookieController()
COOKIE_NAME = "planner_user_session_v3"

def hash_password(plain_password: str) -> str:
    """Aktuální správné bcrypt hashování pro verzi 0.4.2+"""
    temp_creds = {"usernames": {"temp": {"password": plain_password}}}
    Hasher.hash_passwords(temp_creds)
    return temp_creds["usernames"]["temp"]["password"]

def authenticate_user(username: str, password: str):
    """Ověří uživatele proti Supabase"""
    username = username.strip()
    st.write(f"DEBUG: Přihlašuji '{username}'")  # ← pro ladění

    try:
        response = supabase.table('app_users')\
                   .select("id, username, name, role, password_hash")\
                   .eq("username", username)\
                   .execute()

        st.write(f"DEBUG: Supabase odpověď: {response.data}")  # ← klíčový výpis

        if not response.data:
            st.error("Uživatel nenalezen.")
            return None

        user = response.data[0]
        stored_hash = user['password_hash']
        input_hash = hash_password(password)

        st.write(f"DEBUG: Uložený hash: {stored_hash[:30]}...")  # začátek pro kontrolu
        st.write(f"DEBUG: Vypočítaný hash: {input_hash[:30]}...")

        if input_hash == stored_hash:
            return {
                "id": user['id'],
                "username": user['username'],
                "name": user['name'],
                "role": user.get('role', 'viewer')
            }
        else:
            st.error("Heslo nesedí.")
            return None
    except Exception as e:
        st.error(f"Chyba při dotazu na DB: {e}")
        return None

def login(username: str, password: str):
    user_data = authenticate_user(username, password)
    if user_data:
        cookie_controller.set(COOKIE_NAME, user_data['id'], max_age=60*60*24*90)
        st.session_state["user_id"] = user_data['id']
        st.session_state["username"] = user_data['username']
        st.session_state["name"] = user_data['name']
        st.session_state["role"] = user_data['role']
        st.session_state["authentication_status"] = True

        st.success("Přihlášeno!")
        time.sleep(0.5)
        st.rerun()
    else:
        st.error("Přihlášení selhalo.")

def logout():
    cookie_controller.set(COOKIE_NAME, "", max_age=0)
    for key in ["user_id", "username", "name", "role", "authentication_status"]:
        st.session_state.pop(key, None)
    st.success("Odhlášeno.")
    time.sleep(0.5)
    st.rerun()

def check_login():
    user_id = cookie_controller.get(COOKIE_NAME)
    if user_id:
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
                print(f"Chyba obnovy session: {e}")
                return False
        return True
    return False