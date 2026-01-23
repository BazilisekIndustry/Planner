# utils/auth_simple.py
import streamlit as st
from streamlit_cookies_controller import CookieController
from streamlit_authenticator.utilities.hasher import Hasher
import time
from utils.common import supabase
import bcrypt  # ← PŘIDEJ tento import nahoře v souboru!

def get_cookie_controller():
    if "cookie_controller" not in st.session_state:
        st.session_state.cookie_controller = CookieController()
    return st.session_state.cookie_controller
COOKIE_NAME = "planner_user_session_v3"


def authenticate_user(username: str, password: str):
    username = username.strip()
    st.write(f"Přihlašuji **{username}**")

    try:
        response = supabase.table('app_users')\
                   .select("username, name, role, password_hash")\
                   .eq("username", username)\
                   .execute()

        if not response.data:
            st.error("Uživatel nenalezen.")
            return None

        user = response.data[0]
        stored_hash = user['password_hash'].encode('utf-8')  # bcrypt chce bytes
        input_password = password.encode('utf-8')

        if bcrypt.checkpw(input_password, stored_hash):
            return {
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
        cc = get_cookie_controller()  # ← Nahrazeno zde
        cc.set(COOKIE_NAME, user_data['username'], max_age=60*60*24*90)
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
    cc = get_cookie_controller()  # ← Nahrazeno zde
    cc.set(COOKIE_NAME, "", max_age=0)
    for key in ["username", "name", "role", "authentication_status"]:
        st.session_state.pop(key, None)
    st.success("Odhlášeno.")
    time.sleep(0.5)
    st.rerun()

def check_login():
    cc = get_cookie_controller()  # ← Nahrazeno zde
    stored_username = cc.get(COOKIE_NAME)
    if stored_username:
        if "username" not in st.session_state:
            try:
                response = supabase.table('app_users')\
                           .select("username, name, role")\
                           .eq("username", stored_username)\
                           .execute()
                if response.data:
                    user = response.data[0]
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