import streamlit as st
import pandas as pd
import io
import json
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

# --- КОНСТАНТИ ТА НАЛАШТУВАННЯ ---
st.set_page_config(page_title="Academy Scheduler Pro", layout="wide")

SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:42 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]

DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]
SLOT_OPTIONS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]

# --- СТИЛІЗАЦІЯ ---
def apply_custom_css():
    st.markdown("""
        <style>
        .stDataFrame td { white-space: pre-wrap !important; }
        .main-header { font-size: 2.2rem; color: #1E3A8A; font-weight: bold; margin-bottom: 1rem; }
        </style>
    """, unsafe_allow_html=True)

def style_schedule_grid(val):
    if not isinstance(val, str) or val in ["-", ""]: return ""
    v = val.upper()
    if "ОНЛАЙН" in v: return "background-color: #E0F2FE; color: #0369A1; font-weight: 500;"
    if "ПРАКТИКА" in v: return "background-color: #F3E8FF; color: #7E22CE; font-weight: bold;"
    if "ПОТІК" in v: return "background-color: #DCFCE7; color: #15803D; font-weight: 500;"
    return "background-color: #F9FAFB; color: #111827;"

# --- СТАН ДОДАТКУ ---
if 'schedule_results' not in st.session_state:
    st.session_state.schedule_results = None

def init_state():
    defaults = {
        "cfg_groups": pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}]),
        "cfg_teachers": "Усатенко В.М.",
        "cfg_rooms": "1 авдиторія\n15 авдиторія\n27-А комп'ютерний клас\nОНЛАЙН",
        "cfg_limits": pd.DataFrame(columns=["Викладач", "День тижня", "Недоступні пари"]),
        "cfg_curriculum": pd.DataFrame([{
            "Групи": ["ПО-11Б"], "Дисципліна": "Педагогіка", "Викладач": "Усатенко В.М.",
            "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція": "Ні", "Авдиторія": "15 авдиторія"
        }])
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_state()
apply_custom_css()

# --- ЛОГІКА ОБРОБКИ ДАНИХ ---
def safe_json_import(uploaded_file):
    try:
        data = json.load(uploaded_file)
        if "groups" in data: st.session_state.cfg_groups = pd.DataFrame(data["groups"])
        if "teachers" in data: st.session_state.cfg_teachers = data["teachers"]
        if "rooms" in data: st.session_state.cfg_rooms = data["rooms"]
        if "limits" in data: st.session_state.cfg_limits = pd.DataFrame(data["limits"])
        if "curriculum" in data: st.session_state.cfg_curriculum = pd.DataFrame(data["curriculum"])
        st.success("✅ Дані успішно завантажені")
        st.rerun()
    except Exception as e:
        st.error(f"Помилка імпорту: {e}")

# --- ГОЛОВНИЙ ІНТЕРФЕЙС ---
st.markdown('<div class="main-header">🎓 Academy Scheduler Pro</div>', unsafe_allow_html=True)

tab_config, tab_curriculum, tab_limits, tab_view = st.tabs([
    "⚙️ Основні налаштування", "📚 Навчальний план", "🚫 Обмеження", "📅 Результати"
])

with tab_config:
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Параметри сітки")
        c_w, c_d, c_s = st.columns(3)
        max_weeks = c_w.number_input("Тижнів", 1, 25, 15)
        days_count = c_d.number_input("Днів на тиждень", 1, 6, 5)
        slots_count = c_s.number_input("Пар на день", 1, 5, 5)
        
        active_days = DAY_NAMES[:days_count]
        active_slots = SLOT_OPTIONS[:slots_count]

    with col2:
        st.subheader("💾 Робота з файлами")
        st.file_uploader("Завантажити конфігурацію (.json)", type="json", on_change=None, key="json_up")
        if st.session_state.json_up:
            safe_json_import(st.session_state.json_up)
            
        export_data = {
            "groups": st.session_state.cfg_groups.to_dict('records'),
            "teachers": st.session_state.cfg_teachers,
            "rooms": st.session_state.cfg_rooms,
            "limits": st.session_state.cfg_limits.to_dict('records'),
            "curriculum": st.session_state.cfg_curriculum.to_dict('records')
        }
        st.download_button("📥 Зберегти проект", json.dumps(export_data, ensure_ascii=False), "config.json", use_container_width=True)

    st.divider()
    g_col, t_col, r_col = st.columns(3)
    with g_col:
        st.session_state.cfg_groups = st.data_editor(
            st.session_state.cfg_groups, num_rows="dynamic", use_container_width=True,
            column_config={"День практики": st.column_config.SelectboxColumn(options=["Немає"] + active_days)}
        )
    with t_col:
        st.session_state.cfg_teachers = st.text_area("Список викладачів", st.session_state.cfg_teachers, height=200)
    with r_col:
        st.session_state.cfg_rooms = st.text_area("Аудиторії", st.session_state.cfg_rooms, height=200)

