import streamlit as st
import pandas as pd
import io
import json
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматизованого формування розкладу")

# Точні часові слоти академії
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

# Синхронізація зміни кількості тижнів з таблицею
def on_max_weeks_change():
    new_max = st.session_state.get("max_weeks_input", 15)
    if 'cfg_groups' in st.session_state and isinstance(st.session_state.cfg_groups, pd.DataFrame):
        if "Кількість тижнів" in st.session_state.cfg_groups.columns:
            st.session_state.cfg_groups["Кількість тижнів"] = st.session_state.cfg_groups["Кількість тижнів"].apply(
                lambda x: min(int(x), new_max) if pd.notnull(x) else new_max
            )
    if "groups_editor" in st.session_state:
        del st.session_state["groups_editor"]

# 1. Параметри навчального семестру
st.markdown("### 1. Параметри сітки розкладу")
col_w, col_d, col_s = st.columns(3)
with col_w:
    max_weeks = st.number_input(
        "Максимальна кількість тижнів у семестрі", 
        min_value=1, max_value=25, value=15, 
        key="max_weeks_input",
        on_change=on_max_weeks_change
    )
with col_d:
    days_count = st.number_input("Навчальних днів на тиждень", min_value=1, max_value=6, value=5)
with col_s:
    slots_count = st.number_input("Пар на день", min_value=1, max_value=5, value=5)

ACTIVE_DAYS = DAY_NAMES[:days_count]
ACTIVE_SLOTS = SLOT_LABELS[:slots_count]
ACTIVE_SLOT_OPTIONS = SLOT_OPTIONS[:slots_count]

# Ініціалізація стану сесії
if 'schedule_data' not in st.session_state:
    st.session_state.schedule_data = None

if 'cfg_groups' not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([
        {"Група": "ПО-11Б", "Кількість тижнів": max_weeks, "День практики": "Немає"}
    ])

if 'cfg_teachers' not in st.session_state:
    st.session_state.cfg_teachers = "Усатенко В.М."

if 'cfg_rooms' not in st.session_state:
    st.session_state.cfg_rooms = "1\n15\n32\n27-А Комп'ютерний клас\nОНЛАЙН"

if 'cfg_limits' not in st.session_state:
    st.session_state.cfg_limits = pd.DataFrame([
        {"Викладач": "Усатенко В.М.", "День тижня": "Вівторок", "Недоступні пари": ["Всі пари"]}
    ])

if 'cfg_curriculum' not in st.session_state:
    st.session_state.cfg_curriculum = pd.DataFrame([
        {
            "Групи": ["ПО-11Б"],
            "Дисципліна": "Педагогіка",
            "Викладач": "Усатенко В.М.",
            "Годин на семестр": 30,
            "Формат": "Очно",
            "Потокова лекція": "Ні",
            "Аудиторія": "32"
        }
    ])

