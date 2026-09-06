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

st.info("ℹ️ Кольори: Блакитний — ОНЛАЙН, Світло-зелений — ПОТІК (Лекція). Пріоритет: пари та лекції спочатку.")

# Ініціалізація станів
if 'schedule_data' not in st.session_state: st.session_state.schedule_data = None
if 'cfg_groups' not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}])
if 'cfg_teachers' not in st.session_state: st.session_state.cfg_teachers = "Усатенко В.М."
if 'cfg_rooms' not in st.session_state: st.session_state.cfg_rooms = "1 авдиторія\n15 авдиторія\n27-А Комп'ютерний клас\nОНЛАЙН"

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

st.markdown("### 💾 Збереження та відновлення даних")
st.file_uploader("📂 Завантажити .json конфігурацію", type=["json"], key="config_file_uploader", on_change=handle_json_upload)

# 2. Довідники закладу
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
if 'cfg_limits' not in st.session_state:
    st.session_state.cfg_limits = pd.DataFrame([{"Викладач": base_teachers[0] if base_teachers else "", "День тижня": "Вівторок", "Недоступні пари": ["Всі пари"]}])

limits_df = st.data_editor(st.session_state.cfg_limits, num_rows="dynamic", column_config={
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + ACTIVE_DAYS),
    "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + ACTIVE_SLOT_OPTIONS)
}, use_container_width=True, key="l_ed")

# 4. Навчальний план дисциплін
st.markdown("### 4. Навчальний план")
if 'cfg_curriculum' not in st.session_state:
    st.session_state.cfg_curriculum = pd.DataFrame([{
        "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": base_teachers[0] if base_teachers else "",
        "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція?": "Ні", "Аудиторія": "✨ Автоматичний підбір з фонду"
    }])

curriculum_df = st.data_editor(st.session_state.cfg_curriculum, num_rows="dynamic", column_config={
    "Групи": st.column_config.MultiselectColumn(options=active_groups),
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
    "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"]),
    "Аудиторія": st.column_config.SelectboxColumn(options=["✨ Автоматичний підбір з фонду"] + base_rooms)
}, use_container_width=True, key="c_ed")

config_export_data = {
    "groups": groups_df.to_dict(orient="records"), "teachers": teachers_text, "rooms": rooms_text,
    "limits": limits_df.to_dict(orient="records"), "curriculum": curriculum_df.to_dict(orient="records")
}
st.download_button(label="📥 Зберегти введені налаштування у .json", data=json.dumps(config_export_data, ensure_ascii=False, indent=2), file_name="rozklad_config.json", mime="application/json", use_container_width=True)