# Підготовка списків для Selectbox
active_teachers = [t.strip() for t in st.session_state.cfg_teachers.split("\n") if t.strip()]
active_rooms = [r.strip() for r in st.session_state.cfg_rooms.split("\n") if r.strip()]
active_groups = st.session_state.cfg_groups["Група"].dropna().unique().tolist()

with tab_curriculum:
    st.session_state.cfg_curriculum = st.data_editor(
        st.session_state.cfg_curriculum, num_rows="dynamic", use_container_width=True,
        column_config={
            "Групи": st.column_config.MultiselectColumn(options=active_groups),
            "Викладач": st.column_config.SelectboxColumn(options=active_teachers),
            "Аудиторія": st.column_config.SelectboxColumn(options=active_rooms),
            "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
            "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"])
        }
    )

with tab_limits:
    st.session_state.cfg_limits = st.data_editor(
        st.session_state.cfg_limits, num_rows="dynamic", use_container_width=True,
        column_config={
            "Викладач": st.column_config.SelectboxColumn(options=active_teachers),
            "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + active_days),
            "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + active_slots)
        }
    )

# --- ЯДРО ГЕНЕРАЦІЇ (SOLVER) ---
def generate_schedule():
    model = CpModel()
    groups_data = st.session_state.cfg_groups
    curriculum = st.session_state.cfg_curriculum
    
    # 1. Попередній аналіз занять
    lessons = []
    for idx, row in curriculum.iterrows():
        grps = row["Групи"]
        if not grps or pd.isna(row["Предмет"]): continue
        
        # Скільки всього пар (1 пара = 2 години)
        total_pairs = int(round(row["Годин на семестр"] / 2))
        # Ефективна кількість тижнів для груп
        g_w = [groups_data[groups_data["Група"] == g]["Кількість тижнів"].values[0] for g in grps]
        eff_weeks = int(min(g_w))
        
        for p in range(total_pairs):
            lessons.append({
                "id": len(lessons),
                "groups": grps,
                "subject": row["Предмет"],
                "teacher": row["Викладач"],
                "room": row["Аудиторія"],
                "is_online": row["Формат"] == "Онлайн",
                "is_stream": row["Потокова лекція?"] == "Так",
                "eff_weeks": eff_weeks
            })

    if not lessons: return None, "Навчальний план порожній"

    # 2. Змінні: x[lesson_id, week, day, slot]
    x = {}
    for l in lessons:
        for w in range(l["eff_weeks"]):
            for d in range(days_count):
                for s in range(slots_count):
                    x[l["id"], w, d, s] = model.NewBoolVar(f'l{l["id"]}_w{w}_d{d}_s{s}')

    # 3. Обмеження
    # Кожна пара має відбутися рівно 1 раз за семестр
    for l in lessons:
        model.Add(sum(x[l["id"], w, d, s] for w in range(l["eff_weeks"]) for d in range(days_count) for s in range(slots_count)) == 1)

    # Конфлікти груп
    for g in active_groups:
        for w in range(max_weeks):
            for d in range(days_count):
                for s in range(slots_count):
                    relevant = [x[l["id"], w, d, s] for l in lessons if g in l["groups"] and w < l["eff_weeks"]]
                    if relevant: model.Add(sum(relevant) <= 1)

    # Конфлікти викладачів
    for t in active_teachers:
        for w in range(max_weeks):
            for d in range(days_count):
                for s in range(slots_count):
                    relevant = [x[l["id"], w, d, s] for l in lessons if l["teacher"] == t and w < l["eff_weeks"]]
                    if relevant: model.Add(sum(relevant) <= 1)

    # Конфлікти аудиторій (крім ОНЛАЙН)
    for r in active_rooms:
        if "ОНЛАЙН" in r.upper(): continue
        for w in range(max_weeks):
            for d in range(days_count):
                for s in range(slots_count):
                    relevant = [x[l["id"], w, d, s] for l in lessons if l["room"] == r and w < l["eff_weeks"]]
                    if relevant: model.Add(sum(relevant) <= 1)

    # Дні практики
    for _, grow in groups_data.iterrows():
        if grow["День практики"] in active_days:
            d_idx = active_days.index(grow["День практики"])
            for l in lessons:
                if grow["Група"] in l["groups"]:
                    for w in range(l["eff_weeks"]):
                        for s in range(slots_count):
                            model.Add(x[l["id"], w, d_idx, s] == 0)

    # М'які обмеження (Оптимізація)
    # Мінімізуємо 0 та 4 пари
    penalty_vars = []
    for l in lessons:
        for w in range(l["eff_weeks"]):
            for d in range(days_count):
                # Penalty for 0 slot
                penalty_vars.append(x[l["id"], w, d, 0] * 10)
                # Penalty for late 4 slot
                penalty_vars.append(x[l["id"], w, d, 4] * 20)
    
    model.Minimize(sum(penalty_vars))

    # 4. Вирішення
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    status = solver.Solve(model)

    if status in [OPTIMAL, FEASIBLE]:
        results = []
        for l in lessons:
            for w in range(l["eff_weeks"]):
                for d in range(days_count):
                    for s in range(slots_count):
                        if solver.Value(x[l["id"], w, d, s]):
                            results.append({
                                "Тиждень": w + 1, "День": active_days[d], "Пара": s,
                                "Групи": l["groups"], "Предмет": l["subject"],
                                "Викладач": l["teacher"], "Аудиторія": l["room"],
                                "Онлайн": l["is_online"], "Потік": l["is_stream"]
                            })
        return results, None
    return None, "Неможливо створити розклад з такими обмеженнями"

