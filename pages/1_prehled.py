# pages/1_overview.py  # Nebo jakýkoli název, který pasuje do tvé multipage struktury
import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
from plotly import graph_objects as go  # Pro gauge ukazatel
import plotly.express as px  # Pro heatmap
from utils.auth_simple import check_login  # Předpokládám tvůj auth
from utils.common import *  # Tvé funkce: supabase, get_workplaces, get_tasks, get_workplace_name, get_holidays, atd.
import time  # Pro aktualizaci času
from io import BytesIO  # Pro export Excel
from st_aggrid import AgGrid, GridOptionsBuilder  # Správný import po instalaci streamlit-aggrid
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
render_sidebar("Přehledový dashboard")
# Funkce pro aktualizaci času každou minutu
def update_time():
    now = datetime.now()
    current_date_str = now.strftime("%d.%m.%Y")
    current_time_str = now.strftime("%H:%M")
    return current_date_str, current_time_str
# Inicializace session_state pro timer
if 'last_update' not in st.session_state:
    st.session_state.last_update = time.time()
# Hlavní obsah
st.header("Přehledový dashboard")
# Aktuální datum a čas (lokalizováno pro CZ)
current_date_str, current_time_str = update_time()
st.markdown(f"**Aktuální datum:** {current_date_str} | **Čas:** {current_time_str}")
# Automatická aktualizace každých 60 sekund
current_time = time.time()
if current_time - st.session_state.last_update >= 60:
    st.session_state.last_update = current_time
    st.rerun()
# Načtení dat pro tabulku
current_date = datetime.now().date()  # Pouze date pro porovnání
# Získej všechna pracoviště
workplaces = get_workplaces()  # [(id, name)]
wp_names = [wp[1] for wp in workplaces]
wp_dict = {wp[1]: wp[0] for wp in workplaces}  # Pro filtr
# Získej všechny aktivní úkoly (ne canceled, s daty)
tasks = []
response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').neq('status', 'canceled').execute()
end_period = current_date + timedelta(days=7)  # Následujících 7 dní včetně dnes
for t in response.data:
    start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
    if end >= current_date and start <= end_period:  # Úkoly běžící dnes nebo končící později, ale start do 7 dnů
        t['wp_name'] = get_workplace_name(t['workplace_id'])
        t['proj_name'] = get_project_name(t['project_id'])  # Použití nové funkce
        tasks.append(t)