# --- АЛГОРИТМ ---
def generate_fast_schedule():
    if groups_df.empty or curriculum_df.empty: return None, "Дані не заповнені."
    model = CpModel()
    specs = []
    group_info = groups_df.set_index("Група").to_dict('index')
    
    for idx, row in curriculum_df.iterrows():
        grps = row.get("Групи", [])
        if not grps or not row.get("Предмет"): continue
        total_p = math.ceil(float(row.get("Годин на семестр", 30)) / 2.0)
        avg_w = group_info.get(grps[0], {}).get("Кількість тижнів", max_weeks)
        needed = math.ceil((total_p / avg_w) * 2)
        specs.append({
            "id": idx, "groups": grps, "subject": row["Предмет"], "teacher": row["Викладач"],
            "room_choice": row["Аудиторія"], "fmt": row["Формат"], "is_stream": row["Потокова лекція?"] == "Так",
            "needed": needed, "limit": total_p, "avg_w": avg_w
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

    # Hard Constraints
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

    # Заборона вікон
    for p in [0, 1]:
        for d in range(days_count):
            for g in active_groups:
                g_vars = [model.NewBoolVar(f'gv_{g}_{p}_{d}_{sl}') for sl in range(slots_count)]
                for sl in range(slots_count):
                    model.Add(sum(x[s["id"], p, d, sl] for s in specs if g in s["groups"]) == g_vars[sl])
                if slots_count >= 3:
                    for s1 in range(slots_count):
                        for s2 in range(s1 + 1, slots_count - 1):
                            for s3 in range(s2 + 1, slots_count):
                                model.Add(g_vars[s1] + g_vars[s3] <= 1 + g_vars[s2])

    # Обмеження вчителів
    for _, lim in limits_df.iterrows():
        t_n, d_n, u_s = lim.get("Викладач"), lim.get("День тижня"), lim.get("Недоступні пари", [])
        if not t_n: continue
        target_days = range(days_count) if d_n == "Всі дні" else ([ACTIVE_DAYS.index(d_n)] if d_n in ACTIVE_DAYS else [])
        for di in target_days:
            for sli in range(slots_count):
                if "Всі пари" in u_s or any(f"{sli} пара" in str(item) for item in u_s):
                    for s in specs:
                        if s["teacher"] == t_n:
                            for p_ parity in [0, 1]: model.Add(x[s["id"], p_parity, di, sli] == 0)

    # ОПТИМІЗАЦІЯ (ШТРАФИ ТА БОНУСИ)
    penalties = []
    # 1. Бонус за подвійні пари
    for s in specs:
        for p in [0, 1]:
            for d in range(days_count):
                for sl in range(slots_count - 1):
                    is_double = model.NewBoolVar(f'dbl_{s["id"]}_{p}_{d}_{sl}')
                    model.Add(x[s["id"],p,d,sl] + x[s["id"],p,d,sl+1] == 2).OnlyEnforceIf(is_double)
                    penalties.append(is_double * -60)

    # 2. Пріоритет лекцій перед практиками
    subj_teach_map = defaultdict(list)
    for s in specs: subj_teach_map[(s["subject"], s["teacher"])].append(s)
    for (subj, teach), s_list in subj_teach_map.items():
        lecture = next((s for s in s_list if s["is_stream"]), None)
        practicals = [s for s in s_list if not s["is_stream"]]
        if lecture and practicals:
            for prac in practicals:
                for p in [0, 1]:
                    for d1 in range(days_count):
                        for sl1 in range(slots_count):
                            for d2 in range(days_count):
                                for sl2 in range(slots_count):
                                    if (d1 * slots_count + sl1) > (d2 * slots_count + sl2):
                                        bad_order = model.NewBoolVar('')
                                        model.Add(x[lecture["id"], p, d1, sl1] + x[prac["id"], p, d2, sl2] == 2).OnlyEnforceIf(bad_order)
                                        penalties.append(bad_order * 150)

    # 3. Штраф за одиноку пару
    for t in base_teachers:
        for p in [0, 1]:
            for d in range(days_count):
                tc = sum(x[s["id"], p, d, sl] for s in specs if s["teacher"] == t for sl in range(slots_count))
                single = model.NewBoolVar('')
                model.Add(tc == 1).OnlyEnforceIf(single)
                penalties.append(single * 120)

    model.Minimize(sum(penalties))
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)
    
    if status not in [OPTIMAL, FEASIBLE]: return None, "Неможливо знайти рішення. Зменште обмеження."

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
            res.append({
                "week": w, "day": ACTIVE_DAYS[d_t], "slot_idx": sl_t, "slot_label": ACTIVE_SLOTS[sl_t],
                "groups": s["groups"], "subject": s["subject"], "teacher": s["teacher"], 
                "room": rm, "fmt": s["fmt"], "is_stream": s["is_stream"]
            })
    return res, None

# --- ВІЗУАЛІЗАЦІЯ ---
st.markdown("---")
if st.button("🚀 Згенерувати розклад", type="primary", use_container_width=True):
    with st.spinner("Алгоритм оптимізує потоки та пари..."):
        records, err = generate_fast_schedule()
        if err: st.error(err)
        else:
            st.session_state.schedule_data = {"records": records, "max_weeks": max_weeks, "active_groups": active_groups, "active_teachers": base_teachers}
            st.success("Готово!")

if st.session_state.schedule_data:
    data = st.session_state.schedule_data
    
    def style_cell(v):
        if not v or v == "-": return ""
        v_up = v.upper()
        if "ОНЛАЙН" in v_up: return "background-color: #CCFFFF; white-space: pre-wrap;"
        if "(ПОТІК)" in v_up: return "background-color: #D5E8D4; white-space: pre-wrap;"
        return "background-color: #f5f5f5; white-space: pre-wrap;"

    view = st.radio("Режим перегляду:", ["📅 По тижнях (Групи)", "👨‍🏫 Розклад викладача"], horizontal=True)

    if view == "📅 По тижнях (Групи)":
        w_sel = st.selectbox("Оберіть тиждень:", range(1, data["max_weeks"]+1))
        grid = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for g in data["active_groups"]:
                    cell = "-"
                    for r in data["records"]:
                        if r["week"] == w_sel and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                            loc = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                            stream_tag = "\n(ПОТІК)" if r["is_stream"] else ""
                            cell = f"{r['subject']}{stream_tag}\n{r['teacher']}\n{loc}"
                            break
                    row[g] = cell
                grid.append(row)
        st.dataframe(pd.DataFrame(grid).style.map(style_cell), use_container_width=True, height=500)

    elif view == "👨‍🏫 Розклад викладача":
        t_sel = st.selectbox("Викладач:", data["active_teachers"])
        grid_t = []
        for d in ACTIVE_DAYS:
            for sl in range(slots_count):
                row = {"День": d, "Пара": ACTIVE_SLOTS[sl]}
                for w in range(1, data["max_weeks"] + 1):
                    cell = "-"
                    for r in data["records"]:
                        if r["teacher"] == t_sel and r["week"] == w and r["day"] == d and r["slot_idx"] == sl:
                            loc = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                            stream_tag = "\n(ПОТІК)" if r["is_stream"] else ""
                            cell = f"{', '.join(r['groups'])}\n{r['subject']}{stream_tag}\n{loc}"
                            break
                    row[f"Т{w}"] = cell
                grid_t.append(row)
        st.dataframe(pd.DataFrame(grid_t).style.map(style_cell), use_container_width=True, height=500)

    # EXCEL EXPORT
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book
        cell_f = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
        onl_f = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1, 'bg_color': '#CCFFFF'})
        str_f = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1, 'bg_color': '#D5E8D4'})
        head_f = wb.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1, 'align': 'center'})

        for w in range(1, data["max_weeks"] + 1):
            s_data = []
            for d in ACTIVE_DAYS:
                for sl in range(slots_count):
                    row_d = {"День": d, "Пара": ACTIVE_SLOTS[sl].replace("\n", " ")}
                    for g in data["active_groups"]:
                        val = "-"
                        for r in data["records"]:
                            if r["week"] == w and r["day"] == d and r["slot_idx"] == sl and g in r["groups"]:
                                s_t = "\n(ПОТІК)" if r["is_stream"] else ""
                                val = f"{r['subject']}{s_t}\n{r['teacher']}\n{'ОНЛАЙН' if r['fmt']=='Онлайн' else r['room']}"
                                break
                        row_d[g] = val
                    s_data.append(row_d)
            df_w = pd.DataFrame(s_data); df_w.to_excel(writer, sheet_name=f"Тиждень {w}", index=False)
            ws = writer.sheets[f"Тиждень {w}"]
            for r_idx, row_vals in enumerate(s_data):
                for c_idx, col_name in enumerate(df_w.columns):
                    v = str(row_vals.get(col_name, "-"))
                    f = cell_f
                    if "ОНЛАЙН" in v.upper(): f = onl_f
                    elif "(ПОТІК)" in v.upper(): f = str_f
                    ws.write(r_idx + 1, c_idx, v, f)
            for c_idx in range(len(df_w.columns)): ws.write(0, c_idx, df_w.columns[c_idx], head_f); ws.set_column(c_idx, c_idx, 22)

    st.download_button(label="📥 Завантажити повний розклад Excel", data=output.getvalue(), file_name="Academy_Schedule_Colored.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
