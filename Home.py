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
    "Vítejte v Plánovači Horkých komor CVŘ.\n\n"
    "Přihlaste se prosím.\n\n"
    "Pro založení nového uživatele kontaktujte petr.svrcula@cvrez.cz."
)

# Login – volá se vždy pro čtení cookies
authenticator.login(location='main')

if st.session_state.get('authentication_status'):
    st.success("Přihlášeno! Přesměrovávám na hlavní stránku...")
    st.switch_page("pages/2_Přidat_projekt_a_úkol.py")  # nebo na tvou první stránku

elif st.session_state.authentication_status is False:
    st.error("**Nesprávné přihlašovací údaje.** Zkuste to prosím znovu. Pokud problém přetrvává, zkuste vymazat cookies v prohlížeči.")

elif st.session_state.authentication_status is None:
    st.warning("Přihlaste se prosím. Pokud jste již přihlášeni, zkuste refresh stránky (F5) nebo vymazat cookies.")