# pages/5_HMG_roční.py
import streamlit as st
from datetime import datetime, timedelta, date
import pandas as pd
import plotly.express as px
from utils.common import *  # ← všechno ostatní (get_workplaces, is_working_day atd.)

authenticator = get_authenticator()  # ← čerstvý autentizátor

# Kontrola přihlášení
if not st.session_state.get('authentication_status'):
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data
username = st.session_state.get('username')
name = st.session_state.get('name')
role = st.session_state.get('role', 'viewer')
read_only = (role == 'viewer')  # zde není potřeba, ale pro konzistenci OK

# Sidebar
render_sidebar(authenticator, role, "HMG roční")

st.header("HMG roční – Heatmap obsazenosti pracovišť")

year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="year_rocni")

MONTH_CAPACITY = 200.0

workplaces = get_workplaces()
if not workplaces:
    st.info("Žádná pracoviště v databázi.")
    st.stop()

months = ['Led', 'Úno', 'Bře', 'Dub', 'Kvě', 'Čer', 'Čvc', 'Srp', 'Zář', 'Říj', 'Lis', 'Pro']
month_order = {m: i for i, m in enumerate(months)}

occupancy = {wp_name: [0.0 for _ in range(12)] for _, wp_name in workplaces}

try:
    response = supabase.table('tasks')\
               .select('id, workplace_id, hours, capacity_mode, start_date, end_date, status')\
               .not_.is_('start_date', 'null')\
               .not_.is_('end_date', 'null')\
               .execute()
    tasks = response.data
except Exception as e:
    st.error(f"Chyba při načítání úkolů z databáze: {e}")
    tasks = []

for t in tasks:
    if t['status'] == 'canceled':
        continue

    wp_id = t['workplace_id']
    total_hours = t['hours']
    mode = t['capacity_mode']
    start_str = t['start_date']
    end_str = t['end_date']

    wp_name = get_workplace_name(wp_id)
    if wp_name not in occupancy:
        continue

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        st.warning(f"Neplatné datum u úkolu ID {t['id']} – přeskočeno.")
        continue

    if end_date.year < year or start_date.year > year:
        continue

    current = max(start_date, date(year, 1, 1))
    end_in_year = min(end_date, date(year, 12, 31))

    working_days = 0
    while current <= end_in_year:
        if is_working_day(current, mode):
            working_days += 1
        current += timedelta(days=1)

    if working_days == 0:
        continue

    hours_per_day = total_hours / working_days

    current = max(start_date, date(year, 1, 1))
    while current <= end_in_year:
        if is_working_day(current, mode):
            month_idx = current.month - 1
            occupancy[wp_name][month_idx] += hours_per_day
        current += timedelta(days=1)

data = []
for wp_name, occ in occupancy.items():
    for m_idx, occ_hours in enumerate(occ):
        percent = round((occ_hours / MONTH_CAPACITY) * 100, 1)
        data.append({
            "Pracoviště": wp_name,
            "Měsíc": months[m_idx],
            "Hodiny": round(occ_hours, 1),
            "% využití": percent
        })

if not data:
    st.info(f"Žádné úkoly pro rok {year}.")
else:
    df = pd.DataFrame(data)
    df['Měsíc_order'] = df['Měsíc'].map(month_order)
    df = df.sort_values(['Pracoviště', 'Měsíc_order'])

    pivot_df = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
    pivot_df = pivot_df[months]  # zajistí správné pořadí měsíců

    fig = px.imshow(
        pivot_df,
        labels=dict(color="% využití"),
        title=f"Obsazenost pracovišť {year}",
        color_continuous_scale=["#90EE90", "#FFFF99", "#FFB366", "#FF6B6B"],
        zmin=0,
        zmax=120
    )

    fig.update_layout(
        height=400 + len(workplaces) * 35,
        coloraxis_colorbar=dict(
            title="% využití",
            tickvals=[0, 50, 80, 100, 120],
            ticktext=["0%", "50%", "80%", "100%", ">100%"]
        )
    )

    st.plotly_chart(fig, width='stretch')

    st.subheader("Detailní přehled (hodiny / %)")

    hours_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="Hodiny")
    hours_pivot = hours_pivot[months]

    percent_pivot = df.pivot(index="Pracoviště", columns="Měsíc", values="% využití")
    percent_pivot = percent_pivot[months]

    combined = pd.concat([hours_pivot, percent_pivot], axis=1, keys=["Hodiny", "% využití"])

    # Správné sloupce v pořadí
    combined_columns = []
    for month in months:
        if ("Hodiny", month) in combined.columns:
            combined_columns.append(("Hodiny", month))
        if ("% využití", month) in combined.columns:
            combined_columns.append(("% využití", month))

    combined = combined[combined_columns]

    st.dataframe(combined, width='stretch')