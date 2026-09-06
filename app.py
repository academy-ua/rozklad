import streamlit as st
import pandas as pd
import io
import json
import math
from collections import defaultdict
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматизованого формування розкладу")

# --- КОНСТАНТИ ---
SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:45 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]

SLOT_LABELS = [f"{s['label']}\n({s['time']})" for s in SLOT_DETAILS]
SLOT_OPTIONS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]

# 1. Параметри
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

st.info("ℹ️ Алгоритм балансує навантаження студентів: пари розподіляються рівномірно по днях без «вікон».")

# Ініціалізація станів
if 'schedule_data' not in st.session_state: st.session_state.schedule_data = None
if 'cfg_groups' not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}])
if 'cfg_teachers' not in st.session_state: st.session_state.cfg_teachers = "Усатенко В.М."
if 'cfg_rooms' not in st.session_state: st.session_state.cfg_rooms = "1 авдиторія\n15 авдиторія\n27-А Комп'ютерний клас\nОНЛАЙН"
if 'cfg_limits' not in st.session_state:
    st.session_state.cfg_limits = pd.DataFrame([{"Викладач": "Усатенко В.М.", "День тижня": "Вівторок", "Недоступні пари": ["Всі пари"]}])

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
        except: st.session_state.upload_error = "Помилка файлу"

st.markdown("### 💾 Відновлення даних")
st.file_uploader("📂 Завантажити попередньо збережений .json", type=["json"], key="config_file_uploader", on_change=handle_json_upload)

# 2. Довідники
st.markdown("### 2. Довідники закладу")
col_g, col_t, col_r = st.columns(3)
with col_g:
    groups_df = st.data_editor(st.session_state.cfg_groups, num_rows="dynamic", use_container_width=True, key="g_ed")
with col_t:
    teachers_text = st.text_area("Список викладачів", value=st.session_state.cfg_teachers, height=150)
with col_r:
    rooms_text = st.text_area("Аудиторії", value=st.session_state.cfg_rooms, height=150)

base_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
base_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]
active_groups = groups_df["Група"].dropna().unique().tolist() if not groups_df.empty else []

# 3. Обмеження викладачів
st.markdown("### 3. Обмеження викладачів")
limits_df = st.data_editor(st.session_state.cfg_limits, num_rows="dynamic", column_config={
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + ACTIVE_DAYS),
    "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + ACTIVE_SLOT_OPTIONS)
}, use_container_width=True, key="l_ed")

# 4. Навчальний план
st.markdown("### 4. Навчальний план")
if 'cfg_curriculum' not in st.session_state:
    st.session_state.cfg_curriculum = pd.DataFrame([{
        "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": "Усатенко В.М.",
        "Годин на семестр": 30, "Формат": "Очно", "Аудиторія": "✨ Автоматичний підбір з фонду"
    }])

curriculum_df = st.data_editor(st.session_state.cfg_curriculum, num_rows="dynamic", column_config={
    "Групи": st.column_config.MultiselectColumn(options=active_groups),
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
    "Аудиторія": st.column_config.SelectboxColumn(options=["✨ Автоматичний підбір з фонду"] + base_rooms)
}, use_container_width=True, key="c_ed")

# КНОПКА JSON
config_export_data = {
    "groups": groups_df.to_dict(orient="records"), "teachers": teachers_text, "rooms": rooms_text,
    "limits": limits_df.to_dict(orient="records"), "curriculum": curriculum_df.to_dict(orient="records")
}
st.download_button(label="📥 Зберегти поточні налаштування у файл (.json)", data=json.dumps(config_export_data, ensure_ascii=False, indent=2), file_name="academy_config.json", mime="application/json", use_container_width=True)

