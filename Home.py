# Home.py
import streamlit as st
from utils.common import get_authenticator  # ← NOVÝ IMPORT: funkce z common.py
# from utils.common import load_users_from_db  # pokud potřebuješ, ale není nutné

st.set_page_config(
    page_title="Plánovač Horkých komor CVŘ – Přihlášení",
    page_icon=":radioactive:",
    layout="wide"
)

st.title("Plánovač Horkých komor CVŘ")

# Vytvoř autentizátor z nové funkce (čerstvé credentials)
authenticator = get_authenticator()

st.markdown(
    "Vítejte v Plánovači Horkých komor CVŘ v2.\n\n"
    "Přihlaste se prosím.\n\n"
    "Pro založení nového uživatele kontaktujte petr.svrcula@cvrez.cz."
)

if st.session_state.get('authentication_status'):
    # Force uložení cookie a role
    st.session_state['authentication_status'] = True
    if 'role' not in st.session_state:
        # Načti roli hned
        try:
            response = supabase.table('app_users').select('role').eq('username', st.session_state.get('username')).execute()
            if response.data:
                st.session_state['role'] = response.data[0]['role']
        except:
            st.session_state['role'] = 'viewer'
    
    st.success("Přihlášeno! Přesměrovávám...")
    st.switch_page("pages/2_add_project.py")

elif st.session_state.authentication_status is False:
    st.error("**Nesprávné přihlašovací údaje.** Zkuste to prosím znovu. Pokud problém přetrvává, zkuste vymazat cookies v prohlížeči.")

elif st.session_state.authentication_status is None:
    st.warning("Přihlaste se prosím. Pokud jste již přihlášeni, zkuste refresh stránky (F5) nebo vymazat cookies.")