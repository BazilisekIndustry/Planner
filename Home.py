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
if st.session_state.get('authentication_status'):
    # Force uložení stavu + role (proti ztrátě při switch_page)
    st.session_state.authentication_status = True
    
    # Načti roli hned (pro jistotu)
    username = st.session_state.get('username')
    if username and 'role' not in st.session_state:
        try:
            response = supabase.table('app_users').select('role').eq('username', username).execute()
            if response.data:
                st.session_state['role'] = response.data[0]['role']
        except:
            st.session_state['role'] = 'viewer'
    
    st.success("Přihlášeno! Přesměrovávám...")
    st.switch_page("pages/2_add_project.py")

elif st.session_state.authentication_status is False:
    st.error("Nesprávné přihlašovací údaje. Zkuste znovu.")