# --- ФУНКЦІЯ-КОЛБЕК ДЛЯ ВІДНОВЛЕННЯ JSON ---
def handle_json_upload():
    uploaded_file = st.session_state.get("config_file_uploader")
    if uploaded_file is not None:
        try:
            config = json.load(uploaded_file)
            
            # 1. Парсинг груп
            raw_groups = config.get("groups", [])
            adapted_groups = []
            for g_item in raw_groups:
                if isinstance(g_item, dict):
                    g_name = str(g_item.get("Група") or g_item.get("group") or "").strip()
                    if g_name:
                        w_val = g_item.get("Кількість тижнів")
                        try:
                            w_num = min(int(w_val), max_weeks) if pd.notnull(w_val) else max_weeks
                        except (ValueError, TypeError):
                            w_num = max_weeks
                        prac_val = str(g_item.get("День практики") or "Немає").strip()
                        adapted_groups.append({
                            "Група": g_name,
                            "Кількість тижнів": w_num,
                            "День практики": prac_val if prac_val in ACTIVE_DAYS else "Немає"
                        })

            # 2. Парсинг викладачів та аудиторій
            raw_t = config.get("teachers", "")
            teachers_str = "\n".join(raw_t) if isinstance(raw_t, list) else str(raw_t)
            
            raw_r = config.get("rooms", "")
            rooms_str = "\n".join(raw_r) if isinstance(raw_r, list) else str(raw_r)

            # 3. Парсинг навчального плану
            raw_curriculum = config.get("curriculum", [])
            adapted_curriculum = []
            for c_item in raw_curriculum:
                if not isinstance(c_item, dict):
                    continue
                
                groups_val = c_item.get("Групи") or c_item.get("Група") or c_item.get("groups") or []
                if isinstance(groups_val, str):
                    parsed_groups = [g.strip() for g in groups_val.split(",") if g.strip()]
                elif isinstance(groups_val, list):
                    parsed_groups = [str(g).strip() for g in groups_val if str(g).strip()]
                else:
                    parsed_groups = []

                subj_val = c_item.get("Предмет") or c_item.get("Дисципліна") or c_item.get("Назва предмета") or "Математика"
                teach_val = c_item.get("Викладач") or c_item.get("ПІБ викладача") or "Черненко В.П."
                
                hours_val = c_item.get("Годин на семестр") or c_item.get("Години") or 30
                try:
                    hours_num = int(hours_val)
                except (ValueError, TypeError):
                    hours_num = 30

                fmt_val = c_item.get("Формат") or "Очно"
                stream_raw = c_item.get("Потокова лекція?") or c_item.get("Потокова лекція") or "Ні"
                stream_val = "Так" if str(stream_raw).strip() in ["Так", "True", "true", "1"] else "Ні"
                room_val = c_item.get("Аудиторія") or c_item.get("Аудиторія / Формат") or "1"

                adapted_curriculum.append({
                    "Групи": parsed_groups,
                    "Предмет": str(subj_val).strip(),
                    "Викладач": str(teach_val).strip(),
                    "Годин на семестр": hours_num,
                    "Формат": str(fmt_val).strip(),
                    "Потокова лекція?": stream_val,
                    "Аудиторія": str(room_val).strip()
                })

            # 4. Парсинг обмежень
            raw_limits = config.get("limits", [])
            adapted_limits = []
            for l_item in raw_limits:
                if isinstance(l_item, dict):
                    t_name = str(l_item.get("Викладач") or "").strip()
                    d_name = str(l_item.get("День тижня") or "Всі дні").strip()
                    unavail = l_item.get("Недоступні пари") or ["Всі пари"]
                    if isinstance(unavail, str):
                        unavail = [s.strip() for s in unavail.split(",") if s.strip()]
                    adapted_limits.append({
                        "Викладач": t_name,
                        "День тижня": d_name,
                        "Недоступні пари": unavail
                    })

            if adapted_groups:
                st.session_state.cfg_groups = pd.DataFrame(adapted_groups)
            st.session_state.cfg_teachers = teachers_str
            st.session_state.cfg_rooms = rooms_str
            if adapted_limits:
                st.session_state.cfg_limits = pd.DataFrame(adapted_limits)
            if adapted_curriculum:
                st.session_state.cfg_curriculum = pd.DataFrame(adapted_curriculum)

            for key in ["groups_editor", "limits_editor_grid", "curriculum_editor_grid"]:
                if key in st.session_state:
                    del st.session_state[key]

            st.session_state.upload_success = True
        except Exception as e:
            st.session_state.upload_error = str(e)

# --- БЛОК ЗБЕРЕЖЕННЯ ТА ВІДНОВЛЕННЯ ДАНИХ ---
st.markdown("### 💾 Збереження та відновлення налаштувань")
col_imp, col_exp = st.columns(2)

with col_imp:
    st.file_uploader(
        "📂 Відновити збережені дані (файл .json)", 
        type=["json"], 
        key="config_file_uploader",
        on_change=handle_json_upload
    )
    if st.session_state.get("upload_success"):
        st.success("Всі дані успішно завантажено та відновлено!")
        st.session_state.upload_success = False
    if st.session_state.get("upload_error"):
        st.error(f"Помилка зчитування файлу: {st.session_state.upload_error}")
        st.session_state.upload_error = None

# 2. Довідники закладу
st.markdown("### 2. Довідники закладу")
col_g, col_t, col_r = st.columns(3)

with col_g:
    st.markdown("**Академічні групи та тривалість навчання**")
    groups_df = st.data_editor(
        st.session_state.cfg_groups,
        num_rows="dynamic",
        column_config={
            "Група": st.column_config.TextColumn(required=True),
            "Кількість тижнів": st.column_config.NumberColumn(min_value=1, max_value=max_weeks, default=max_weeks, required=True),
            "День практики": st.column_config.SelectboxColumn(options=["Немає"] + ACTIVE_DAYS)
        },
        use_container_width=True,
        key="groups_editor"
    )

