# pages/4_HMG_month.py
import streamlit as st
from datetime import datetime, timedelta, date
import calendar
import pandas as pd
import plotly.express as px
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch
from utils.auth_simple import check_login
from utils.common import *
from collections import defaultdict

# Registrace fontu pro diakritiku v PDF
try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    pdf_font = 'DejaVu'
except Exception:
    st.warning("Font DejaVuSans.ttf nebyl nalezen – diakritika v PDF nemusí fungovat správně.")
    pdf_font = 'Helvetica'

# Kontrola přihlášení
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")

render_sidebar("HMG měsíční")

st.header("HMG měsíční – Přehled úkolů po dnech")

# Výběr měsíce a roku
selected_year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="hmg_year")
selected_month = st.number_input("Měsíc", min_value=1, max_value=12, value=datetime.now().month, key="hmg_month")

# Výpočet prvního a posledního dne měsíce
first_day = date(selected_year, selected_month, 1)
last_day = date(selected_year, selected_month + 1, 1) - timedelta(days=1) if selected_month < 12 else date(selected_year + 1, 1, 1) - timedelta(days=1)
num_days = last_day.day

# Načtení projektů
projects = {pid: {'name': name, 'color': color} for pid, name, color in get_projects()}

# Načtení úkolů pro měsíc
response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
all_tasks = [t for t in response.data if t.get('status') != 'canceled']

tasks_in_month = []
workplaces_set = set()
for t in all_tasks:
    s = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
    e = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
    if e < first_day or s > last_day:
        continue
    tasks_in_month.append(t)
    workplaces_set.add(get_workplace_name(t['workplace_id']))

# Detekce kolizí
collisions = detect_collisions_in_month(tasks_in_month)

# Definice funkce pro overlaps
def overlaps(t1, t2):
    s1 = datetime.strptime(t1['start_date'], '%Y-%m-%d').date()
    e1 = datetime.strptime(t1['end_date'], '%Y-%m-%d').date()
    s2 = datetime.strptime(t2['start_date'], '%Y-%m-%d').date()
    e2 = datetime.strptime(t2['end_date'], '%Y-%m-%d').date()
    return max(s1, s2) <= min(e1, e2)

# Ses kupení úkolů podle pracoviště
tasks_by_wp = defaultdict(list)
for t in tasks_in_month:
    wp = get_workplace_name(t['workplace_id'])
    tasks_by_wp[wp].append(t)

# Příprava dat pro graf
plot_data = []
total_rows = 0
y_categories = []
wp_lanes = {}

for wp in sorted(tasks_by_wp.keys()):
    wp_tasks = tasks_by_wp[wp]
    if len(wp_tasks) == 0:
        continue

    # Seřazení podle start date
    wp_tasks.sort(key=lambda t: datetime.strptime(t['start_date'], '%Y-%m-%d'))

    lanes = []
    for t in wp_tasks:
        assigned = False
        for lane in lanes:
            if all(not overlaps(t, ex) for ex in lane):
                lane.append(t)
                assigned = True
                break
        if not assigned:
            lanes.append([t])

    num_lanes = len(lanes)
    wp_lanes[wp] = num_lanes
    total_rows += num_lanes

    task_to_lane = {}
    for lane_idx, lane_tasks in enumerate(lanes):
        for t in lane_tasks:
            task_to_lane[t['id']] = lane_idx

        if num_lanes == 1:
            y_prac = wp
        else:
            y_prac = f"{wp} - Lane {lane_idx + 1}"
        y_categories.append(y_prac)

    for t in wp_tasks:
        lane_idx = task_to_lane[t['id']]
        if num_lanes == 1:
            y_prac = wp
        else:
            y_prac = f"{wp} - Lane {lane_idx + 1}"

        pid = t['project_id']
        start_date = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
        proj = projects.get(pid, {'name': f'P{pid}', 'color': '#4285F4'})
        task_text = proj['name']  # základní název
        original_color = proj['color']
        display_color = original_color
        text_color = '#000000'

        # Pokud je kolize, přidáme vykřičník k názvu
        colliding = collisions.get(t['id'], [])
        if colliding:
            task_text += " !"
            display_color = "#EA4335"  # červená pro kolizi
            text_color = '#FFFFFF'

        # Tooltip s opravenými daty – správný název projektu, termíny
        coll_str = []
        if colliding:
            for i, coll_id in enumerate(colliding):
                if i >= 3:
                    coll_str.append("...a další")
                    break
                coll_task = get_task(coll_id)
                if coll_task and coll_task['id'] != t['id']:
                    coll_pid = coll_task['project_id']
                    coll_name = projects.get(coll_pid, {'name': f'P{coll_pid}'})['name']
                    coll_str.append(coll_name)

            # Zkontrolujeme, jestli je mezi kolizemi jiný projekt
            has_cross_project_collision = any(
                get_task(coll_id)['project_id'] != pid for coll_id in colliding
            )
            if has_cross_project_collision:
                task_text += " !"                

        tooltip = (
        f"<b>{proj['name']}</b><br>"
        f"Projektová barva: <span style='color:{original_color}; font-weight:bold'>■ {original_color}</span><br>"
        f"Od: {start_date.strftime('%d.%m.%Y')}<br>"
        f"Do: {end_date.strftime('%d.%m.%Y') if end_date else 'není definován'}"
        )
        if coll_str:
            tooltip += f"<br><b>Kolize s:</b> {', '.join(coll_str)}"

        plot_data.append({
            "Pracoviště": y_prac,
            "Úkol": task_text,
            "Start": max(start_date, first_day),
            "Finish": min(end_date, last_day) + timedelta(days=1),
            "Color": display_color,
            "TextColor": text_color,
            "FullTooltip": tooltip,        # ← NOVÉ
            "TaskID": t['id']              # ← pro případný debug
        })