# Rozložení sloupců pro tabulku a gauge
col1, col2 = st.columns([2, 1])  # Levý širší pro tabulku, pravý pro gauge
# Tabulka úkolů (nezávisle na gauge)
with col1:
    if not tasks:
        st.info("Žádné probíhající nebo nadcházející úkoly v následujících 7 dnech.")
    else:
        # Data pro tabulku
        data = []
        for t in tasks:
            start_date = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            if start_date > current_date:
                status = f"Začíná {start_date.strftime('%d.%m.%Y')}"
            elif start_date <= current_date <= end_date:
                status = "Běží nyní"
                if end_date == current_date:
                    status += " (končí dnes)"
                elif end_date - current_date <= timedelta(days=1):
                    status += " (končí do 24h)"
                elif end_date - current_date <= timedelta(days=7):
                    status += f" (končí {end_date.strftime('%d.%m.%Y')})"
            else:
                status = ""  # Nemělo by se stát díky filtru
            data.append({
                "Pracoviště": t['wp_name'],
                "Projekt": t['proj_name'] or f"P{t['project_id']}",
                "Úkol ID": t['id'],
                "Start": t['start_date'],
                "End": t['end_date'],
                "Hodiny": t['hours'],
                "Režim": t['capacity_mode'],
                "Poznámka": t['notes'][:50] + "..." if t['notes'] else "",
                "Kolize": "Ano" if check_collisions(t['id']) else "Ne",
                "Status": status
            })
        df = pd.DataFrame(data)
        # Interaktivní filtr
        selected_wp = st.multiselect("Filtr pracovišť", options=wp_names, default=wp_names)
        if selected_wp:
            df = df[df['Pracoviště'].isin(selected_wp)]
        # Notifikace a alerty
        collisions = df[df['Kolize'] == 'Ano'].shape[0]
        if collisions > 0:
            st.warning(f"Detekováno {collisions} kolizí – zkontrolujte úkoly!")
        running_now = df[df['Status'].str.contains("Běží nyní", na=False)].shape[0]
        starting_soon = df[df['Status'].str.contains("Začíná", na=False)].shape[0]
        ending_today = df[df['Status'].str.contains("končí dnes", na=False)].shape[0]
        ending_soon = df[df['Status'].str.contains("končí do 24h", na=False)].shape[0]
        if running_now > 0 or starting_soon > 0 or ending_today > 0 or ending_soon > 0:
            st.info(f"Běžící nyní: {running_now} | Začínající brzy: {starting_soon} | Končící dnes: {ending_today} | Končící do 24h: {ending_soon}")
        # Tabulka s AgGrid a selection pro detail
        st.subheader("Probíhající a nadcházející úkoly (dnes + následujících 7 dní)")
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_selection('single', use_checkbox=True)
        grid_options = gb.build()
        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            height=300,
            editable=False,
            fit_columns_on_grid_load=True,
            theme="streamlit"
        )
        # Detailní view na klik (expander)
        selected_rows = grid_response.get('selected_rows', [])
        if isinstance(selected_rows, pd.DataFrame):
            selected_rows = selected_rows.to_dict('records')  # Převod na list dictů, pokud je to DataFrame
        if selected_rows:  # Teď je to vždy list
            selected_task_id = selected_rows[0]['Úkol ID']
            selected_task = next((t for t in tasks if t['id'] == selected_task_id), None)
            if selected_task:
                with st.expander(f"Detail úkolu ID: {selected_task_id}", expanded=True):
                    st.write(f"Pracoviště: {selected_task['wp_name']}")
                    st.write(f"Projekt: {selected_task['proj_name']}")
                    st.write(f"Start: {selected_task['start_date']}")
                    st.write(f"End: {selected_task['end_date']}")
                    st.write(f"Hodiny: {selected_task['hours']}")
                    st.write(f"Režim: {selected_task['capacity_mode']}")
                    st.write(f"Poznámka: {selected_task['notes']}")
                    # Přidej další detaily podle potřeby
        # Export dat (Excel)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:  # Pokud chceš změnit, nahraď na 'xlsxwriter'
            df.to_excel(writer, index=False, sheet_name='Úkoly dnes + 7 dní')
        output.seek(0)
        st.download_button(
            label="Exportovat jako Excel",
            data=output,
            file_name=f"ukoly_{current_date_str}_plus7.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
# Analogový ukazatel využití (Plotly Gauge – celkové do konce roku) – teď mimo else, aby se zobrazil vždy
with col2:
    st.subheader("Celkové využití komor do konce roku")
    
    # Definice konce roku
    now = datetime.now()
    end_of_year = datetime(now.year, 12, 31).date()
    days_to_eoy = (end_of_year - now.date()).days + 1  # Vč. dnes
    
    # Načtení svátků
    holidays_set = set(get_holidays(now.year))  # Pro aktuální rok
    
    # Počet dostupných pracovních dnů (zohlední svátky a víkendy)
    available_days = 0
    current_day = now.date()
    for _ in range(days_to_eoy):
        if is_working_day(current_day, mode='24'):  # Pro max kapacitu – vč. víkendů pokud mode=24 (nebo uprav na vždy True pro full 365)
            available_days += 1
        current_day += timedelta(days=1)
    
    # Celková dostupná kapacita: pracoviště * dny * 24 h/den
    total_wp = len(workplaces)
    max_hours_per_day = 24.0  # Max kapacita (uprav na 7.5 pokud chceš konzervativní)
    total_capacity = total_wp * available_days * max_hours_per_day
    
    # Celkové bookované hodiny: sum hours všech relevantních úkolů
    booked_hours = 0.0
    for t in response.data:  # Z předchozího query na všechny úkoly
        if t['status'] != 'canceled' and t['start_date'] and t['end_date']:
            end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            if end >= now.date():
                booked_hours += t['hours']
    
    # Procento využití
    utilization = (booked_hours / total_capacity) * 100 if total_capacity > 0 else 0
    
    # Gauge fig (beze změny)
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
    # Načtení svátků pro aktuální rok (a případně sousední, ale get_holidays vrací jen pro year)
    now = datetime.now()
    holidays_set = set(get_holidays(now.year))
    if now.month == 12:
        holidays_set.update(get_holidays(now.year + 1))
    elif now.month == 1:
        holidays_set.update(get_holidays(now.year - 1))
    
    # Funkce pro počet pracovních dnů (už máš v common.py, ale pro úplnost)
    def count_workdays(start, days):
        count = 0
        for d in range(days):
            day = start + timedelta(days=d)
            if day.weekday() < 5 and day not in holidays_set:  # Pondělí-Pátek, ne svátek
                count += 1
        return count
    
    forecast_periods = [30, 90]
    for days in forecast_periods:
        st.markdown(f"### Na příštích {days} dní")
        start_forecast = current_date + timedelta(days=1)
        end_forecast = current_date + timedelta(days=days)
        
        # Svátky v období
        holidays_in_period = sum(1 for d in range(days) if (start_forecast + timedelta(days=d)) in holidays_set)
        
        # Všechny úkoly v období (přesný overlap)
        forecast_tasks = []
        for t in response.data:  # Použijeme všechny tasks z předchozího query
            if t['status'] == 'canceled' or not t['start_date'] or not t['end_date']:
                continue
            start = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
            end = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            if end >= start_forecast and start <= end_forecast:
                forecast_tasks.append(t)
        
        # Celkové pracovní dny v období
        total_workdays = count_workdays(start_forecast, days)
        if total_workdays == 0:
            total_workdays = 1  # Aby nedošlo k dělení nulou
        
        # Výpočet průměrné denní zátěže po pracovištích (v %)
        from collections import defaultdict
        occupancy = defaultdict(float)  # wp_name → součet daily_load_pct přes úkoly
        
        for t in forecast_tasks:
            wp_name = get_workplace_name(t['workplace_id'])
            start_t = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
            end_t = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
            
            # Overlap s prognózou
            overlap_start = max(start_t, start_forecast)
            overlap_end = min(end_t, end_forecast)
            if overlap_start > overlap_end:
                continue  # Žádný overlap
            
            overlap_days = (overlap_end - overlap_start).days + 1
            overlap_workdays = 0
            current_day = overlap_start
            for _ in range(overlap_days):
                if is_working_day(current_day, t['capacity_mode']):  # Zohlední mode (7.5 nebo 24)
                    overlap_workdays += 1
                current_day += timedelta(days=1)
            
            if overlap_workdays > 0:
                # Předpoklad rovnoměrného rozložení hodin v úkolu
                total_task_days = (end_t - start_t).days + 1
                daily_load = t['hours'] / total_task_days
                # Max kapacita podle mode
                max_capacity = 7.5 if t['capacity_mode'] == '7.5' else 24.0
                # Procentuální příspěvek: (daily_load / max_capacity) * 100
                daily_load_pct = (daily_load / max_capacity) * 100
                # Přidat vážený příspěvek: (overlap_workdays / total_workdays)
                occupancy[wp_name] += daily_load_pct * (overlap_workdays / total_workdays)
        
        if not occupancy:
            st.info("Žádná zatížení v tomto období.")
            continue
        
        # Data pro heatmap (seřazené sestupně podle zátěže)
        heatmap_data = pd.DataFrame({
            "Pracoviště": list(occupancy.keys()),
            "Průměrná denní zátěž (%)": list(occupancy.values())
        }).sort_values(by="Průměrná denní zátěž (%)", ascending=False)
        
        fig = px.imshow(
            heatmap_data.set_index("Pracoviště"),
            color_continuous_scale="YlOrRd",  # Žlutá-oranžová-červená
            title=f"Prognóza na {days} dní (zohledněno {holidays_in_period} svátků)",
            aspect="auto",
            zmin=0,  # Fix škály pro %
            zmax=100  # Max 100%
        )
        fig.update_layout(height=300 + len(workplaces) * 20)
        st.plotly_chart(fig, use_container_width=True)