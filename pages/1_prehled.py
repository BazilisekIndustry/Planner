# pages/1_overview.py  # Nebo jakýkoli název, který pasuje do tvé multipage struktury
import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
from plotly import graph_objects as go  # Pro gauge ukazatel
import plotly.express as px  # Pro heatmap
from utils.auth_simple import check_login  # Předpokládám tvůj auth
from utils.common import *  # Tvé funkce: supabase, get_workplaces, get_tasks, get_workplace_name, get_holidays, atd.

# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")
render_sidebar("Přehledový dashboard")

# Hlavní obsah
st.header("Přehledový dashboard")

# Aktuální datum a čas (lokalizováno pro CZ)
now = datetime.now()
current_date_str = now.strftime("%d.%m.%Y")
current_time_str = now.strftime("%H:%M")  # Jen hodiny:minuty
st.markdown(f"**Aktuální datum:** {current_date_str} | **Čas:** {current_time_str}")

# Načtení dat pro tabulku
current_date = now.date()  # Pouze date pro porovnání

# Získej všechna pracoviště
workplaces = get_workplaces()  # [(id, name)]

# Získej všechny aktivní úkoly (ne canceled, s daty)
tasks = []
response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').neq('status', 'canceled').execute()
for t in response.data:
    start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
    if start <= current_date <= end:
        t['wp_name'] = get_workplace_name(t['workplace_id'])
        t['proj_name'] = get_project_choices(t['project_id'])  # Předpokládám funkci get_project_name(pid) – pokud ne, přidej ji podobně jako get_workplace_name
        tasks.append(t)

# Pokud žádný úkol, info
if not tasks:
    st.info("Žádné probíhající úkoly dnes.")
else:
    # Data pro tabulku
    data = []
    for t in tasks:
        data.append({
            "Pracoviště": t['wp_name'],
            "Projekt": t['proj_name'] or f"P{t['project_id']}",
            "Úkol ID": t['id'],
            "Hodiny": t['hours'],
            "Režim": t['capacity_mode'],
            "Poznámka": t['notes'][:50] + "..." if t['notes'] else "",
            "Kolize": "Ano" if check_collisions(t['id']) else "Ne"
        })

    df = pd.DataFrame(data)

    # Tabulka
    col1, col2 = st.columns([2, 1])  # Levý širší pro tabulku, pravý pro gauge
    with col1:
        st.subheader("Probíhající úkoly na pracovištích")
        AgGrid(
            df,
            height=300,
            editable=False,
            fit_columns_on_grid_load=True,
            theme="streamlit"
        )

    # Analogový ukazatel využití (Plotly Gauge – vypadá jako tachometr)
    with col2:
        st.subheader("Celkové využití komor")

        # Výpočet celkového využití (např. procento obsazených pracovišť)
        total_wp = len(workplaces)
        busy_wp = len(set(t['workplace_id'] for t in tasks))  # Počet obsazených pracovišť
        utilization = (busy_wp / total_wp) * 100 if total_wp > 0 else 0

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=utilization,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Využití (%)"},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': "darkblue"},
                'steps': [
                    {'range': [0, 50], 'color': "lightgreen"},
                    {'range': [50, 80], 'color': "yellow"},
                    {'range': [80, 100], 'color': "red"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 90
                }
            }
        ))

        fig.update_layout(height=250, margin={'l': 20, 'r': 20, 't': 50, 'b': 20})
        st.plotly_chart(fig, use_container_width=True)

# Nové: Nejvytíženější pracoviště na příštích 14 dní
st.subheader("Nejvytíženější pracoviště na příštích 14 dní")

start_date = current_date + timedelta(days=1)
end_date = current_date + timedelta(days=14)

# Všechny úkoly v období
future_tasks = []
for t in response.data:  # Použijeme všechny tasks z předchozího query
    start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
    if end >= start_date and start <= end_date:
        future_tasks.append(t)

# Výpočet zatížení po pracovištích (např. počet hodin nebo počet úkolů)
from collections import defaultdict
wp_load = defaultdict(float)  # Pracoviště ID → celkové hodiny

for t in future_tasks:
    wp_id = t['workplace_id']
    wp_load[wp_id] += t['hours']

# Seřadíme sestupně a vybereme top 5 (nebo všechny)
top_wp = sorted(wp_load.items(), key=lambda x: x[1], reverse=True)[:5]

if not top_wp:
    st.info("Žádná zatížení na příštích 14 dní.")
else:
    top_data = []
    for wp_id, hours in top_wp:
        top_data.append({
            "Pracoviště": get_workplace_name(wp_id),
            "Celkové hodiny": round(hours, 1),
            "Počet úkolů": sum(1 for t in future_tasks if t['workplace_id'] == wp_id)
        })
    
    top_df = pd.DataFrame(top_data)
    st.dataframe(top_df, use_container_width=True)

# Nové: Tlačítko pro heatmap prognózy na 30/90 dní
if st.button("Zobrazit prognózu zatížení na 30/90 dní"):
    st.subheader("Prognóza zatížení pracovišť (heatmap)")

    # Výpočet pro příštích 30 a 90 dní (podobně jako v HMG roční, ale pro budoucnost)
    forecast_periods = [30, 90]
    for days in forecast_periods:
        st.markdown(f"### Na příštích {days} dní")

        end_forecast = current_date + timedelta(days=days)
        occupancy = {wp_name: 0.0 for _, wp_name in workplaces}  # Inicializace

        forecast_tasks = []
        for t in response.data:
            start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
            end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            if end >= current_date and start <= end_forecast:
                forecast_tasks.append(t)

        total_days = days
        for t in forecast_tasks:
            wp_name = get_workplace_name(t['workplace_id'])
            if wp_name in occupancy:
                # Přibližný výpočet: hodiny / celkové dny (můžeš upravit na pracovní dny)
                occupancy[wp_name] += t['hours'] / total_days  # Průměrná denní zátěž

        # Data pro heatmap
        heatmap_data = pd.DataFrame({
            "Pracoviště": list(occupancy.keys()),
            "Průměrná denní zátěž (hodiny)": list(occupancy.values())
        })

        fig = px.imshow(
            heatmap_data.set_index("Pracoviště"),
            color_continuous_scale="YlOrRd",  # Žlutá-oranžová-červená
            title=f"Prognóza na {days} dní",
            aspect="auto"
        )
        fig.update_layout(height=300 + len(workplaces) * 20)
        st.plotly_chart(fig, use_container_width=True)