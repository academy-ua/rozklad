import streamlit as st
import pandas as pd
import io
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматичного формування розкладу")

if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = None

# 1. Параметри сітки
st.markdown("### 1. Параметри навчальної сітки")
col1, col2 = st.columns(2)
with col1:
    days_count = st.number_input("Кількість навчальних днів", min_value=1, max_value=7, value=5)
with col2:
    slots_count = st.number_input("Кількість пар на день (1 пара = 2 години)", min_value=1, max_value=8, value=4)

DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"][:days_count]

# 2. Академічні групи та практика
st.markdown("### 2. Налаштування груп та практики")
st.caption("Вкажіть групи та день практики (якщо практика 1 день на тиждень). Якщо практика триває кілька тижнів поспіль — залиште 'Немає'.")

default_groups = pd.DataFrame([
    {"Група": "ПО-11", "Формат": "Очно", "День практики": "Вівторок"},
    {"Група": "ПО-21", "Формат": "Очно", "День практики": "Немає"},
    {"Група": "ПО-31", "Формат": "Онлайн", "День практики": "Немає"},
    {"Група": "ПО-41", "Формат": "Онлайн", "День практики": "Немає"}
])

groups_df = st.data_editor(
    default_groups,
    num_rows="dynamic",
    column_config={
        "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
        "День практики": st.column_config.SelectboxColumn(options=["Немає"] + DAY_NAMES)
    },
    use_container_width=True,
    key="groups_editor"
)

# 3. Навчальний план
st.markdown("### 3. Навчальний план дисциплін")
st.caption("Вкажіть предмети для кожної групи, викладача, кількість пар на тиждень та тип аудиторії.")

active_groups = groups_df["Група"].dropna().unique().tolist() if not groups_df.empty else ["ПО-11"]

default_plan = pd.DataFrame([
    {"Група": "ПО-11", "Предмет": "Математика", "Викладач": "Черненко В.П.", "Пар на тиждень": 2, "Тип аудиторії": "Звичайна"},
    {"Група": "ПО-11", "Предмет": "Інформатика", "Викладач": "Іванов І.І.", "Пар на тиждень": 1, "Тип аудиторії": "Комп'ютерний клас"},
    {"Група": "ПО-21", "Предмет": "Психологія", "Викладач": "Петренко П.П.", "Пар на тиждень": 2, "Тип аудиторії": "Звичайна"},
    {"Група": "ПО-21", "Предмет": "Програмування", "Викладач": "Іванов І.І.", "Пар на тиждень": 2, "Тип аудиторії": "Комп'ютерний клас"},
    {"Група": "ПО-31", "Предмет": "Менеджмент", "Викладач": "Петренко П.П.", "Пар на тиждень": 2, "Тип аудиторії": "Онлайн"},
    {"Група": "ПО-41", "Предмет": "Аналіз даних", "Викладач": "Черненко В.П.", "Пар на тиждень": 2, "Тип аудиторії": "Потокова лекція"}
])

curriculum_df = st.data_editor(
    default_plan,
    num_rows="dynamic",
    column_config={
        "Група": st.column_config.SelectboxColumn(options=active_groups),
        "Пар на тиждень": st.column_config.NumberColumn(min_value=1, max_value=10, step=1, default=1),
        "Тип аудиторії": st.column_config.SelectboxColumn(options=["Звичайна", "Комп'ютерний клас", "Потокова лекція", "Онлайн"])
    },
    use_container_width=True,
    key="curriculum_editor"
)

# Функція кольорів
def color_cells(val):
    if not isinstance(val, str):
        return ''
    val_lower = val.lower()
    if 'практика' in val_lower:
        return 'background-color: #E6E6FA; color: black;'
    elif 'онлайн' in val_lower:
        return 'background-color: #AFEEEE; color: black;'
    elif 'потік' in val_lower:
        return 'background-color: #98FB98; color: black;'
    elif 'комп' in val_lower:
        return 'background-color: #FFFACD; color: black;'
    return ''

