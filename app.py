import streamlit as st
import pandas as pd
import io
import json
import math
from collections import defaultdict
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматизованого формування розкладу")

# --- КОНСТАНТИ ТА НАЛАШТУВАННЯ ---
SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:42 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]

SLOT_OPTIONS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]
SLOT_LABELS = [f"{s['label']}\n({s['time']})" for s in SLOT_DETAILS]
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]

# 1. Параметри навчального семестру
st.markdown("### 1. Параметри сітки та комфорту розкладу")
col_w, col_d, col_s = st.columns(3)
with col_w:
    max_weeks = st.number_input("Максимальна кількість тижнів", min_value=1, max_value=25, value=15)
with col_d:
    days_count = st.number_input("Навчальних днів на тиждень", min_value=1, max_value=6, value=5)
with col_s:
    slots_count = st.number_input("Пар на день", min_value=1, max_value=5, value=5)

ACTIVE_DAYS = DAY_NAMES[:days_count]
ACTIVE_SLOTS = SLOT_LABELS[:slots_count]
ACTIVE_SLOT_OPTIONS = SLOT_OPTIONS[:slots_count]

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    avoid_windows = st.checkbox("🚫 Заборонити «вікна» у розкладі студентів", value=True)
with col_opt2:
    avoid_single_teacher = st.checkbox("🚫 Заборонити викладачу мати лише 1 пару на день", value=False)

# Ініціалізація станів
if 'schedule_data' not in st.session_state: st.session_state.schedule_data = None
if 'cfg_groups' not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}])
if 'cfg_teachers' not in st.session_state: st.session_state.cfg_teachers = "Усатенко В.М."
if 'cfg_rooms' not in st.session_state: st.session_state.cfg_rooms = "1 авдиторія\n15 авдиторія\n27-А Комп'ютерний клас\nОНЛАЙН\nСпортзал"
if 'cfg_limits' not in st.session_state:
    st.session_state.cfg_limits = pd.DataFrame([{"Викладач": "Усатенко В.М.", "День тижня": "Вівторок", "Недоступні пари": ["Всі пари"]}])
if 'cfg_curriculum' not in st.session_state:
    st.session_state.cfg_curriculum = pd.DataFrame([{
        "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": "Усатенко В.М.",
        "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція?": "Ні",
        "Аудиторія": "✨ Автоматичний підбір з фонду"
    }])

# --- ФУНКЦІЇ ЗАВАНТАЖЕННЯ ---
def handle_json_upload():
    uploaded_file = st.session_state.get("config_file_uploader")
    if uploaded_file:
        try:
            config = json.load(uploaded_file)
            if "groups" in config: st.session_state.cfg_groups = pd.DataFrame(config["groups"])
            if "teachers" in config: st.session_state.cfg_teachers = config["teachers"]
            if "rooms" in config: st.session_state.cfg_rooms = config["rooms"]
            if "limits" in config: st.session_state.cfg_limits = pd.DataFrame(config["limits"])
            if "curriculum" in config: st.session_state.cfg_curriculum = pd.DataFrame(config["curriculum"])
            st.session_state.upload_success = True
        except: st.session_state.upload_error = "Помилка формату файлу"

st.markdown("### 💾 Збереження та відновлення")
st.file_uploader("📂 Завантажити конфігурацію (.json)", type=["json"], key="config_file_uploader", on_change=handle_json_upload)

# 2. Довідники
st.markdown("### 2. Довідники закладу")
col_g, col_t, col_r = st.columns(3)
with col_g:
    groups_df = st.data_editor(st.session_state.cfg_groups, num_rows="dynamic", use_container_width=True, key="g_ed")
with col_t:
    teachers_text = st.text_area("Список викладачів", value=st.session_state.cfg_teachers, height=150)
with col_r:
    rooms_text = st.text_area("Аудиторний фонд", value=st.session_state.cfg_rooms, height=150)

base_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
base_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]
active_groups = groups_df["Група"].dropna().unique().tolist() if not groups_df.empty else []

# 3. Обмеження
st.markdown("### 3. Обмеження викладачів")
limits_df = st.data_editor(st.session_state.cfg_limits, num_rows="dynamic", column_config={
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + ACTIVE_DAYS),
    "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + ACTIVE_SLOT_OPTIONS)
}, use_container_width=True, key="l_ed")

# 4. Навчальний план
st.markdown("### 4. Навчальний план")
curriculum_df = st.data_editor(st.session_state.cfg_curriculum, num_rows="dynamic", column_config={
    "Групи": st.column_config.MultiselectColumn(options=active_groups),
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
    "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"]),
    "Аудиторія": st.column_config.SelectboxColumn(options=["✨ Автоматичний підбір з фонду"] + base_rooms)
}, use_container_width=True, key="c_ed")

