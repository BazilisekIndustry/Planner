import streamlit as st
from utils.common import *  # ← importuje VŠECHNO z common.py (nejjednodušší)
from utils.auth_simple import check_login, logout
try:
    pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
    pdf_font = 'DejaVu'
except Exception:
    print("Varování: Font DejaVuSans.ttf nebyl nalezen – diakritika v PDF nemusí fungovat správně.")
    pdf_font = 'Helvetica'



# Kontrola přihlášení (nový způsob)
if not check_login():
    st.switch_page("Home.py")
    st.stop()

# Uživatelská data – teď už máš vše v session_state
username = st.session_state.get("username", "neznámý")
name = st.session_state.get("name", "Uživatel")
role = st.session_state.get("role", "viewer")
read_only = (role == "viewer")

render_sidebar("HMG měsíční")
st.header("HMG měsíční – Přehled úkolů po dnech")
selected_year = st.number_input("Rok", min_value=2020, max_value=2030, value=datetime.now().year, key="hmg_year")
selected_month = st.number_input("Měsíc", min_value=1, max_value=12, value=datetime.now().month, key="hmg_month")
first_day = date(selected_year, selected_month, 1)
if selected_month == 12:
    last_day = date(selected_year + 1, 1, 1) - timedelta(days=1)
else:
    last_day = date(selected_year, selected_month + 1, 1) - timedelta(days=1)
num_days = last_day.day

response = supabase.table('tasks').select('*').not_.is_('start_date', 'null').not_.is_('end_date', 'null').execute()
all_tasks = response.data
plot_data = []
pdf_data = []
workplaces_set = set()
for t in all_tasks:
    tid = t['id']
    pid = t['project_id']
    wp_id = t['workplace_id']
    hours = t['hours']
    mode = t['capacity_mode']
    start_int = t['start_date']
    end_int = t['end_date']
    status = t['status']
    notes = t['notes']
    if status == 'canceled':
        continue
    wp_name = get_workplace_name(wp_id)
    workplaces_set.add(wp_name)
    start_date = datetime.strptime(start_int, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_int, '%Y-%m-%d').date()
    if end_date < first_day or start_date > last_day:
        continue
    task_text = f"P{pid}"
    if check_collisions(tid):
        task_text += " !"
    color = "#4285f4"
    if status == 'done':
        color = "#34a853"
    if check_collisions(tid):
        color = "#ea4335"
    display_start = max(start_date, first_day)
    display_end = min(end_date, last_day)
    plot_data.append({
        "Pracoviště": wp_name,
        "Úkol": task_text,
        "Start": display_start,
        "Finish": display_end + timedelta(days=1),
        "Color": color
    })
    pdf_data.append({
        "wp_name": wp_name,
        "task_text": task_text,
        "start_day": display_start.day,
        "end_day": display_end.day,
        "color": color
    })

if not plot_data:
    st.info(f"Žádné úkoly pro {calendar.month_name[selected_month]} {selected_year}.")
else:
    df = pd.DataFrame(plot_data)
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Pracoviště",
        color="Color",
        color_discrete_map={"#4285f4": "#4285f4", "#34a853": "#34a853", "#ea4335": "#ea4335"},
        hover_name="Úkol",
        title=f"HMG HK – {calendar.month_name[selected_month]} {selected_year}",
        height=400 + len(workplaces_set) * 40
    )
    fig.update_xaxes(
        tickformat="%d",
        tickmode="linear",
        dtick=86400000.0,
        range=[first_day, last_day + timedelta(days=1)]
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(bargap=0.2, bargroupgap=0.1, showlegend=False)
    st.plotly_chart(fig, width='stretch')

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
        row_height = (height - 2.5 * inch) / len(workplaces_set) if workplaces_set else 40
        pdf.setFont(pdf_font, 10)
        for d in range(1, num_days + 1):
            current_date = date(selected_year, selected_month, d)
            x = left_margin + wp_col_width + (d - 1) * day_col_width
            fill_color = (1, 0, 0) if is_weekend_or_holiday(current_date) else (0, 0, 0)
            pdf.setFillColorRGB(*fill_color)
            pdf.drawCentredString(x + day_col_width / 2, header_y, str(d))
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.line(left_margin + wp_col_width, header_y - 10, width - 0.8 * inch, header_y - 10)
        sorted_workplaces = sorted(workplaces_set)
        colors_rgb = {
            "#4285f4": (0.26, 0.52, 0.96),
            "#34a853": (0.20, 0.66, 0.32),
            "#ea4335": (0.92, 0.26, 0.21)
        }
        for i, wp_name in enumerate(sorted_workplaces):
            y_top = header_y - 20 - i * row_height
            y_bottom = y_top - row_height
            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont(pdf_font, 9)
            pdf.drawString(left_margin, y_top - row_height / 2, wp_name)
            pdf.line(left_margin, y_bottom, width - 0.8 * inch, y_bottom)
            for item in pdf_data:
                if item["wp_name"] != wp_name:
                    continue
                x1 = left_margin + wp_col_width + (item["start_day"] - 1) * day_col_width
                x2 = left_margin + wp_col_width + item["end_day"] * day_col_width
                rgb = colors_rgb.get(item["color"], (0.26, 0.52, 0.96))
                pdf.setFillColorRGB(*rgb)
                pdf.rect(x1, y_bottom + 5, x2 - x1, row_height - 10, fill=1, stroke=1)
                pdf.setFillColorRGB(1, 1, 1)
                pdf.setFont(pdf_font, 8)
                pdf.drawCentredString((x1 + x2) / 2, y_bottom + row_height / 2, item["task_text"])
        pdf.save()
        with open(file_name, "rb") as f:
            st.download_button(
                label="Stáhnout PDF s HMG",
                data=f.read(),
                file_name=file_name,
                mime="application/pdf"
            )

