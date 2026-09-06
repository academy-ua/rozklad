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
    {"num": 0, "label": "0 пара", "time": "12:42 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]
SLOT_LABELS = [f"{s['label']}\n({s['time']})" for s in SLOT_DETAILS]
SLOT_OPTIONS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]

# 1. ПАРАМЕТРИ
st.markdown("### 1. Параметри семестру")
col_w, col_d, col_s = st.columns(3)
with col_w: max_weeks = st.number_input("Тижнів у семестрі", 1, 25, 15)
with col_d: days_count = st.number_input("Днів на тиждень", 1, 6, 5)
with col_s: slots_count = st.number_input("Пар на день", 1, 5, 5)

ACTIVE_DAYS = DAY_NAMES[:days_count]
ACTIVE_SLOTS = SLOT_LABELS[:slots_count]

col_opt1, col_opt2 = st.columns(2)
with col_opt1: avoid_windows = st.checkbox("🚫 Заборонити «вікна»", value=True)
with col_opt2: avoid_single = st.checkbox("🚫 Заборонити викладачу 1 пару на день", value=False)

# Ініціалізація станів
if 'schedule_data' not in st.session_state: st.session_state.schedule_data = None
if 'cfg_groups' not in st.session_state: 
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}])

# 2. ДОВІДНИКИ
st.markdown("### 2. Налаштування")
col_g, col_t, col_r = st.columns(3)
with col_g:
    groups_df = st.data_editor(st.session_state.cfg_groups, num_rows="dynamic", use_container_width=True, key="g_ed")
with col_t:
    teachers_text = st.text_area("Список викладачів (по одному в рядку)", "Усатенко В.М.\nЧерненко В.П.", height=150)
with col_r:
    rooms_text = st.text_area("Аудиторії", "1 авд.\n15 авд.\n27-А Комп.\nОНЛАЙН", height=150)

base_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
base_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]
active_groups = groups_df["Група"].dropna().unique().tolist() if not groups_df.empty else []

# 3. ОБМЕЖЕННЯ ТА ПЛАН
st.markdown("### 3. Навчальний план та обмеження")
curriculum_df = st.data_editor(pd.DataFrame([{
    "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": base_teachers[0] if base_teachers else "",
    "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція?": "Ні",
    "Аудиторія": "✨ Автоматичний підбір з фонду"
}]), num_rows="dynamic", column_config={
    "Групи": st.column_config.MultiselectColumn(options=active_groups),
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "Аудиторія": st.column_config.SelectboxColumn(options=["✨ Автоматичний підбір з фонду"] + base_rooms)
}, use_container_width=True, key="c_ed")

# --- АЛГОРИТМ (ЦИКЛІЧНИЙ ШАБЛОН) ---
def generate_schedule():
    if groups_df.empty or curriculum_df.empty: return None, "Дані не заповнені"
    
    model = CpModel()
    group_info = groups_df.set_index("Група").to_dict('index')
    
    specs = []
    for idx, row in curriculum_df.iterrows():
        grps = row.get("Групи", [])
        if not grps or not row.get("Предмет"): continue
        
        total_pairs = math.ceil(float(row.get("Годин на семестр", 30)) / 2.0)
        avg_w = group_info.get(grps[0], {}).get("Кількість тижнів", max_weeks)
        # Скільки пар треба в 2-тижневому шаблоні (чисельник/знаменник)
        needed_in_template = math.ceil((total_pairs / avg_w) * 2)
        
        specs.append({
            "id": idx, "grps": grps, "sub": row["Предмет"], "teach": row["Викладач"],
            "room": row["Аудиторія"], "fmt": row["Формат"], "needed": needed_in_template, "limit": total_pairs
        })

    # Змінні [spec, parity(0-1), day, slot]
    x = {}
    auto_rooms = [r for r in base_rooms if r.upper() not in ["ОНЛАЙН", "СПОРТЗАЛ"]]
    room_vars = {}

    for s in specs:
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count):
                    x[s["id"], p, d, sl] = model.NewBoolVar(f'x_{s["id"]}_{p}_{d}_{sl}')
                    if s["room"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        for ri in range(len(auto_rooms)):
                            room_vars[s["id"], p, d, sl, ri] = model.NewBoolVar(f'rm_{s["id"]}_{p}_{d}_{sl}_{ri}')

    # Обмеження
    for s in specs:
        model.Add(sum(x[s["id"], p, d, sl] for p in [0, 1] for d in range(days_count) for sl in range(slots_count)) == s["needed"])

    for p in [0, 1]:
        for d in range(days_count):
            for sl in range(slots_count):
                for g in active_groups:
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["grps"]) <= 1)
                for t in base_teachers:
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if s["teach"] == t) <= 1)
                
                for ri in range(len(auto_rooms)):
                    rms = []
                    for s in specs:
                        if s["room"] == auto_rooms[ri]: rms.append(x[s["id"], p, d, sl])
                        elif s["room"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                            model.Add(room_vars[s["id"], p, d, sl, ri] <= x[s["id"], p, d, sl])
                            rms.append(room_vars[s["id"], p, d, sl, ri])
                    model.Add(sum(rms) <= 1)
                
                for s in specs:
                    if s["room"] == "✨ Автоматичний підбір з фонду" and s["fmt"] == "Очно":
                        model.Add(sum(room_vars[s["id"], p, d, sl, ri] for ri in range(len(auto_rooms))) == x[s["id"], p, d, sl])

    # Практика
    for g, info in group_info.items():
        pd_day = info.get("День практики")
        if pd_day in ACTIVE_DAYS:
            di = ACTIVE_DAYS.index(pd_day)
            for s in specs:
                if g in s["grps"]:
                    for p in [0, 1]:
                        for sl in range(slots_count): model.Add(x[s["id"], p, di, sl] == 0)

    # Оптимізація (вікна)
    penalty = []
    for p in [0, 1]:
        for d in range(days_count):
            for g in active_groups:
                g_vars = [model.NewBoolVar('') for _ in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["grps"]) == g_vars[sl])
                if avoid_windows and slots_count >= 3:
                    for sl in range(slots_count-2):
                        model.Add(g_vars[sl] + g_vars[sl+2] - g_vars[sl+1] <= 1)

    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    if solver.Solve(model) not in [OPTIMAL, FEASIBLE]: return None, "Немає розв'язку"

    # Розгортання
    res = []
    for s in specs:
        placed = 0
        for w in range(1, max_weeks + 1):
            if placed >= s["limit"]: break
            p = (w-1) % 2
            for d in range(days_count):
                for sl in range(slots_count):
                    if solver.Value(x[s["id"], p, d, sl]) == 1:
                        if placed < s["limit"]:
                            rm = s["room"]
                            if rm == "✨ Автоматичний підбір з фонду":
                                rm = "ОНЛАЙН" if s["fmt"] == "Онлайн" else "1 авд."
                                for ri, rname in enumerate(auto_rooms):
                                    if (s["id"], p, d, sl, ri) in room_vars and solver.Value(room_vars[s["id"], p, d, sl, ri]) == 1:
                                        rm = rname; break
                            res.append({"w": w, "d": ACTIVE_DAYS[d], "sl": sl, "grps": s["grps"], "sub": s["sub"], "teach": s["teach"], "rm": rm})
                            placed += 1
    return res, None