with col_t:
    st.markdown("**Список викладачів**")
    teachers_text = st.text_area(
        "ПІБ викладачів (кожен з нового рядка)",
        st.session_state.cfg_teachers,
        height=140
    )

with col_r:
    st.markdown("**Аудиторний фонд**")
    rooms_text = st.text_area(
        "Аудиторії (кожна з нового рядка)",
        st.session_state.cfg_rooms,
        height=140
    )

active_groups_df = groups_df.dropna(subset=["Група"]).copy()
active_groups = [str(g).strip() for g in active_groups_df["Група"].tolist() if str(g).strip()]

active_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
active_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]

if not st.session_state.cfg_curriculum.empty:
    for _, c_row in st.session_state.cfg_curriculum.iterrows():
        c_g_list = c_row.get("Групи", [])
        if isinstance(c_g_list, list):
            for cg in c_g_list:
                cg_s = str(cg).strip()
                if cg_s and cg_s not in active_groups:
                    active_groups.append(cg_s)
        elif isinstance(c_g_list, str):
            for cg in c_g_list.split(","):
                cg_s = str(cg).strip()
                if cg_s and cg_s not in active_groups:
                    active_groups.append(cg_s)

        c_t = str(c_row.get("Викладач", "")).strip()
        if c_t and c_t not in active_teachers and c_t != "None":
            active_teachers.append(c_t)

        c_r = str(c_row.get("Аудиторія", "")).strip()
        if c_r and c_r not in active_rooms and c_r != "None":
            active_rooms.append(c_r)

if not active_groups: active_groups = ["ПО-11Б"]
if not active_teachers: active_teachers = ["Черненко В.П."]
if not active_rooms: active_rooms = ["1"]

group_weeks_map = {}
for _, g_row in active_groups_df.iterrows():
    g_n = str(g_row.get("Група", "")).strip()
    g_w = int(g_row.get("Кількість тижнів", max_weeks)) if pd.notnull(g_row.get("Кількість тижнів")) else max_weeks
    if g_n:
        group_weeks_map[g_n] = min(g_w, max_weeks)

# 3. Обмеження викладачів
st.markdown("### 3. Обмеження та недоступність викладачів")

limits_df = st.data_editor(
    st.session_state.cfg_limits,
    num_rows="dynamic",
    column_config={
        "Викладач": st.column_config.SelectboxColumn(options=active_teachers, required=True),
        "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + ACTIVE_DAYS, required=True),
        "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + ACTIVE_SLOT_OPTIONS, required=True)
    },
    use_container_width=True,
    key="limits_editor_grid"
)

# 4. Навчальний план дисциплін
st.markdown("### 4. Навчальний план дисциплін")

curriculum_df = st.data_editor(
    st.session_state.cfg_curriculum,
    num_rows="dynamic",
    column_config={
        "Групи": st.column_config.MultiselectColumn(options=active_groups, required=True, help="Оберіть 1 або кілька груп"),
        "Предмет": st.column_config.TextColumn(required=True),
        "Викладач": st.column_config.SelectboxColumn(options=active_teachers, required=True),
        "Годин на семестр": st.column_config.NumberColumn(min_value=10, max_value=300, step=10, default=30, required=True),
        "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"], required=True, default="Очно"),
        "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"], required=True, default="Ні"),
        "Аудиторія": st.column_config.SelectboxColumn(options=active_rooms, required=True)
    },
    use_container_width=True,
    key="curriculum_editor_grid"
)

config_export_data = {
    "groups": groups_df.to_dict(orient="records"),
    "teachers": teachers_text,
    "rooms": rooms_text,
    "limits": limits_df.to_dict(orient="records"),
    "curriculum": curriculum_df.to_dict(orient="records")
}

with col_exp:
    st.write(" ")
    st.write(" ")
    st.download_button(
        label="📥 Зберегти всі введені налаштування у файл (.json)",
        data=json.dumps(config_export_data, ensure_ascii=False, indent=2),
        file_name="rozklad_config.json",
        mime="application/json",
        use_container_width=True
    )

