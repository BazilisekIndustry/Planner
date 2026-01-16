# Home.py
import streamlit as st
from utils.auth_simple import login, check_login
from streamlit_authenticator.utilities.hasher import Hasher
from utils.common import supabase

st.set_page_config(page_title="Plánovač – Přihlášení", layout="wide")
# Na konec Home.py (před login formulářem)

if check_login():
    st.success("Již přihlášen – přesměrovávám...")
    st.switch_page("pages/2_add_project.py")
else:
    st.title("Přihlášení do Plánovače Horkých komor")
    st.markdown("Vítejte! Přihlaste se prosím.")

    with st.form("login_form"):
        username = st.text_input("Uživatelské jméno")
        password = st.text_input("Heslo", type="password")
        submitted = st.form_submit_button("Přihlásit se")

        if submitted:
            login(username, password)