# --- ВІДОБРАЖЕННЯ ---
if st.button("🚀 Згенерувати розклад", type="primary"):
    records, err = generate_schedule()
    if err: st.error(err)
    else:
        st.session_state.schedule_data = records
        st.success("Готово!")

if st.session_state.schedule_data:
    records = st.session_state.schedule_data
    
    tab1, tab2 = st.tabs(["📅 Розклад по тижнях (Групи)", "👨‍🏫 Розклад викладача (Семестр)"])
    
    with tab1:
        week = st.selectbox("Оберіть тиждень:", range(1, max_weeks + 1))
        week_data = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for g in active_groups:
                    cell = "-"
                    for r in records:
                        if r["w"] == week and r["d"] == d and r["sl"] == sl and g in r["grps"]:
                            cell = f"{r['sub']}\n{r['teach']}\n{rm := r['rm']}"
                            break
                    row[g] = cell
                week_data.append(row)
        df_week = pd.DataFrame(week_data)
        st.dataframe(df_week.style.map(lambda x: "white-space: pre-wrap;"), use_container_width=True)

    with tab2:
        t_sel = st.selectbox("Оберіть викладача:", base_teachers)
        t_data = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for w in range(1, max_weeks + 1):
                    cell = "-"
                    for r in records:
                        if r["teach"] == t_sel and r["w"] == w and r["d"] == d and r["sl"] == sl:
                            cell = f"{', '.join(r['grps'])}\n{r['sub']}\n{r['rm']}"
                            break
                    row[f"Тиждень {w}"] = cell
                t_data.append(row)
        df_teacher = pd.DataFrame(t_data)
        st.dataframe(df_teacher.style.map(lambda x: "white-space: pre-wrap;"), use_container_width=True)

    # ЕКСПОРТ EXCEL
    st.markdown("### 📥 Експорт")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        workbook = writer.book
        fmt = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
        
        # Листи тижнів
        for w in range(1, max_weeks + 1):
            w_rows = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    r_dict = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for g in active_groups:
                        val = "-"
                        for r in records:
                            if r["w"] == w and r["d"] == d and r["sl"] == sl and g in r["grps"]:
                                val = f"{r['sub']}\n{r['teach']}\n{r['rm']}"
                                break
                        r_dict[g] = val
                    w_rows.append(r_dict)
            df_w = pd.DataFrame(w_rows)
            df_w.to_excel(writer, index=False, sheet_name=f"Тиждень {w}")
            writer.sheets[f"Тиждень {w}"].set_column(0, 100, 25, fmt)

        # Листи викладачів
        for t in base_teachers:
            t_rows = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    r_dict = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for w in range(1, max_weeks + 1):
                        val = "-"
                        for r in records:
                            if r["teach"] == t and r["w"] == w and r["d"] == d and r["sl"] == sl:
                                val = f"{', '.join(r['grps'])}\n{r['sub']}\n{r['rm']}"
                                break
                        r_dict[f"Т{w}"] = val
                    t_rows.append(r_dict)
            df_t = pd.DataFrame(t_rows)
            sheet_name = t[:31] # Обмеження Excel
            df_t.to_excel(writer, index=False, sheet_name=sheet_name)
            writer.sheets[sheet_name].set_column(0, 100, 20, fmt)

    st.download_button("📥 Завантажити повний розклад (Excel)", buffer.getvalue(), "academy_schedule.xlsx")
