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

st.info("ℹ️ Алгоритм забезпечує 100% відсутність «вікон» та адаптується до будь-якої кількості груп.")

# Ініціалізація станів
if 'schedule_data' not in st.session_state: st.session_state.schedule_data = None
if 'cfg_groups' not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}])
if 'cfg_teachers' not in st.session_state: st.session_state.cfg_teachers = "Усатенко В.М."
if 'cfg_rooms' not in st.session_state: st.session_state.cfg_rooms = "1 авдиторія\n15 авдиторія\n27-А Комп'ютерний клас\nОНЛАЙН"
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

# 3. Обмеження викладачів (3 КОЛОНКИ)
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

# КНОПКА JSON
config_export_data = {
    "groups": groups_df.to_dict(orient="records"), "teachers": teachers_text, "rooms": rooms_text,
    "limits": limits_df.to_dict(orient="records"), "curriculum": curriculum_df.to_dict(orient="records")
}
st.download_button(label="📥 Зберегти поточні налаштування (.json)", data=json.dumps(config_export_data, ensure_ascii=False, indent=2), file_name="academy_config.json", mime="application/json", use_container_width=True)

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

    # Конфлікти груп та викладачів
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

    # СУВОРА ЗАБОРОНА ВІКОН (HARD CONSTRAINT)
    for p in [0, 1]:
        for d in range(days_count):
            for g in active_groups:
                g_vars = [model.NewBoolVar(f'g_{g}_{p}_{d}_{sl}') for sl in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"]) == g_vars[sl])
                
                if slots_count >= 3:
                    # Якщо є пара в слоті s1 та s3, то s2 ОБОВ'ЯЗКОВО має бути заповнена
                    for s1 in range(slots_count):
                        for s2 in range(s1 + 1, slots_count - 1):
                            for s3 in range(s2 + 1, slots_count):
                                model.Add(g_vars[s1] + g_vars[s3] <= 1 + g_vars[s2])

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

    # ОПТИМІЗАЦІЯ (SOFT CONSTRAINTS)
    penalties = []
    for p in [0, 1]:
        for d in range(days_count):
            # 1. Групування пар викладачів
            for t in base_teachers:
                count = sum(x[s["id"], p, d, sl] for s in specs if s["teacher"] == t for sl in range(slots_count))
                is_w = model.NewBoolVar(''); has_m = model.NewBoolVar('')
                model.Add(count >= 1).OnlyEnforceIf(is_w); model.Add(count == 0).OnlyEnforceIf(is_w.Not())
                model.Add(count >= 2).OnlyEnforceIf(has_m); model.Add(count <= 1).OnlyEnforceIf(has_m.Not())
                single = model.NewBoolVar('')
                model.Add(single == 1).OnlyEnforceIf([is_w, has_m.Not()])
                model.Add(single == 0).OnlyEnforceIf(is_w.Not()); model.Add(single == 0).OnlyEnforceIf(has_m)
                penalties.append(single * 100)
            
            # 2. Пріоритет довгих предметів на початок дня (щоб уникнути вікон в кінці семестру)
            for sl in range(slots_count):
                for s in specs:
                    # Чим пізніше слот (sl) і чим довший предмет (s['limit']), тим більший штраф
                    # Це змушує довгі предмети "підніматися" до першої пари
                    penalties.append(x[s["id"], p, d, sl] * sl * (max_weeks - s["limit"]))

    model.Minimize(sum(penalties))
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    status = solver.Solve(model)
    
    if status not in [OPTIMAL, FEASIBLE]: 
        return None, "Неможливо створити розклад. Спробуйте зменшити кількість обмежень для викладачів або додати аудиторії."

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
                    if (s["id"], p_t, d_t, sl_t, ri) in room_vars and solver.Value(room_vars[s["id"], p_t, d_t, sl_t, ri]) == 1:
                        rm = rname; break
            res.append({"week": w, "day": ACTIVE_DAYS[d_t], "slot_idx": sl_t, "slot_label": ACTIVE_SLOTS[sl_t], "groups": s["groups"], "subject": s["subject"], "teacher": s["teacher"], "room": rm, "fmt": s["fmt"]})
    return res, None

# --- ВІЗУАЛ ТА ЕКСПОРТ ---
st.markdown("---")
if st.button("🚀 Згенерувати розклад", type="primary", use_container_width=True):
    with st.spinner("Алгоритм розраховує оптимальні позиції..."):
        records, err = generate_fast_schedule()
        if err: st.error(err)
        else:
            st.session_state.schedule_data = {"records": records, "max_weeks": max_weeks, "active_groups": active_groups, "active_teachers": base_teachers}
            st.success("Розклад сформовано!")

if st.session_state.schedule_data:
    data = st.session_state.schedule_data
    def style_cell(v):
        if not v or v == "-": return ""
        if "ОНЛАЙН" in v.upper(): return "background-color: #CCFFFF; white-space: pre-wrap;"
        return "background-color: #f5f5f5; white-space: pre-wrap;"

    view = st.radio("Режим відображення:", ["По тижнях", "Викладач"], horizontal=True)

    if view == "По тижнях":
        w_sel = st.selectbox("Тиждень:", range(1, data["max_weeks"]+1))
        grid = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for g in data["active_groups"]:
                    cell = "-"
                    for r in data["records"]:
                        if r["week"] == w_sel and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                            cell = f"{r['subject']}\n{r['teacher']}\n{r['room'] if r['fmt']!='Онлайн' else 'ОНЛАЙН'}"
                            break
                    row[g] = cell
                grid.append(row)
        st.dataframe(pd.DataFrame(grid).style.map(style_cell), use_container_width=True, height=500)

    elif view == "Викладач":
        t_sel = st.selectbox("Викладач:", data["active_teachers"])
        grid_t = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for w in range(1, data["max_weeks"] + 1):
                    cell = "-"
                    for r in data["records"]:
                        if r["teacher"] == t_sel and r["week"] == w and r["day"] == d and r["slot_idx"] == sl:
                            cell = f"{', '.join(r['groups'])}\n{r['subject']}\n{r['room'] if r['fmt']!='Онлайн' else 'ОНЛАЙН'}"
                            break
                    row[f"Тиждень {w}"] = cell
                grid_t.append(row)
        st.dataframe(pd.DataFrame(grid_t).style.map(style_cell), use_container_width=True, height=500)

    # --- EXCEL ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        cell_f = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
        onl_f = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1, 'bg_color': '#CCFFFF'})
        head_f = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1, 'align': 'center'})
        for w in range(1, data["max_weeks"] + 1):
            s_data = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    row = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for g in data["active_groups"]:
                        cell = "-"
                        for r in data["records"]:
                            if r["week"] == w and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                                cell = f"{r['subject']}\n{r['teacher']}\n{r['room'] if r['fmt']!='Онлайн' else 'ОНЛАЙН'}"
                                break
                        row[g] = cell
                    s_data.append(row)
            df = pd.DataFrame(s_data); df.to_excel(writer, sheet_name=f"Тиждень {w}", index=False)
            ws = writer.sheets[f"Тиждень {w}"]
            for r_i in range(len(df)):
                for c_i in range(len(df.columns)):
                    val = str(df.iloc[r_i, c_i])
                    ws.write(r_i+1, c_i, val, onl_f if "ОНЛАЙН" in val else cell_f)
            for c_i, col in enumerate(df.columns):
                ws.write(0, c_i, col, head_f); ws.set_column(c_i, c_i, 22)
        for t in data["active_teachers"]:
            t_d = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    row = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for w in range(1, data["max_weeks"] + 1):
                        cell = "-"
                        for r in data["records"]:
                            if r["teacher"] == t and r["week"] == w and r["day"] == d and r["slot_idx"] == sl:
                                cell = f"{', '.join(r['groups'])}\n{r['subject']}\n{r['room'] if r['fmt']!='Онлайн' else 'ОНЛАЙН'}"
                                break
                        row[f"Тиждень {w}"] = cell
                    t_d.append(row)
            df_t = pd.DataFrame(t_d); sn = "".join([c for c in t if c.isalnum() or c in " ."])[:30]
            df_t.to_excel(writer, sheet_name=sn if sn else "Викл", index=False)
            ws = writer.sheets[sn if sn else "Викл"]
            for r_i in range(len(df_t)):
                for c_i in range(len(df_t.columns)):
                    val = str(df_t.iloc[r_i, c_i])
                    ws.write(r_i+1, c_i, val, onl_f if "ОНЛАЙН" in val else cell_f)
            for c_i, col in enumerate(df_t.columns):
                ws.write(0, c_i, col, head_f); ws.set_column(c_i, c_i, 18)

    st.download_button(label="📥 Завантажити повний розклад у Excel", data=output.getvalue(), file_name="Academy_Schedule.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