def style_schedule_grid(val):
    if not isinstance(val, str) or val == "-" or not val:
        return ""
    val_upper = val.upper()
    if "ОНЛАЙН" in val_upper:
        return "background-color: #CCFFFF; color: #000000; font-weight: bold;"
    elif "ПРАКТИКА" in val_upper:
        return "background-color: #E6E6FA; color: #000000; font-weight: bold;"
    elif "ПОТІК" in val_upper:
        return "background-color: #D5E8D4; color: #000000; font-weight: bold;"
    elif "КОМП" in val_upper:
        return "background-color: #FFF2CC; color: #000000; font-weight: bold;"
    else:
        return "background-color: #F5F5F5; color: #000000;"

def generate_full_semester_schedule(max_w, d_cnt, s_cnt, day_names, slot_labels, slot_opts, grp_df, grp_w_map, lim_df, plan_df):
    if grp_df.empty or plan_df.empty:
        return None, "Будь ласка, заповніть групи та навчальний план."

    model = CpModel()
    all_registered_groups = [g for g in grp_df["Група"].dropna().unique().tolist() if str(g).strip()]

    raw_lessons = []
    for _, row in plan_df.iterrows():
        g_raw = row.get("Групи", [])
        if isinstance(g_raw, list):
            g_list = [str(g).strip() for g in g_raw if str(g).strip()]
        elif isinstance(g_raw, str):
            g_list = [g.strip() for g in g_raw.split(",") if g.strip()]
        else:
            g_list = []

        subj = str(row.get("Предмет", "")).strip()
        teacher = str(row.get("Викладач", "")).strip()
        hours = float(row.get("Годин на семестр", 30)) if pd.notnull(row.get("Годин на семестр")) else 30
        fmt = str(row.get("Формат", "Очно")).strip()
        is_stream = str(row.get("Потокова лекція?", "Ні")).strip() == "Так" or len(g_list) > 1
        room = str(row.get("Аудиторія", "")).strip()

        if not g_list or not subj or subj == "None":
            continue

        raw_lessons.append({
            "groups": g_list,
            "subject": subj,
            "teacher": teacher,
            "hours": hours,
            "fmt": fmt,
            "is_stream": is_stream,
            "room": room
        })

    stream_dict = {}
    non_stream_lessons = []

    for item in raw_lessons:
        if item["is_stream"]:
            key = (item["teacher"], item["subject"], item["room"], item["fmt"])
            if key not in stream_dict:
                stream_dict[key] = {
                    "groups": set(item["groups"]),
                    "subject": item["subject"],
                    "teacher": item["teacher"],
                    "hours": item["hours"],
                    "fmt": item["fmt"],
                    "is_stream": True,
                    "room": item["room"]
                }
            else:
                stream_dict[key]["groups"].update(item["groups"])
        else:
            non_stream_lessons.append(item)

    final_specs = list(stream_dict.values()) + non_stream_lessons

    semester_lessons = []
    lesson_id = 0

    for spec in final_specs:
        spec_groups = list(spec["groups"])
        eff_weeks = min([grp_w_map.get(g, max_w) for g in spec_groups if g in grp_w_map] or [max_w])
        total_pairs = max(1, int(round(spec["hours"] / 2.0)))
        
        for p_idx in range(total_pairs):
            semester_lessons.append({
                "id": lesson_id,
                "groups": spec_groups,
                "subject": spec["subject"],
                "teacher": spec["teacher"],
                "fmt": spec["fmt"],
                "is_stream": spec["is_stream"],
                "room": spec["room"],
                "eff_weeks": eff_weeks,
                "spec_id": f"{spec['teacher']}_{spec['subject']}"
            })
            lesson_id += 1

    if not semester_lessons:
        return None, "Не знайдено заповнених предметів."

    x = {}
    for l in semester_lessons:
        eff_w = l["eff_weeks"]
        for w in range(eff_w):
            for d in range(d_cnt):
                for s in range(s_cnt):
                    x[l["id"], w, d, s] = model.NewBoolVar(f'x_{l["id"]}_{w}_{d}_{s}')

    for l in semester_lessons:
        eff_w = l["eff_weeks"]
        model.Add(sum(x[l["id"], w, d, s] for w in range(eff_w) for d in range(d_cnt) for s in range(s_cnt)) == 1)

    spec_groups_map = {}
    for l in semester_lessons:
        spec_groups_map.setdefault((l["spec_id"], l["eff_weeks"]), []).append(l)

    for (spec_key, eff_w), l_list in spec_groups_map.items():
        total_p = len(l_list)
        base_p_per_week = total_p // eff_w
        for w in range(eff_w):
            week_pairs_count = sum(x[l["id"], w, d, s] for l in l_list for d in range(d_cnt) for s in range(s_cnt))
            model.Add(week_pairs_count >= base_p_per_week)
            model.Add(week_pairs_count <= base_p_per_week + 1)

    for g in all_registered_groups:
        g_w = grp_w_map.get(g, max_w)
        for w in range(g_w):
            for d in range(d_cnt):
                for s in range(s_cnt):
                    g_active_lessons = [l for l in semester_lessons if g in l["groups"] and w < l["eff_weeks"]]
                    if g_active_lessons:
                        model.Add(sum(x[l["id"], w, d, s] for l in g_active_lessons) <= 1)

    for g in all_registered_groups:
        g_w = grp_w_map.get(g, max_w)
        for w in range(g_w):
            for d in range(d_cnt):
                g_active_lessons = [l for l in semester_lessons if g in l["groups"] and w < l["eff_weeks"]]
                if g_active_lessons:
                    for s1 in range(s_cnt):
                        for s2 in range(s1 + 1, s_cnt):
                            for s3 in range(s2 + 1, s_cnt):
                                y_s1 = sum(x[l["id"], w, d, s1] for l in g_active_lessons)
                                y_s2 = sum(x[l["id"], w, d, s2] for l in g_active_lessons)
                                y_s3 = sum(x[l["id"], w, d, s3] for l in g_active_lessons)
                                model.Add(y_s1 - y_s2 + y_s3 <= 1)

    for _, g_row in grp_df.iterrows():
        g_n = str(g_row.get("Група", "")).strip()
        p_d = str(g_row.get("День практики", "Немає")).strip()
        if p_d in day_names:
            p_idx = day_names.index(p_d)
            g_w = grp_w_map.get(g_n, max_w)
            g_lessons = [l for l in semester_lessons if g_n in l["groups"]]
            for w in range(g_w):
                for l in g_lessons:
                    if w < l["eff_weeks"]:
                        for s in range(s_cnt):
                            model.Add(x[l["id"], w, p_idx, s] == 0)

    if not lim_df.empty:
        for _, lim_row in lim_df.iterrows():
            t_n = str(lim_row.get("Викладач", "")).strip()
            l_d = lim_row.get("День тижня", "")
            l_s = lim_row.get("Недоступні пари", [])

            if not t_n or t_n == "None":
                continue

            target_days_indices = list(range(d_cnt)) if l_d == "Всі дні" else ([day_names.index(l_d)] if l_d in day_names else [])
            raw_slots = l_s if isinstance(l_s, list) else ([s.strip() for s in str(l_s).split(",") if s.strip()])

            t_lessons = [l for l in semester_lessons if l["teacher"] == t_n]
            if not t_lessons:
                continue

            for w in range(max_w):
                for d_idx in target_days_indices:
                    for s_idx in range(s_cnt):
                        s_opt_name = slot_opts[s_idx]
                        s_num_tag = f"{s_idx} пара"

                        is_blocked = False
                        if "Всі пари" in raw_slots:
                            is_blocked = True
                        else:
                            for item in raw_slots:
                                if item in s_opt_name or s_num_tag in item or item == s_opt_name:
                                    is_blocked = True
                                    break

                        if is_blocked:
                            for l in t_lessons:
                                if w < l["eff_weeks"]:
                                    model.Add(x[l["id"], w, d_idx, s_idx] == 0)

    all_teachers = list(set([l["teacher"] for l in semester_lessons if l["teacher"]]))
    for t in all_teachers:
        t_lessons = [l for l in semester_lessons if l["teacher"] == t]
        for w in range(max_w):
            for d in range(d_cnt):
                for s in range(s_cnt):
                    t_w_lessons = [l for l in t_lessons if w < l["eff_weeks"]]
                    if t_w_lessons:
                        model.Add(sum(x[l["id"], w, d, s] for l in t_w_lessons) <= 1)

    for t in all_teachers:
        t_lessons = [l for l in semester_lessons if l["teacher"] == t]
        for w in range(max_w):
            for d in range(d_cnt):
                t_w_lessons = [l for l in t_lessons if w < l["eff_weeks"]]
                if t_w_lessons:
                    t_day_count = sum(x[l["id"], w, d, s] for l in t_w_lessons for s in range(s_cnt))
                    model.Add(t_day_count != 1)

    comp_lessons = [l for l in semester_lessons if "Комп" in l["room"]]
    for w in range(max_w):
        for d in range(d_cnt):
            for s in range(s_cnt):
                c_w_lessons = [l for l in comp_lessons if w < l["eff_weeks"]]
                if c_w_lessons:
                    model.Add(sum(x[l["id"], w, d, s] for l in c_w_lessons) <= 1)

    penalties = []
    slot_penalties = {0: 10, 1: 0, 2: 0, 3: 0, 4: 100}

    for l in semester_lessons:
        for w in range(l["eff_weeks"]):
            for d in range(d_cnt):
                for s in range(s_cnt):
                    p_cost = slot_penalties.get(s, 0)
                    if p_cost > 0:
                        penalties.append(p_cost * x[l["id"], w, d, s])

    if penalties:
        model.Minimize(sum(penalties))

    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)

    if status not in [OPTIMAL, FEASIBLE]:
        return None, "Не вдалося розставити розклад. Перевірте обмеження або збільшіть вільні слоти."

    schedule_records = []
    for l in semester_lessons:
        for w in range(l["eff_weeks"]):
            for d in range(d_cnt):
                for s in range(s_cnt):
                    if solver.Value(x[l["id"], w, d, s]) == 1:
                        schedule_records.append({
                            "week": w + 1,
                            "day": day_names[d],
                            "slot_idx": s,
                            "slot_label": slot_labels[s],
                            "groups": l["groups"],
                            "subject": l["subject"],
                            "teacher": l["teacher"],
                            "fmt": l["fmt"],
                            "is_stream": l["is_stream"],
                            "room": l["room"]
                        })

    return schedule_records, None