# Алгоритм формування розкладу
def generate_schedule(d_cnt, s_cnt, day_names, grp_df, plan_df):
    if grp_df.empty or plan_df.empty:
        return None, "Заповніть таблиці груп та навчального плану."

    model = CpModel()
    
    # Створення списку окремих занять
    lessons = []
    lesson_id = 0
    
    for _, row in plan_df.iterrows():
        g_name = str(row.get("Група", "")).strip()
        subj = str(row.get("Предмет", "")).strip()
        teacher = str(row.get("Викладач", "")).strip()
        pairs = int(row.get("Пар на тиждень", 1)) if pd.notnull(row.get("Пар на тиждень")) else 1
        room_type = str(row.get("Тип аудиторії", "Звичайна")).strip()

        if not g_name or not subj:
            continue

        for _ in range(pairs):
            lessons.append({
                "id": lesson_id,
                "group": g_name,
                "subject": subj,
                "teacher": teacher,
                "room_type": room_type
            })
            lesson_id += 1

    if not lessons:
        return None, "Не знайдено коректно заповнених предметів у навчальному плані."

    # Змінні рішення x[lesson_id, day, slot]
    x = {}
    for l in lessons:
        for d in range(d_cnt):
            for s in range(s_cnt):
                x[l["id"], d, s] = model.NewBoolVar(f'x_{l["id"]}_{d}_{s}')

    # 1. Кожне заняття має відбутися рівно 1 раз на тиждень
    for l in lessons:
        model.Add(sum(x[l["id"], d, s] for d in range(d_cnt) for s in range(s_cnt)) == 1)

    # 2. Не більше 1 пари у групи на один слот
    groups_list = list(set([l["group"] for l in lessons]))
    for g in groups_list:
        g_lessons = [l for l in lessons if l["group"] == g]
        for d in range(d_cnt):
            for s in range(s_cnt):
                model.Add(sum(x[l["id"], d, s] for l in g_lessons) <= 1)

    # 3. День практики для групи (заборона накладання занять)
    for _, g_row in grp_df.iterrows():
        g_name = str(g_row.get("Група", "")).strip()
        prac_day = str(g_row.get("День практики", "Немає")).strip()
        if prac_day in day_names:
            p_d_idx = day_names.index(prac_day)
            g_lessons = [l for l in lessons if l["group"] == g_name]
            for l in g_lessons:
                for s in range(s_cnt):
                    model.Add(x[l["id"], p_d_idx, s] == 0)

    # 4. Не більше 1 пари у викладача на один слот (крім потокових лекцій)
    teachers_list = list(set([l["teacher"] for l in lessons if l["teacher"]]))
    for t in teachers_list:
        t_lessons = [l for l in lessons if l["teacher"] == t and l["room_type"] != "Потокова лекція"]
        for d in range(d_cnt):
            for s in range(s_cnt):
                model.Add(sum(x[l["id"], d, s] for l in t_lessons) <= 1)

    # 5. Єдиний комп'ютерний клас (максимум 1 пара на один слот)
    comp_lessons = [l for l in lessons if l["room_type"] == "Комп'ютерний клас"]
    for d in range(d_cnt):
        for s in range(s_cnt):
            model.Add(sum(x[l["id"], d, s] for l in comp_lessons) <= 1)

    # Запуск розв'язувача
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status not in [OPTIMAL, FEASIBLE]:
        return None, "Не вдалося розставити всі пари. Спробуйте збільшити кількість днів/пар на день або перевірте навантаження."

    # Побудова таблиці розкладу
    schedule_dict = {"Час": [f"Пара {s+1}" for s in range(s_cnt)]}
    
    # Отримуємо дні практики по групах для маркування в таблиці
    prac_map = {}
    for _, g_row in grp_df.iterrows():
        g_n = str(g_row.get("Група", "")).strip()
        p_d = str(g_row.get("День практики", "Немає")).strip()
        if p_d in day_names:
            prac_map.setdefault(p_d, []).append(g_n)

    for d_idx, day_name in enumerate(day_names):
        day_cells = []
        for s_idx in range(s_cnt):
            cell_items = []
            
            # Якщо у груп у цей день практика
            if day_name in prac_map and s_idx == 0:
                p_groups = ", ".join(prac_map[day_name])
                cell_items.append(f"ПРАКТИКА ({p_groups})")

            for l in lessons:
                if solver.Value(x[l["id"], d_idx, s_idx]) == 1:
                    tag = f", {l['room_type']}" if l['room_type'] != "Звичайна" else ""
                    t_str = f" ({l['teacher']})" if l['teacher'] else ""
                    cell_items.append(f"{l['group']}: {l['subject']}{t_str}{tag}")

            if cell_items:
                day_cells.append(" | ".join(cell_items))
            else:
                day_cells.append("-")
        
        schedule_dict[day_name] = day_cells

    return pd.DataFrame(schedule_dict), None

# Кнопка запуску
if st.button("Згенерувати розклад", type="primary"):
    with st.spinner("Формування розкладу згідно з навчальним планом..."):
        res_df, err = generate_schedule(days_count, slots_count, DAY_NAMES, groups_df, curriculum_df)
    
    if err:
        st.error(err)
    else:
        st.success("Розклад успішно згенеровано!")
        st.session_state.schedule_df = res_df

# Вивід та експорт
if st.session_state.schedule_df is not None:
    st.markdown("### ✏️ Редагування та перегляд готового розкладу")
    st.info("Ви можете відкоригувати будь-яку комірку прямо на екрані перед завантаженням.")
    
    styled_df = st.session_state.schedule_df.style.map(color_cells)
    edited_df = st.data_editor(styled_df, use_container_width=True)
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        edited_df.to_excel(writer, index=False, sheet_name='Розклад')
        worksheet = writer.sheets['Розклад']
        for i, col in enumerate(edited_df.columns):
            column_len = max(edited_df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, column_len)

    st.download_button(
        label="📥 Завантажити для Google Таблиць (.xlsx)",
        data=buffer.getvalue(),
        file_name="rozklad_academy.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