# --- АЛГОРИТМ ---
def generate_fast_schedule():
    if groups_df.empty or curriculum_df.empty: return None, "Заповніть дані."
    model = CpModel()
    specs = []
    group_info = groups_df.set_index("Група").to_dict('index')
    
    for idx, row in curriculum_df.iterrows():
        grps = row.get("Групи", [])
        if not grps or not row.get("Предмет"): continue
        total_p = math.ceil(float(row.get("Годин на семестр", 30)) / 2.0)
        avg_w = group_info.get(grps[0], {}).get("Кількість тижнів", max_weeks)
        needed = math.ceil((total_p / avg_w) * 2)
        specs.append({"id": idx, "groups": grps, "subject": row["Предмет"], "teacher": row["Викладач"], "room_choice": row["Аудиторія"], "fmt": row["Формат"], "needed": needed, "limit": total_p, "avg_w": avg_w})

    x = {}
    auto_rooms = [r for r in base_rooms if r.upper() not in ["ОНЛАЙН", "СПОРТЗАЛ"]]
    room_vars = {}

    for s in specs:
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count):
                    x[s["id"], p, d, sl] = model.NewBoolVar(f'x_{s["id"]}_{p}_{d}_{sl}')
                    if s["room_choice"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        for ri, rname in enumerate(auto_rooms):
                            room_vars[s["id"], p, d, sl, ri] = model.NewBoolVar(f'rm_{s["id"]}_{p}_{d}_{sl}_{ri}')

    for s in specs:
        model.Add(sum(x[s["id"], p, d, sl] for p in [0, 1] for d in range(days_count) for sl in range(slots_count)) == s["needed"])

    # 1. КОНФЛІКТИ ТА АУДИТОРІЇ
    for p in [0, 1]:
        for d in range(days_count):
            for sl in range(slots_count):
                for g in active_groups:
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"]) <= 1)
                for t in base_teachers:
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if s["teacher"] == t) <= 1)
                for ri, rname in enumerate(auto_rooms):
                    occ = [room_vars[s["id"], p, d, sl, ri] for s in specs if (s["id"], p, d, sl, ri) in room_vars]
                    occ += [x[s["id"], p, d, sl] for s in specs if s["room_choice"] == rname]
                    model.Add(sum(occ) <= 1)
                for s in specs:
                    if s["room_choice"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        model.Add(sum(room_vars[s["id"], p, d, sl, ri] for ri in range(len(auto_rooms))) == x[s["id"], p, d, sl])

    # 2. СУВОРА ЗАБОРОНА ВІКОН ТА БАЛАНСУВАННЯ СТУДЕНТІВ
    for p in [0, 1]:
        for d in range(days_count):
            for g in active_groups:
                g_vars = [model.NewBoolVar(f'g_{g}_{p}_{d}_{sl}') for sl in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"]) == g_vars[sl])
                
                # Жорстка заборона вікон
                if slots_count >= 3:
                    for s1 in range(slots_count):
                        for s2 in range(s1 + 1, slots_count - 1):
                            for s3 in range(s2 + 1, slots_count):
                                model.Add(g_vars[s1] + g_vars[s3] <= 1 + g_vars[s2])

                # Уникнення однієї пари для студента в день (щоб не їздити дарма)
                day_total = sum(g_vars)
                is_working = model.NewBoolVar(f'g_work_{g}_{p}_{d}')
                model.Add(day_total >= 1).OnlyEnforceIf(is_working)
                model.Add(day_total == 0).OnlyEnforceIf(is_working.Not())
                model.Add(day_total >= 2).OnlyEnforceIf(is_working) # Якщо день робочий, мінімум 2 пари

    # Рівномірний розподіл навантаження студента по днях
    for g in active_groups:
        total_p_for_g = sum(s["needed"] for s in specs if g in s["groups"])
        ideal_per_day = total_p_for_g // (days_count * 2)
        for p in [0, 1]:
            for d in range(days_count):
                day_total = sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"] for sl in range(slots_count))
                model.Add(day_total >= ideal_per_day)
                model.Add(day_total <= ideal_per_day + 2)

    # 3. ОБМЕЖЕННЯ ВИКЛАДАЧІВ (3 колонки)
    for _, lim in limits_df.iterrows():
        t_n, d_n, u_s = lim.get("Викладач"), lim.get("День тижня"), lim.get("Недоступні пари", [])
        if not t_n: continue
        target_days = range(days_count) if d_n == "Всі дні" else ([ACTIVE_DAYS.index(d_n)] if d_n in ACTIVE_DAYS else [])
        for di in target_days:
            for sli in range(slots_count):
                if "Всі пари" in u_s or any(f"{sli} пара" in str(item) for item in u_s):
                    for s in specs:
                        if s["teacher"] == t_n:
                            for p in [0, 1]: model.Add(x[s["id"], p, di, sli] == 0)

    # ОПТИМІЗАЦІЯ
    penalties = []
    for p in [0, 1]:
        for d in range(days_count):
            for t in base_teachers:
                count = sum(x[s["id"], p, d, sl] for s in specs if s["teacher"] == t for sl in range(slots_count))
                single = model.NewBoolVar('')
                model.Add(count == 1).OnlyEnforceIf(single)
                model.Add(count != 1).OnlyEnforceIf(single.Not())
                penalties.append(single * 150)
            
            for s in specs:
                penalties.append(x[s["id"], p, d, sl] * sl) # Пріоритет першим парам

    model.Minimize(sum(penalties))
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 25.0
    status = solver.Solve(model)
    
    if status not in [OPTIMAL, FEASIBLE]: 
        return None, "Неможливо збалансувати розклад. Спробуйте додати робочий день або зменшити кількість обмежень."

    # РОЗГОРТАННЯ
    res = []
    for s in specs:
        target_weeks = [round(i * (s["avg_w"] / s["limit"])) + 1 for i in range(s["limit"])]
        target_weeks = [min(w, int(s["avg_w"])) for w in target_weeks]
        tmpl = []
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count):
                    if solver.Value(x[s["id"], p, d, sl]) == 1: tmpl.append((p, d, sl))
        
        if not tmpl: continue
        for idx, w in enumerate(target_weeks):
            p_t, d_t, sl_t = tmpl[idx % len(tmpl)]
            rm = s["room_choice"]
            if rm == "✨ Автоматичний підбір з фонду":
                rm = "ОНЛАЙН" if s["fmt"] == "Онлайн" else "1 авд."
                for ri, rname in enumerate(auto_rooms):
                    if (s["id"], p_t, d_t
