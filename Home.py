# Home.py
import streamlit as st
from utils.common import get_authenticator

st.set_page_config(
    page_title="Plánovač Horkých komor CVŘ – Přihlášení",
    page_icon=":radioactive:",
    layout="wide"
)

st.title("Plánovač Horkých komor CVŘ")

# Vytvoř autentizátor
authenticator = get_authenticator()

# Force zobrazení loginu (pokud zmizí)
st.markdown(
    """
    Vítejte v Plánovači Horkých komor CVŘ v2.\n\n
    Přihlaste se prosím.\n\n
    Pro založení nového uživatele kontaktujte petr.svrcula@cvrez.cz.
    """
)

# Login – volá se vždy
authenticator.login(location='main', fields={
    'Form name': 'Přihlášení',
    'Username': 'Uživatelské jméno',
    'Password': 'Heslo',
    'Login': 'Přihlásit se'
})

# Explicitní kontrola stavu (pokud formulář zmizí)
if 'authentication_status' not in st.session_state:
    st.session_state.authentication_status = None

if st.session_state.authentication_status is None:
    st.info("Přihlašovací formulář by se měl zobrazit výše. Pokud ne, zkuste refresh (F5) nebo otevřít v anonymním okně.")

if st.session_state.get('authentication_status'):
    st.success("Přihlášeno! Přesměrovávám...")
    st.switch_page("pages/2_add_project.py")

elif st.session_state.authentication_status is False:
    st.error("Nesprávné přihlašovací údaje. Zkuste znovu.")