if not plot_data:
    st.info(f"Žádné úkoly v {calendar.month_name[selected_month]} {selected_year}.")
else:
    df = pd.DataFrame(plot_data)
    color_map = {c: c for c in df["Color"].unique()}
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Pracoviště",
        color="Color",
        text="Úkol",
        hover_name=None,                    # vypneme výchozí
        color_discrete_map=color_map,
        title=f"HMG HK – {calendar.month_name[selected_month]} {selected_year}",
        height=400 + total_rows * 40,
        custom_data=["FullTooltip"]         # ← DŮLEŽITÉ
    )
    fig.update_traces(
        opacity=0.7,
        textposition='inside',
        textfont_color=df["TextColor"].tolist(),
        hovertemplate="%{customdata[0]}",   # ← DŮLEŽITÉ – bere plný tooltip
        hoverlabel=dict(bgcolor="white", font_size=12)
    )
    fig.update_xaxes(
        tickformat="%d",
        tickmode="linear",
        dtick=86400000.0,
        range=[first_day, last_day + timedelta(days=1)]
    )
    fig.update_yaxes(autorange="reversed", categoryorder='array', categoryarray=y_categories)
    fig.update_layout(bargap=0.2, bargroupgap=0.1, showlegend=False)

    # Víkendy a svátky – červené dashed vline
    holidays = get_holidays(selected_year)
    current = first_day
    epoch = date(1970, 1, 1)  # referenční bod, který Plotly interně používá

    while current <= last_day:
        if is_weekend_or_holiday(current):
            label = "S" if current in holidays else "V"
            
            # Klíč: počet dní od 1970-01-01
            x_num = (current - epoch).days
            
            fig.add_vline(
                x=x_num,                    # ← čisté číslo, žádný date, žádný string
                line_dash="dash",
                line_color="red",
                line_width=1.2,
                opacity=0.6,
                annotation_text=label,
                annotation_position="top",
                annotation_font_size=10,
                annotation_font_color="red"
            )
        
        current += timedelta(days=1)

    st.plotly_chart(fig, use_container_width=True)

    # Export do PDF
    if st.button("Exportovat HMG měsíční do PDF"):
        file_name = f"HMG_mesicni_{selected_year}_{selected_month:02d}.pdf"
        pdf = pdf_canvas.Canvas(file_name, pagesize=landscape(A4))
        width, height = landscape(A4)

        pdf.setFont(pdf_font, 16)
        pdf.drawCentredString(width / 2, height - 0.8 * inch, f"HMG HK – {calendar.month_name[selected_month]} {selected_year}")

        left_margin = 1.0 * inch
        wp_col_width = 2.0 * inch
        day_col_width = (width - left_margin - wp_col_width - 0.8 * inch) / num_days
        header_y = height - 1.5 * inch
        row_height = (height - 2.5 * inch) / total_rows if total_rows > 0 else 40

        pdf.setFont(pdf_font, 10)
        for d in range(1, num_days + 1):
            current_date = date(selected_year, selected_month, d)
            x = left_margin + wp_col_width + (d - 1) * day_col_width
            fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
            pdf.setFillColorRGB(*fill_color)
            pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))

        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)

        sorted_workplaces = sorted(tasks_by_wp.keys())

        colors_rgb = {}
        for pid, proj in projects.items():
            hex_color = proj['color']
            r = int(hex_color[1:3], 16) / 255
            g = int(hex_color[3:5], 16) / 255
            b = int(hex_color[5:7], 16) / 255
            colors_rgb[hex_color] = (r, g, b)
        colors_rgb["#34A853"] = (0.20, 0.66, 0.32)
        colors_rgb["#EA4335"] = (0.92, 0.26, 0.21)

        pdf_data = []
        for wp in sorted_workplaces:
            wp_tasks = tasks_by_wp[wp]
            lanes = wp_lanes[wp]
            task_to_lane = {}
            # Rekonstrukce lanes pro pdf_data
            lanes_list = [[] for _ in range(lanes)]
            for t in wp_tasks:
                # Znovu vypočítat lane pro konzistenci
                assigned = False
                for lane_idx, lane in enumerate(lanes_list):
                    if all(not overlaps(t, ex) for ex in lane):
                        lanes_list[lane_idx].append(t)
                        task_to_lane[t['id']] = lane_idx
                        assigned = True
                        break
                if not assigned:
                    # To by nemělo nastat
                    pass

            for t in wp_tasks:
                lane_idx = task_to_lane[t['id']]
                start_date = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
                start_day = (max(start_date, first_day) - first_day).days + 1
                end_day = (min(end_date, last_day) - first_day).days + 1
                proj = projects.get(t['project_id'], {'name': f'P{t["project_id"]}', 'color': '#4285F4'})
                task_text = proj['name']

                colliding = collisions.get(t['id'], [])
                if colliding:
                    task_text += " !"
                    display_color = "#EA4335"
                    has_cross_project_collision = any(
                        get_task(coll_id)['project_id'] != t['project_id'] for coll_id in colliding
                    )
                    if has_cross_project_collision:
                        task_text += " !"
                else:
                    display_color = proj['color']

                pdf_data.append({
                    "wp_name": wp,
                    "lane": lane_idx,
                    "task_text": task_text,
                    "start_day": start_day,
                    "end_day": end_day,
                    "color": display_color
                })

        current_row = 0
        for wp_name in sorted_workplaces:
            num_lanes = wp_lanes[wp_name]
            for sub in range(num_lanes):
                y_top = header_y - 20 - current_row * row_height
                y_bottom = y_top - row_height

                pdf.setFillColorRGB(0, 0, 0)
                pdf.setFont(pdf_font, 9)
                if sub == 0:
                    pdf.drawString(left_margin, y_top - row_height / 2 - 3, wp_name)

                pdf.line(left_margin, y_bottom, width - 0.8 * inch, y_bottom)

                for item in pdf_data:
                    if item["wp_name"] != wp_name or item["lane"] != sub:
                        continue
                    x1 = left_margin + wp_col_width + (item["start_day"] - 1) * day_col_width
                    x2 = left_margin + wp_col_width + item["end_day"] * day_col_width
                    rgb = colors_rgb.get(item["color"], (0.26, 0.52, 0.96))
                    pdf.setFillColorRGB(*rgb)
                    pdf.rect(x1, y_bottom + 5, x2 - x1, row_height - 10, fill=1, stroke=1)

                    if item["color"] == "#EA4335":
                        pdf.setFillColorRGB(1, 1, 1)
                    else:
                        pdf.setFillColorRGB(0, 0, 0)
                    pdf.setFont(pdf_font, 8)
                    pdf.drawCentredString((x1 + x2) / 2, y_bottom + row_height / 2 - 4, item["task_text"])

                current_row += 1

        pdf.save()

        with open(file_name, "rb") as f:
            st.download_button(
                label="Stáhnout PDF s HMG",
                data=f.read(),
                file_name=file_name,
                mime="application/pdf"
            )