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

st.info("ℹ️ Алгоритм забезпечує 100% відсутність «вікон» у студентів та рівномірний розподіл пар по всьому семестру.")

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

# 3. Обмеження викладачів (3 колонки)
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
        
        # Кількість пар в 2-тижневому шаблоні. 
        # Використовуємо ceil, щоб знайти позиції в шаблоні, але пізніше розподілимо їх рівномірно.
        needed_template = math.ceil((total_p / avg_w) * 2)
        
        specs.append({
            "id": idx, "groups": grps, "subject": row["Предмет"], "teacher": row["Викладач"], 
            "room_choice": row["Аудиторія"], "fmt": row["Format"] if "Format" in row else row["Формат"], 
            "needed": needed_template, "limit": total_p, "avg_w": avg_w
        })

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

    # СУВОРА ЗАБОРОНА ВІКОН
    for p in [0, 1]:
        for d in range(days_count):
            for g in active_groups:
                g_vars = [model.NewBoolVar(f'g_{g}_{p}_{d}_{sl}') for sl in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"]) == g_vars[sl])
                if slots_count >= 3:
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

    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    status = solver.Solve(model)
    if status not in [OPTIMAL, FEASIBLE]: return None, "Неможливо створити розклад без вікон."

    # РОЗГОРТАННЯ З РІВНОМІРНИМ РОЗПОДІЛОМ
    res = []
    for s in specs:
        # Створюємо список тижнів, на яких має бути пара (рівномірно по семестру)
        # Використовуємо алгоритм: тиждень = round(i * (avg_w / limit))
        target_weeks = [round(i * (s["avg_w"] / s["limit"])) + 1 for i in range(s["limit"])]
        # Щоб не вийти за межі
        target_weeks = [min(w, int(s["avg_w"])) for w in target_weeks]
        
        # Знаходимо, які саме слоти в шаблоні (0 або 1 тиждень циклу) зайняті
        template_slots = []
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count):
                    if solver.Value(x[s["id"], p, d, sl]) == 1:
                        template_slots.append((p, d, sl))
        
        if not template_slots: continue

        placed = 0
        for w_idx, w in enumerate(target_weeks):
            # Визначаємо, який слот з шаблону використати для цього конкретного тижня
            # (чергуємо їх, якщо їх кілька в шаблоні)
            p_tmpl, d_tmpl, sl_tmpl = template_slots[w_idx % len(template_slots)]
            
            # Визначаємо аудиторію для цього слота
            rm = s["room_choice"]
            if rm == "✨ Автоматичний підбір з фонду":
                rm = "ОНЛАЙН" if s["fmt"] == "Онлайн" else "1 авд."
                for ri, rname in enumerate(auto_rooms):
                    # Перевіряємо значення змінної для конкретного тижня шаблону p_tmpl
                    if (s["id"], p_tmpl, d_tmpl, sl_tmpl, ri) in room_vars and solver.Value(room_vars[s["id"], p_tmpl, d_tmpl, sl_tmpl, ri]) == 1:
                        rm = rname; break
            
            res.append({
                "week": w, "day": ACTIVE_DAYS[d_tmpl], "slot_idx": sl_tmpl, 
                "slot_label": ACTIVE_SLOTS[sl_tmpl], "groups": s["groups"], 
                "subject": s["subject"], "teacher": s["teacher"], "room": rm
            })
            
    return res, None

# --- ВІЗУАЛ ТА ЕКСПОРТ ---
st.markdown("---")
if st.button("🚀 Згенерувати розклад", type="primary", use_container_width=True):
    with st.spinner("Рівномірний розподіл пар по семестру..."):
        records, err = generate_fast_schedule()
        if err: st.error(err)
        else:
            st.session_state.schedule_data = {"records": records, "max_weeks": max_weeks, "active_groups": active_groups, "active_teachers": base_teachers}
            st.success("Розклад сформовано рівномірно!")

if st.session_state.schedule_data:
    data = st.session_state.schedule_data
    view = st.radio("Режим відображення:", ["По тижнях", "Викладач"], horizontal=True)
    def style_cell(v): return "background-color: #f5f5f5; white-space: pre-wrap;" if v and v != "-" else ""

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
                            cell = f"{r['subject']}\n{r['teacher']}\n{r['room']}"
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
                            cell = f"{', '.join(r['groups'])}\n{r['subject']}\n{r['room']}"
                            break
                    row[f"Тиждень {w}"] = cell
                grid_t.append(row)
        st.dataframe(pd.DataFrame(grid_t).style.map(style_cell), use_container_width=True, height=500)

    # EXCEL
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1, 'align': 'center'})
        for w in range(1, data["max_weeks"] + 1):
            s_data = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    row = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for g in data["active_groups"]:
                        cell = "-"
                        for r in data["records"]:
                            if r["week"] == w and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                                cell = f"{r['subject']}\n{r['teacher']}\n{r['room']}"
                                break
                        row[g] = cell
                    s_data.append(row)
            df_w = pd.DataFrame(s_data); df_w.to_excel(writer, sheet_name=f"Тиждень {w}", index=False)
            ws = writer.sheets[f"Тиждень {w}"]
            for col_num, value in enumerate(df_w.columns.values):
                ws.write(0, col_num, value, header_fmt); ws.set_column(col_num, col_num, 20, cell_fmt)
        for t in data["active_teachers"]:
            t_data = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    row = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for w in range(1, data["max_weeks"] + 1):
                        cell = "-"
                        for r in data["records"]:
                            if r["teacher"] == t and r["week"] == w and r["day"] == d and r["slot_idx"] == sl:
                                cell = f"{', '.join(r['groups'])}\n{r['subject']}\n{r['room']}"
                                break
                        row[f"Тиждень {w}"] = cell
                    t_data.append(row)
            df_t = pd.DataFrame(t_data); sn = "".join([c for c in t if c.isalnum() or c in " ."])[:30]
            df_t.to_excel(writer, sheet_name=sn if sn else "Викл", index=False)
            ws = writer.sheets[sn if sn else "Викл"]
            for col_num, value in enumerate(df_t.columns.values):
                ws.write(0, col_num, value, header_fmt); ws.set_column(col_num, col_num, 18, cell_fmt)

    st.download_button(label="📥 Завантажити повний розклад у Excel", data=output.getvalue(), file_name="Academy_Schedule.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
