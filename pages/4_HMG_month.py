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

# Příprava dat pro graf
plot_data = []
for t in tasks_in_month:
    pid = t['project_id']
    start_date = datetime.strptime(t['start_date'], '%Y-%m-%d').date()
    end_date = datetime.strptime(t['end_date'], '%Y-%m-%d').date()
    proj = projects.get(pid, {'name': f'P{pid}', 'color': '#4285F4'})
    task_text = proj['name']
    original_color = proj['color']  # ← původní barva projektu
    display_color = original_color
    text_color = '#000000'

    # Priorita barev
    status_text = ""
    if t.get('status') == 'done':
        display_color = "#34A853"  # zelená pro hotovo
        status_text = " (hotovo)"
    elif collisions.get(t['id'], []):
        display_color = "#EA4335"  # červená pro kolizi
        text_color = '#FFFFFF'

    # Tooltip s původní barvou projektu + stavem
    coll_str = []
    colliding = collisions.get(t['id'], [])
    if colliding:
        for i, cp in enumerate(colliding):
            if i >= 5:
                coll_str.append("...a další")
                break
            cname = projects.get(cp, {'name': f'P{cp}'})['name']
            coll_str.append(f"P{cp} ({cname})")

    tooltip = (
        f"<b>{task_text}</b><br>"
        f"Projektová barva: <span style='color:{original_color}; font-weight:bold'>■ {original_color}</span><br>"
        f"Od: %{{x|%d.%m.%Y}}<br>Do: %{{x2|%d.%m.%Y}}"
    )

    if status_text:
        tooltip += f"<br><b>Stav:</b> {status_text}"
    if coll_str:
        tooltip += f"<br><b>Kolize s:</b> {', '.join(coll_str)}"

    plot_data.append({
        "Pracoviště": get_workplace_name(t['workplace_id']),
        "Úkol": task_text,
        "Start": max(start_date, first_day),
        "Finish": min(end_date, last_day) + timedelta(days=1),
        "Color": display_color,
        "Tooltip": tooltip,
        "TextColor": text_color
    })

if not plot_data:
    st.info(f"Žádné úkoly v {calendar.month_name[selected_month]} {selected_year}.")
else:
    df = pd.DataFrame(plot_data)
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Pracoviště",
        color="Color",
        text="Úkol",
        hover_name="Úkol",
        title=f"HMG HK – {calendar.month_name[selected_month]} {selected_year}",
        height=400 + len(workplaces_set) * 40
    )
    fig.update_traces(
        opacity=0.7,
        textposition='inside',
        textfont_color=df["TextColor"].tolist(),
        hovertemplate=df["Tooltip"].tolist(),
    )
    fig.update_xaxes(
        tickformat="%d",
        tickmode="linear",
        dtick=86400000.0,
        range=[first_day, last_day + timedelta(days=1)]
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(bargap=0.2, bargroupgap=0.1, showlegend=False)

    # Víkendy a svátky – červené dashed vline
    holidays = get_holidays(selected_year)
    current = first_day
    while current <= last_day:
        if is_weekend_or_holiday(current):
            label = "S" if current in holidays else "V"
            fig.add_vline(
                x=current.isoformat(),          # ← klíčová změna
                line_dash="dash",
                line_color="red",
                opacity=0.5,
                annotation_text=label,
                annotation_position="top"
            )
        current += timedelta(days=1)

    st.plotly_chart(fig, use_container_width=True)

    # ──────────────────────────────────────────────────────────────
    # EXPORT DO PDF
    # ──────────────────────────────────────────────────────────────
    if st.button("Exportovat HMG měsíční do PDF"):
        file_name = f"HMG_mesicni_{selected_year}_{selected_month:02d}.pdf"
        pdf = pdf_canvas.Canvas(file_name, pagesize=landscape(A4))
        width, height = landscape(A4)

        # Nadpis
        pdf.setFont(pdf_font, 16)
        pdf.drawCentredString(width / 2, height - 0.8 * inch, f"HMG HK – {calendar.month_name[selected_month]} {selected_year}")

        # Rozměry
        left_margin = 1.0 * inch
        wp_col_width = 2.0 * inch
        day_col_width = (width - left_margin - wp_col_width - 0.8 * inch) / num_days
        header_y = height - 1.5 * inch
        row_height = (height - 2.5 * inch) / len(workplaces_set) if workplaces_set else 40

        # Hlavička dnů (červeně pro víkendy/svátky)
        pdf.setFont(pdf_font, 10)
        for d in range(1, num_days + 1):
            current_date = date(selected_year, selected_month, d)
            x = left_margin + wp_col_width + (d - 1) * day_col_width
            fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
            pdf.setFillColorRGB(*fill_color)
            pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))

        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)

        # Seřazená pracoviště
        sorted_workplaces = sorted(workplaces_set)

        # Mapa barev na RGB
        colors_rgb = {}
        for pid, proj in projects.items():
            hex_color = proj['color']
            r = int(hex_color[1:3], 16) / 255.0
            g = int(hex_color[3:5], 16) / 255.0
            b = int(hex_color[5:7], 16) / 255.0
            colors_rgb[hex_color] = (r, g, b)
        colors_rgb["#34A853"] = (0.20, 0.66, 0.32)  # done
        colors_rgb["#EA4335"] = (0.92, 0.26, 0.21)  # collision

        # Data pro PDF
        pdf_data = []
        for item in plot_data:
            start_day = (item["Start"] - first_day).days + 1
            end_day = (item["Finish"] - first_day).days
            pdf_data.append({
                "wp_name": item["Pracoviště"],
                "task_text": item["Úkol"],
                "start_day": start_day,
                "end_day": end_day,
                "color": item["Color"]
            })

        # Kreslení řádků
        for i, wp_name in enumerate(sorted_workplaces):
            y_top = header_y - 20 - i * row_height
            y_bottom = y_top - row_height

            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont(pdf_font, 9)
            pdf.drawString(left_margin, y_top - row_height / 2 - 3, wp_name)

            pdf.line(left_margin, y_bottom, width - 0.8 * inch, y_bottom)

            for item in pdf_data:
                if item["wp_name"] != wp_name:
                    continue
                x1 = left_margin + wp_col_width + (item["start_day"] - 1) * day_col_width
                x2 = left_margin + wp_col_width + item["end_day"] * day_col_width
                rgb = colors_rgb.get(item["color"], (0.26, 0.52, 0.96))
                pdf.setFillColorRGB(*rgb)
                pdf.rect(x1, y_bottom + 5, x2 - x1, row_height - 10, fill=1, stroke=1)

                # Text úkolu
                if item["color"] == "#EA4335":
                    pdf.setFillColorRGB(1, 1, 1)
                else:
                    pdf.setFillColorRGB(0, 0, 0)
                pdf.setFont(pdf_font, 8)
                pdf.drawCentredString((x1 + x2) / 2, y_bottom + row_height / 2 - 4, item["task_text"])

        pdf.save()

        with open(file_name, "rb") as f:
            st.download_button(
                label="Stáhnout PDF s HMG",
                data=f.read(),
                file_name=file_name,
                mime="application/pdf"
            )