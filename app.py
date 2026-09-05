import streamlit as st
import pandas as pd
import io
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматизованого формування розкладу")

# Часові слоти академії
SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:42 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]

SLOT_LABELS = [f"{s['label']}\n({s['time']})" for s in SLOT_DETAILS]
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]

if 'schedule_matrix' not in st.session_state:
    st.session_state.schedule_matrix = None
if 'teacher_limits' not in st.session_state:
    st.session_state.teacher_limits = []

# 1. Параметри навчального семестру
st.markdown("### 1. Параметри семестру та сітки")
col_w, col_d, col_s = st.columns(3)
with col_w:
    weeks_count = st.number_input("Кількість тижнів у семестрі", min_value=1, max_value=25, value=15)
with col_d:
    days_count = st.number_input("Навчальних днів на тиждень", min_value=1, max_value=6, value=5)
with col_s:
    slots_count = st.number_input("Пар на день", min_value=1, max_value=5, value=5)

ACTIVE_DAYS = DAY_NAMES[:days_count]
ACTIVE_SLOTS = SLOT_LABELS[:slots_count]

# 2. Довідники закладу
st.markdown("### 2. Довідники закладу (Групи, Викладачі, Аудиторії)")
col_g, col_t, col_r = st.columns(3)

with col_g:
    st.markdown("**Академічні групи**")
    default_groups = pd.DataFrame([
        {"Група": "ДО-11Б", "Формат за замовчуванням": "Очно", "День практики": "Немає"},
        {"Група": "ДО-21Б", "Формат за замовчуванням": "Очно", "День практики": "Вівторок"},
        {"Група": "ДО-31Б онлайн", "Формат за замовчуванням": "Онлайн", "День практики": "Немає"},
        {"Група": "М-11Б", "Формат за замовчуванням": "Очно", "День практики": "Немає"}
    ])
    groups_df = st.data_editor(
        default_groups,
        num_rows="dynamic",
        column_config={
            "Формат за замовчуванням": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
            "День практики": st.column_config.SelectboxColumn(options=["Немає"] + ACTIVE_DAYS)
        },
        use_container_width=True,
        key="groups_editor"
    )

with col_t:
    st.markdown("**Список викладачів**")
    teachers_text = st.text_area(
        "ПІБ викладачів (кожен з нового рядка)",
        "Черненко В.П.\nАлексєєва Т.В.\nКулікова Т.В.\nКостенко О.В.\nКоробко Ю.В.\nПантелеймоненко А.О.\nІванов І.І.\nПетренко П.П.",
        height=190
    )

with col_r:
    st.markdown("**Аудиторний фонд**")
    rooms_text = st.text_area(
        "Аудиторії (кожна з нового рядка)",
        "1 аудиторія\n15 аудиторія\n27-А аудиторія\n32 аудиторія\nКомп'ютерний клас\nВелика лекційна ауд.",
        height=190
    )

# Парсинг довідників
active_groups = [g for g in groups_df["Група"].dropna().unique().tolist() if str(g).strip()]
if not active_groups:
    active_groups = ["ДО-11Б"]

active_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
if not active_teachers:
    active_teachers = ["Черненко В.П."]

active_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]
if not active_rooms:
    active_rooms = ["1 аудиторія"]

# 3. Обмеження викладачів
st.markdown("### 3. Обмеження та недоступність викладачів")
col_t_select, col_d_select, col_s_select, col_btn = st.columns([2, 2.5, 3, 1.5])

with col_t_select:
    limit_teacher = st.selectbox("Викладач", options=active_teachers)
with col_d_select:
    limit_days = st.multiselect(
        "Дні тижня", 
        options=["Всі дні"] + ACTIVE_DAYS,
        default=["Понеділок"]
    )
with col_s_select:
    limit_slots = st.multiselect(
        "Недоступні пари", 
        options=["Всі пари"] + [s['label'] for s in SLOT_DETAILS[:slots_count]],
        default=["0 пара"]
    )
with col_btn:
    st.write(" ")
    st.write(" ")
    if st.button("Додати обмеження"):
        if limit_teacher and limit_days and limit_slots:
            target_days = ACTIVE_DAYS if "Всі дні" in limit_days else limit_days
            for d_item in target_days:
                st.session_state.teacher_limits.append({
                    "Викладач": limit_teacher,
                    "День": d_item,
                    "Пари": ", ".join(limit_slots)
                })
            st.rerun()

if st.session_state.teacher_limits:
    limits_df = pd.DataFrame(st.session_state.teacher_limits)
    st.dataframe(limits_df, use_container_width=True)
    if st.button("Очистити всі обмеження"):
        st.session_state.teacher_limits = []
        st.rerun()
else:
    limits_df = pd.DataFrame(columns=["Викладач", "День", "Пари"])

# 4. Навчальний план дисциплін (З опціями Онлайн та Потокова лекція)
st.markdown("### 4. Навчальний план дисциплін")
st.caption("Для потокових предметів вкажіть кілька груп через кому (наприклад: ДО-11Б, ДО-21Б) та оберіть 'Потокова лекція: Так'.")

