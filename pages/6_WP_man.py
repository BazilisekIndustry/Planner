# pages/6_Správa_pracovišť.py
import streamlit as st
from utils.common import *  # ← všechno (add_workplace, delete_workplace, get_workplaces atd.)

from utils.auth_simple import check_login, logout
st.set_page_config(page_title="Plánovač HK", layout="wide")
# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")

render_sidebar("Správa pracovišť")

# Hlavní obsah – jen pro adminy
if role != 'admin':
    st.error("Přístup jen pro administrátory.")
else:
    st.header("Správa pracovišť")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Přidat pracoviště")
        new_wp_name = st.text_input("Název nového pracoviště", key="new_wp_name_input")
        
        if st.button("Přidat pracoviště", type="primary"):
            cleaned_name = new_wp_name.strip()
            if cleaned_name:
                try:
                    if add_workplace(cleaned_name):
                        st.success(f"Pracoviště **{cleaned_name}** úspěšně přidáno!")
                        st.rerun()
                    else:
                        st.error("Pracoviště s tímto názvem již existuje.")
                except Exception as e:
                    st.error(f"Chyba při přidávání pracoviště: {e}")
            else:
                st.error("Zadejte platný název (alespoň jedno písmeno).")

    with col2:
        st.subheader("Existující pracoviště")
        workplaces = get_workplaces()
        
        if not workplaces:
            st.info("Zatím žádné pracoviště v databázi.")
        else:
            for wp_id, wp_name in workplaces:
                c1, c2 = st.columns([4, 1])
                c1.write(wp_name)
                
                if c2.button("Smazat", key=f"del_{wp_id}", type="primary"):
                    # Potvrzení mazání – lepší UX
                    if st.session_state.get(f"confirm_delete_{wp_id}", False):
                        try:
                            if delete_workplace(wp_id):
                                st.success(f"Pracoviště **{wp_name}** bylo smazáno.")
                                # Vyčistit potvrzení
                                if f"confirm_delete_{wp_id}" in st.session_state:
                                    del st.session_state[f"confirm_delete_{wp_id}"]
                                st.rerun()
                            else:
                                st.error("Pracoviště nelze smazat – je použito v nějakém úkolu.")
                        except Exception as e:
                            st.error(f"Chyba při mazání pracoviště: {e}")
                    else:
                        st.session_state[f"confirm_delete_{wp_id}"] = True
                        st.warning(f"Opravdu chcete smazat pracoviště **{wp_name}**? Klikněte znovu na Smazat pro potvrzení.")
                        st.rerun()