# --- АЛГОРИТМ (ОПТИМІЗОВАНИЙ) ---
def generate_fast_schedule():
    if groups_df.empty or curriculum_df.empty:
        return None, "Заповніть дані груп та плану."

    model = CpModel()
    
    # 1. Підготовка специфікацій занять
    # Ми будуємо розклад на 2-тижневий цикл (парний/непарний)
    specs = []
    group_info = groups_df.set_index("Група").to_dict('index')
    
    for idx, row in curriculum_df.iterrows():
        grps = row.get("Групи", [])
        if not grps or not row.get("Предмет"): continue
        
        # Розрахунок годин: скільки пар на 2 тижні потрібно поставити в шаблон
        total_hours = float(row.get("Годин на семестр", 30))
        total_pairs = math.ceil(total_hours / 2.0)
        
        # Середня кількість пар на 2 тижні
        avg_weeks = group_info.get(grps[0], {}).get("Кількість тижнів", max_weeks)
        pairs_per_2_weeks = math.ceil((total_pairs / avg_weeks) * 2)
        
        specs.append({
            "id": idx,
            "groups": grps,
            "subject": row["Предмет"],
            "teacher": row["Викладач"],
            "room_choice": row["Аудиторія"],
            "fmt": row["Формат"],
            "is_stream": row["Потокова лекція?"] == "Так" or len(grps) > 1,
            "needed_pairs": pairs_per_2_weeks,
            "total_pairs_limit": total_pairs
        })

    # 2. Змінні: x[spec, week_parity, day, slot]
    # week_parity: 0 - перший тиждень, 1 - другий тиждень циклу
    x = {}
    auto_rooms = [r for r in base_rooms if r.upper() not in ["ОНЛАЙН", "СПОРТЗАЛ"]]
    room_vars = {}

    for s in specs:
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count):
                    x[s["id"], p, d, sl] = model.NewBoolVar(f'x_{s["id"]}_{p}_{d}_{sl}')
                    
                    if s["room_choice"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        for r_idx, r_name in enumerate(auto_rooms):
                            room_vars[s["id"], p, d, sl, r_idx] = model.NewBoolVar(f'rm_{s["id"]}_{p}_{d}_{sl}_{r_idx}')

    # 3. Основні обмеження шаблону
    # Кількість пар за цикл
    for s in specs:
        model.Add(sum(x[s["id"], p, d, sl] for p in [0, 1] for d in range(days_count) for sl in range(slots_count)) == s["needed_pairs"])

    # Відсутність конфліктів (Групи, Викладачі) в один момент часу
    for p in [0, 1]:
        for d in range(days_count):
            for sl in range(slots_count):
                # Для кожної групи
                for g_name in active_groups:
                    group_lessons = [x[s["id"], p, d, sl] for s in specs if g_name in s["groups"]]
                    model.Add(sum(group_lessons) <= 1)
                
                # Для кожного викладача
                for t_name in base_teachers:
                    teach_lessons = [x[s["id"], p, d, sl] for s in specs if s["teacher"] == t_name]
                    model.Add(sum(teach_lessons) <= 1)

    # Аудиторії
    for p in [0, 1]:
        for d in range(days_count):
            for sl in range(slots_count):
                for r_idx, r_name in enumerate(auto_rooms):
                    occupants = []
                    for s in specs:
                        # Якщо обрана конкретна ця аудиторія
                        if s["room_choice"] == r_name:
                            occupants.append(x[s["id"], p, d, sl])
                        # Або якщо працює автопідбір
                        elif s["room_choice"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                            model.Add(room_vars[s["id"], p, d, sl, r_idx] <= x[s["id"], p, d, sl])
                            occupants.append(room_vars[s["id"], p, d, sl, r_idx])
                    
                    model.Add(sum(occupants) <= 1)
                
                # Зв'язок: якщо пара є, то одна кімната має бути призначена
                for s in specs:
                    if s["room_choice"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        model.Add(sum(room_vars[s["id"], p, d, sl, ri] for ri in range(len(auto_rooms))) == x[s["id"], p, d, sl])

    # День практики (блокування всього дня для групи)
    for g_name, info in group_info.items():
        prac_day = info.get("День практики", "Немає")
        if prac_day in ACTIVE_DAYS:
            d_idx = ACTIVE_DAYS.index(prac_day)
            for s in specs:
                if g_name in s["groups"]:
                    for p in [0, 1]:
                        for sl in range(slots_count):
                            model.Add(x[s["id"], p, d_idx, sl] == 0)

    # Обмеження викладачів (Unavailable)
    for _, lim in limits_df.iterrows():
        t_n = lim.get("Викладач")
        d_n = lim.get("День тижня")
        u_s = lim.get("Недоступні пари", [])
        if not t_n: continue
        
        target_days = range(days_count) if d_n == "Всі дні" else ([ACTIVE_DAYS.index(d_n)] if d_n in ACTIVE_DAYS else [])
        for d_idx in target_days:
            for sl_idx in range(slots_count):
                if "Всі пари" in u_s or any(f"{sl_idx} пара" in item for item in u_s):
                    for s in specs:
                        if s["teacher"] == t_n:
                            for p in [0, 1]:
                                model.Add(x[s["id"], p, d_idx, sl_idx] == 0)

    # Оптимізація: мінімізація вікон та 4-х пар
    penalty = []
    for p in [0, 1]:
        for d in range(days_count):
            for g_name in active_groups:
                g_vars = [model.NewBoolVar(f'gv_{g_name}_{p}_{d}_{sl}') for sl in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g_name in s["groups"]) == g_vars[sl])
                
                if avoid_windows and slots_count >= 3:
                    for s1 in range(slots_count - 2):
                        # Якщо є пара в s1 та s1+2, то має бути і в s1+1
                        model.Add(g_vars[s1] + g_vars[s1+2] - g_vars[s1+1] <= 1)
            
            # Штраф за 4-ту та 0-ву пару
            for s in specs:
                penalty.append(x[s["id"], p, d, 4] * 10)
                penalty.append(x[s["id"], p, d, 0] * 5)

    model.Minimize(sum(penalty))

    # Розв'язання
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    status = solver.Solve(model)

    if status not in [OPTIMAL, FEASIBLE]:
        return None, "Неможливо створити розклад з такими обмеженнями."

    # 4. Розгортання шаблону на весь семестр
    final_records = []
    for s in specs:
        pairs_placed = 0
        # Йдемо по тижнях
        for w in range(1, max_weeks + 1):
            if pairs_placed >= s["total_pairs_limit"]: break
            
            p_idx = (w - 1) % 2 # Чисельник або знаменник
            for d_idx in range(days_count):
                for sl_idx in range(slots_count):
                    if solver.Value(x[s["id"], p_idx, d_idx, sl_idx]) == 1:
                        if pairs_placed < s["total_pairs_limit"]:
                            # Визначення аудиторії
                            if s["fmt"] == "Онлайн": rm = "ОНЛАЙН"
                            elif s["room_choice"] != "✨ Автоматичний підбір з фонду": rm = s["room_choice"]
                            else:
                                rm = "Не призначено"
                                for ri, rname in enumerate(auto_rooms):
                                    if solver.Value(room_vars[s["id"], p_idx, d_idx, sl_idx, ri]) == 1:
                                        rm = rname; break
                            
                            final_records.append({
                                "week": w, "day": ACTIVE_DAYS[d_idx], "slot_idx": sl_idx,
                                "slot_label": ACTIVE_SLOTS[sl_idx], "groups": s["groups"],
                                "subject": s["subject"], "teacher": s["teacher"],
                                "fmt": s["fmt"], "is_stream": s["is_stream"], "room": rm
                            })
                            pairs_placed += 1
    
    return final_records, None

# --- ВІЗУАЛІЗАЦІЯ ---
if st.button("🚀 Згенерувати розклад", type="primary"):
    with st.spinner("Генерація оптимального шаблону..."):
        records, err = generate_fast_schedule()
        if err: st.error(err)
        else:
            st.success("Розклад сформовано!")
            st.session_state.schedule_data = {
                "records": records, "max_weeks": max_weeks,
                "active_groups": active_groups,
                "active_teachers": base_teachers,
                "groups_df": groups_df
            }

if st.session_state.schedule_data:
    data = st.session_state.schedule_data
    view = st.radio("Режим:", ["По тижнях", "Викладач"], horizontal=True)
    
    def style_cell(val):
        if not val or val == "-": return ""
        if "ОНЛАЙН" in val: return "background-color: #e3f2fd"
        if "ПРАКТИКА" in val: return "background-color: #f3e5f5"
        return "background-color: #f5f5f5"

    if view == "По тижнях":
        w_sel = st.selectbox("Тиждень:", range(1, data["max_weeks"]+1))
        grid = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for g in data["active_groups"]:
                    cell = "-"
                    # Перевірка на практику
                    g_pract = groups_df[groups_df["Група"] == g]["День практики"].values
                    if len(g_pract) > 0 and g_pract[0] == d: cell = "ПРАКТИКА"
                    else:
                        for r in data["records"]:
                            if r["week"] == w_sel and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                                cell = f"{r['subject']}\n{r['teacher']}\n{r['room']}"
                                break
                    row[g] = cell
                grid.append(row)
        st.dataframe(pd.DataFrame(grid).style.map(style_cell), use_container_width=True, height=500)

    # Експорт Excel (спрощений для швидкості)
    if st.button("📥 Завантажити Excel"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            pd.DataFrame(data["records"]).to_excel(writer, sheet_name="Список_пар")
        st.download_button("Скачати файл", output.getvalue(), "schedule.xlsx")