default_plan = pd.DataFrame([
    {
        "Група": active_groups[0],
        "Предмет": "Анатомія та гігієна",
        "Викладач": active_teachers[1] if len(active_teachers) > 1 else active_teachers[0],
        "Годин на семестр": 30,
        "Формат": "Очно",
        "Потокова лекція?": "Ні",
        "Аудиторія": active_rooms[0]
    }
])

curriculum_df = st.data_editor(
    default_plan,
    num_rows="dynamic",
    column_config={
        "Група": st.column_config.TextColumn(required=True, help="Вкажіть 1 групу або кілька через кому для потоку"),
        "Предмет": st.column_config.TextColumn(required=True),
        "Викладач": st.column_config.SelectboxColumn(options=active_teachers, required=True),
        "Годин на семестр": st.column_config.NumberColumn(min_value=10, max_value=300, step=10, default=30, required=True),
        "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"], required=True, default="Очно"),
        "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"], required=True, default="Ні"),
        "Аудиторія": st.column_config.SelectboxColumn(options=active_rooms, required=True)
    },
    use_container_width=True,
    key="curriculum_editor"
)

# Функція підсвічування осередків розкладу
def style_schedule_grid(val):
    if not isinstance(val, str) or val == "-" or not val:
        return ""
    val_upper = val.upper()
    if "ОНЛАЙН" in val_upper:
        return "background-color: #CCFFFF; color: #000000; font-weight: bold;"  # Блакитний
    elif "ПРАКТИКА" in val_upper:
        return "background-color: #E6E6FA; color: #000000; font-weight: bold;"  # Лаванда
    elif "ПОТІК" in val_upper:
        return "background-color: #D5E8D4; color: #000000; font-weight: bold;"  # Зелений
    elif "КОМП" in val_upper:
        return "background-color: #FFF2CC; color: #000000; font-weight: bold;"  # Жовтий
    else:
        return "background-color: #F5F5F5; color: #000000;"

# Математичний алгоритм генерації
def generate_schedule_matrix(w_cnt, d_cnt, s_cnt, day_names, slot_labels, grp_df, lim_df, plan_df):
    if grp_df.empty or plan_df.empty:
        return None, "Будь ласка, заповніть групи та навчальний план."

    model = CpModel()
    lessons = []
    lesson_id = 0

    all_registered_groups = [g for g in grp_df["Група"].dropna().unique().tolist() if str(g).strip()]

    for _, row in plan_df.iterrows():
        g_str = str(row.get("Група", "")).strip()
        subj = str(row.get("Предмет", "")).strip()
        teacher = str(row.get("Викладач", "")).strip()
        hours = float(row.get("Годин на семестр", 30)) if pd.notnull(row.get("Годин на семестр")) else 30
        fmt = str(row.get("Формат", "Очно")).strip()
        is_stream = str(row.get("Потокова лекція?", "Ні")).strip() == "Так"
        room = str(row.get("Аудиторія", "")).strip()

        if not g_str or not subj or g_str == "None" or subj == "None":
            continue

        # Парсинг кількох груп, якщо потік
        target_groups = [g.strip() for g in g_str.split(",") if g.strip()]

        pairs_per_week = max(1, int(round(hours / (2.0 * w_cnt))))

        for _ in range(pairs_per_week):
            lessons.append({
                "id": lesson_id,
                "groups": target_groups,
                "subject": subj,
                "teacher": teacher,
                "fmt": fmt,
                "is_stream": is_stream,
                "room": room
            })
            lesson_id += 1

    if not lessons:
        return None, "Не знайдено заповнених предметів."

    x = {}
    for l in lessons:
        for d in range(d_cnt):
            for s in range(s_cnt):
                x[l["id"], d, s] = model.NewBoolVar(f'x_{l["id"]}_{d}_{s}')

    # 1. Рівно 1 пара на тиждень
    for l in lessons:
        model.Add(sum(x[l["id"], d, s] for d in range(d_cnt) for s in range(s_cnt)) == 1)

    # 2. Перевірка накладок для кожної окремої групи
    for g in all_registered_groups:
        g_lessons = [l for l in lessons if g in l["groups"]]
        for d in range(d_cnt):
            for s in range(s_cnt):
                model.Add(sum(x[l["id"], d, s] for l in g_lessons) <= 1)

    # 3. Обмеження практики
    for _, g_row in grp_df.iterrows():
        g_n = str(g_row.get("Група", "")).strip()
        p_d = str(g_row.get("День практики", "Немає")).strip()
        if p_d in day_names:
            p_idx = day_names.index(p_d)
            g_lessons = [l for l in lessons if g_n in l["groups"]]
            for l in g_lessons:
                for s in range(s_cnt):
                    model.Add(x[l["id"], p_idx, s] == 0)

    # 4. Обмеження викладачів
    if not lim_df.empty:
        for _, lim_row in lim_df.iterrows():
            t_n = str(lim_row.get("Викладач", "")).strip()
            l_d = str(lim_row.get("День", "")).strip()
            l_s_str = str(lim_row.get("Пари", "")).strip()

            if t_n and l_d in day_names:
                d_idx = day_names.index(l_d)
                t_lessons = [l for l in lessons if l["teacher"] == t_n]

                for s_idx in range(s_cnt):
                    s_name = f"{s_idx} пара"
                    if "Всі пари" in l_s_str or s_name in l_s_str:
                        for l in t_lessons:
                            model.Add(x[l["id"], d_idx, s_idx] == 0)

    # 5. Один викладач не проводитиме 2 пари одночасно
    all_teachers = list(set([l["teacher"] for l in lessons if l["teacher"]]))
    for t in all_teachers:
        t_lessons = [l for l in lessons if l["teacher"] == t]
        for d in range(d_cnt):
            for s in range(s_cnt):
                model.Add(sum(x[l["id"], d, s] for l in t_lessons) <= 1)

    # 6. Обмеження на комп'ютерні класи
    comp_lessons = [l for l in lessons if "Комп" in l["room"]]
    for d in range(d_cnt):
        for s in range(s_cnt):
            model.Add(sum(x[l["id"], d, s] for l in comp_lessons) <= 1)

    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status not in [OPTIMAL, FEASIBLE]:
        return None, "Не вдалося розставити розклад. Занадто багато обмежень або замало вільних слотів."

    # Побудова сітки розкладу
    rows_list = []
    
    prac_map = {}
    for _, g_row in grp_df.iterrows():
        g_n = str(g_row.get("Група", "")).strip()
        p_d = str(g_row.get("День практики", "Немає")).strip()
        if p_d in day_names:
            prac_map.setdefault(p_d, []).append(g_n)

    for d_idx, day_name in enumerate(day_names):
        for s_idx in range(s_cnt):
            row_dict = {
                "День тижня": day_name,
                "Пара / Час": slot_labels[s_idx]
            }
            
            for g_name in all_registered_groups:
                if day_name in prac_map and g_name in prac_map[day_name] and s_idx == 0:
                    row_dict[g_name] = "ПРАКТИКА"
                    continue

                cell_content = "-"
                for l in lessons:
                    if g_name in l["groups"] and solver.Value(x[l["id"], d_idx, s_idx]) == 1:
                        loc_str = "ОНЛАЙН" if l["fmt"] == "Онлайн" else l["room"]
                        stream_tag = "\n(ПОТІК)" if l["is_stream"] else ""
                        cell_content = f"{l['subject']}{stream_tag}\n{l['teacher']}\n{loc_str}"
                        break
                
                row_dict[g_name] = cell_content
            
            rows_list.append(row_dict)

    return pd.DataFrame(rows_list), None

