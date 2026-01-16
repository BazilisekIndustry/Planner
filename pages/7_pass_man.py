# pages/7_Změnit_heslo.py
import streamlit as st
from utils.common import *  # ← všechno (change_password atd.)
from utils.auth_simple import check_login, logout

# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")

render_sidebar("Změnit heslo")

st.header("Změnit heslo")

st.info("Zadejte nové heslo. Doporučujeme délku minimálně 8 znaků s kombinací písmen, číslic a symbolů.")

new_password = st.text_input("Nové heslo", type="password", key="new_pw")
confirm_password = st.text_input("Potvrďte nové heslo", type="password", key="confirm_pw")

# Volitelně: jednoduchá kontrola síly hesla
if new_password and len(new_password) < 6:
    st.warning("Heslo je příliš krátké (doporučujeme minimálně 6 znaků).")

if st.button("Změnit heslo", type="primary"):
    if not new_password.strip():
        st.error("Heslo nesmí být prázdné.")
    elif new_password != confirm_password:
        st.error("Hesla se neshodují – zkontrolujte a zkuste znovu.")
    elif len(new_password) < 6:
        st.error("Heslo musí mít minimálně 6 znaků.")
    else:
        try:
            success, message = change_password(username, new_password.strip())
            if success:
                st.success(message + " Nyní se prosím odhlašte a přihlaste znovu s novým heslem.")
            else:
                st.error(message or "Chyba při změně hesla – zkuste to znovu.")
        except Exception as e:
            st.error(f"Neočekávaná chyba při změně hesla: {e}")