if st.button("Згенерувати розклад", type="primary"):
    with st.spinner("Обчислення оптимального розкладу на весь семестр..."):
        res_records, err = generate_full_semester_schedule(
            max_weeks, days_count, slots_count, 
            ACTIVE_DAYS, ACTIVE_SLOTS, ACTIVE_SLOT_OPTIONS,
            groups_df, group_weeks_map, limits_df, curriculum_df
        )
    
    if err:
        st.error(err)
    else:
        st.success("Розклад успішно згенеровано!")
        st.session_state.schedule_data = {
            "records": res_records,
            "max_weeks": max_weeks,
            "days_count": days_count,
            "slots_count": slots_count,
            "active_groups": active_groups,
            "active_teachers": active_teachers,
            "groups_df": groups_df
        }

if st.session_state.schedule_data is not None:
    st.markdown("---")
    st.markdown("### 📊 Перегляд та експорт розкладу")

    records = st.session_state.schedule_data["records"]
    m_weeks = st.session_state.schedule_data["max_weeks"]
    d_cnt = st.session_state.schedule_data["days_count"]
    s_cnt = st.session_state.schedule_data["slots_count"]
    all_groups = st.session_state.schedule_data["active_groups"]
    all_teachers = st.session_state.schedule_data["active_teachers"]
    g_df = st.session_state.schedule_data["groups_df"]

    prac_map = {}
    for _, g_row in g_df.iterrows():
        g_n = str(g_row.get("Група", "")).strip()
        p_d = str(g_row.get("День практики", "Немає")).strip()
        if p_d in DAY_NAMES[:d_cnt]:
            prac_map.setdefault(p_d, []).append(g_n)

    view_option = st.radio(
        "Режим відображення:", 
        ["📅 Повний розклад по тижнях (Всі групи)", "👨‍🏫 Розклад викладача на весь семестр"], 
        horizontal=True
    )

    if view_option == "📅 Повний розклад по тижнях (Всі групи)":
        selected_week = st.selectbox("Оберіть тиждень:", range(1, m_weeks + 1), format_func=lambda x: f"Тиждень {x}")
        
        week_rows = []
        for d_name in DAY_NAMES[:d_cnt]:
            for s_idx in range(s_cnt):
                row_dict = {
                    "День тижня": d_name,
                    "Пара / Час": ACTIVE_SLOTS[s_idx]
                }
                
                for g_name in all_groups:
                    if d_name in prac_map and g_name in prac_map[d_name] and s_idx == 0:
                        row_dict[g_name] = "ПРАКТИКА"
                        continue

                    cell_content = "-"
                    for r in records:
                        if r["week"] == selected_week and r["day"] == d_name and r["slot_idx"] == s_idx and g_name in r["groups"]:
                            loc_str = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                            stream_tag = "\n(ПОТІК)" if r["is_stream"] else ""
                            cell_content = f"{r['subject']}{stream_tag}\n{r['teacher']}\n{loc_str}"
                            break
                    
                    row_dict[g_name] = cell_content
                
                week_rows.append(row_dict)

        df_week_view = pd.DataFrame(week_rows)
        styled_w = df_week_view.style.map(style_schedule_grid)
        st.dataframe(styled_w, use_container_width=True, height=600)

    elif view_option == "👨‍🏫 Розклад викладача на весь семестр":
        selected_teacher = st.selectbox("Оберіть викладача:", all_teachers)

        teacher_rows = []
        for d_name in DAY_NAMES[:d_cnt]:
            for s_idx in range(s_cnt):
                row_dict = {
                    "День тижня": d_name,
                    "Пара / Час": ACTIVE_SLOTS[s_idx]
                }

                for w in range(1, m_weeks + 1):
                    col_name = f"Тиждень {w}"
                    cell_content = "-"
                    for r in records:
                        if r["teacher"] == selected_teacher and r["week"] == w and r["day"] == d_name and r["slot_idx"] == s_idx:
                            groups_str = ", ".join(r["groups"])
                            loc_str = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                            cell_content = f"{groups_str}\n{r['subject']}\n{loc_str}"
                            break
                    row_dict[col_name] = cell_content

                teacher_rows.append(row_dict)

        df_teacher_view = pd.DataFrame(teacher_rows)
        styled_t = df_teacher_view.style.map(style_schedule_grid)
        st.dataframe(styled_t, use_container_width=True, height=600)

    st.markdown("#### 📥 Завантаження розкладу в Excel")
    
    buffer_all = io.BytesIO()
    with pd.ExcelWriter(buffer_all, engine='xlsxwriter') as writer:
        workbook = writer.book
        wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center'})

        for w in range(1, m_weeks + 1):
            w_rows = []
            for d_name in DAY_NAMES[:d_cnt]:
                for s_idx in range(s_cnt):
                    r_dict = {"День тижня": d_name, "Пара / Час": ACTIVE_SLOTS[s_idx]}
                    for g_name in all_groups:
                        if d_name in prac_map and g_name in prac_map[d_name] and s_idx == 0:
                            r_dict[g_name] = "ПРАКТИКА"
                            continue
                        c_val = "-"
                        for r in records:
                            if r["week"] == w and r["day"] == d_name and r["slot_idx"] == s_idx and g_name in r["groups"]:
                                loc_str = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                                stream_tag = "\n(ПОТІК)" if r["is_stream"] else ""
                                c_val = f"{r['subject']}{stream_tag}\n{r['teacher']}\n{loc_str}"
                                break
                        r_dict[g_name] = c_val
                    w_rows.append(r_dict)
            df_w = pd.DataFrame(w_rows)
            df_w.to_excel(writer, index=False, sheet_name=f"Тиждень {w}")

        for t_name in all_teachers:
            if not t_name:
                continue
            t_rows = []
            for d_name in DAY_NAMES[:d_cnt]:
                for s_idx in range(s_cnt):
                    r_dict = {"День тижня": d_name, "Пара / Час": ACTIVE_SLOTS[s_idx]}
                    for w in range(1, m_weeks + 1):
                        c_val = "-"
                        for r in records:
                            if r["teacher"] == t_name and r["week"] == w and r["day"] == d_name and r["slot_idx"] == s_idx:
                                groups_str = ", ".join(r["groups"])
                                loc_str = "ОНЛАЙН" if r["fmt"] == "Онлайн" else r["room"]
                                c_val = f"{groups_str}\n{r['subject']}\n{loc_str}"
                                break
                        r_dict[f"Тиждень {w}"] = c_val
                    t_rows.append(r_dict)
            df_t = pd.DataFrame(t_rows)
            sheet_title = f"{t_name}"[:31]
            df_t.to_excel(writer, index=False, sheet_name=sheet_title)

        for sheet in writer.sheets.values():
            sheet.set_column('A:Z', 22, wrap_format)

    st.download_button(
        label="📦 Завантажити повний розклад семестру у Excel (усі тижні та викладачі)",
        data=buffer_all.getvalue(),
        file_name="rozklad_semestr_full.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