# Кнопка запуску
if st.button("Згенерувати розклад", type="primary"):
    with st.spinner("Обчислення оптимального розкладу..."):
        res_matrix, err = generate_schedule_matrix(
            weeks_count, days_count, slots_count, 
            ACTIVE_DAYS, ACTIVE_SLOTS, 
            groups_df, limits_df, curriculum_df
        )
    
    if err:
        st.error(err)
    else:
        st.success("Розклад успішно згенеровано!")
        st.session_state.schedule_matrix = res_matrix

# Відображення та експорт
if st.session_state.schedule_matrix is not None:
    st.markdown("---")
    st.markdown("### 📊 Перегляд та експорт розкладу")

    view_option = st.radio(
        "Режим відображення:", 
        ["Повний розклад (всі групи)", "По конкретній групі", "По конкретному викладачу"], 
        horizontal=True
    )

    df_full = st.session_state.schedule_matrix.copy()

    if view_option == "Повний розклад (всі групи)":
        styled_df = df_full.style.map(style_schedule_grid)
        st.dataframe(styled_df, use_container_width=True, height=600)

    elif view_option == "По конкретній групі":
        group_cols = [c for c in df_full.columns if c not in ["День тижня", "Пара / Час"]]
        selected_g = st.selectbox("Оберіть групу:", group_cols)
        
        df_group = df_full[["День тижня", "Пара / Час", selected_g]]
        styled_g = df_group.style.map(style_schedule_grid)
        st.dataframe(styled_g, use_container_width=True, height=600)

    elif view_option == "По конкретному викладачу":
        all_teachers_in_plan = [t for t in active_teachers if t]
        selected_t = st.selectbox("Оберіть викладача:", all_teachers_in_plan)

        df_teacher = df_full.copy()
        group_cols = [c for c in df_teacher.columns if c not in ["День тижня", "Пара / Час"]]
        
        for col in group_cols:
            df_teacher[col] = df_teacher[col].apply(
                lambda val: val if isinstance(val, str) and selected_t in val else "-"
            )

        styled_t = df_teacher.style.map(style_schedule_grid)
        st.dataframe(styled_t, use_container_width=True, height=600)

    # Експорт у Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df_full.to_excel(writer, index=False, sheet_name='Повний розклад')
        
        workbook  = writer.book
        worksheet = writer.sheets['Повний розклад']
        wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center'})
        worksheet.set_column('A:Z', 25, wrap_format)

    st.download_button(
        label="📥 Завантажити повний розклад у Excel (.xlsx)",
        data=buffer.getvalue(),
        file_name="rozklad_academy.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