if st.button("🚀 Згенерувати розклад", type="primary", use_container_width=True):
    with st.spinner("Математичний двигун обчислює оптимальні варіанти..."):
        res, err = generate_schedule()
        if err: st.error(err)
        else:
            st.session_state.schedule_results = res
            st.success(f"Розклад сформовано! Знайдено {len(res)} занять.")

# --- ВІДОБРАЖЕННЯ ТА ЕКСПОРТ ---
with tab_view:
    if st.session_state.schedule_results:
        res = st.session_state.schedule_results
        
        view_mode = st.radio("Режим перегляду", ["По тижнях (Групи)", "Викладачі"], horizontal=True)
        
        if view_mode == "По тижнях (Групи)":
            sel_w = st.selectbox("Оберіть тиждень", range(1, max_weeks + 1))
            
            grid_data = []
            for d in active_days:
                for s_idx in range(slots_count):
                    row = {"День": d, "Час": SLOT_DETAILS[s_idx]["time"]}
                    for g in active_groups:
                        cell = "-"
                        # Перевірка на практику
                        prac_day = st.session_state.cfg_groups[st.session_state.cfg_groups["Група"] == g]["День практики"].values[0]
                        if d == prac_day: cell = "🧬 ПРАКТИКА"
                        else:
                            match = [r for r in res if r["Тиждень"] == sel_w and r["День"] == d and r["Пара"] == s_idx and g in r["Групи"]]
                            if match:
                                m = match[0]
                                loc = "🌐 ONLINE" if m["Онлайн"] else m["Аудиторія"]
                                strm = " 👥" if m["Потік"] else ""
                                cell = f"{m['Предмет']}{strm}\n{m['Викладач']}\n{loc}"
                        row[g] = cell
                    grid_data.append(row)
            
            df_view = pd.DataFrame(grid_data)
            st.dataframe(df_view.style.map(style_schedule_grid), use_container_width=True, height=500)

        # --- EXCEL EXPORT ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            for w in range(1, max_weeks + 1):
                # Спрощена логіка для експорту в Excel
                w_data = [r for r in res if r["Тиждень"] == w]
                pd.DataFrame(w_data).to_excel(writer, sheet_name=f"Тиждень {w}", index=False)
                # Додавання форматування
                workbook = writer.book
                worksheet = writer.sheets[f"Тиждень {w}"]
                wrap_fmt = workbook.add_format({'text_wrap': True, 'align': 'center', 'valign': 'vcenter', 'border': 1})
                worksheet.set_column('A:Z', 20, wrap_fmt)

        st.download_button("📊 Завантажити Excel", output.getvalue(), "Schedule_Full.xlsx", use_container_width=True)
    else:
        st.info("Натисніть 'Згенерувати розклад' для отримання результатів")
