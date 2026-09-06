import streamlit as st
import pandas as pd
import io
import json
from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

# --- КОНСТАНТИ ---
SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:42 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"}
]
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]
SLOT_LABELS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="Academy Scheduler Pro", layout="wide", page_icon="🎓")

# --- СТИЛІЗАЦІЯ ---
st.markdown("""
    <style>
    .main-title { font-size: 2.5rem; color: #1E3A8A; font-weight: 800; text-align: center; margin-bottom: 2rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { 
        background-color: #f0f2f6; border-radius: 4px 4px 0 0; padding: 10px 20px; 
    }
    .stTabs [aria-selected="true"] { background-color: #1E3A8A !important; color: white !important; }
    </style>
""", unsafe_allow_html=True)

# --- ІНІЦІАЛІЗАЦІЯ СТАНУ ---
if 'cfg' not in st.session_state:
    st.session_state.cfg = {
        "max_weeks": 15,
        "days_count": 5,
        "slots_count": 5,
        "groups": pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "День практики": "Немає"}]),
        "teachers": "Усатенко В.М.",
        "rooms": "1 авдиторія\n15 авдиторія\n27-А комп'ютерний клас\nОНЛАЙН\nспортзал",
        "curriculum": pd.DataFrame([{
            "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": "Усатенко В.М.",
            "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція": "Ні", "Авдиторія": "1 авдиторія"
        }]),
        "limits": pd.DataFrame(columns=["Викладач", "День тижня", "Недоступні пари"]),
        "results": None
    }

# --- ФУНКЦІЇ ДОПОМОГИ ---
def get_active_lists():
    teachers = [t.strip() for t in st.session_state.cfg["teachers"].split("\n") if t.strip()]
    rooms = [r.strip() for r in st.session_state.cfg["rooms"].split("\n") if r.strip()]
    groups = st.session_state.cfg["groups"]["Група"].dropna().unique().tolist()
    return teachers, rooms, groups

def style_cell(val):
    if not isinstance(val, str) or val in ["-", ""]: return ""
    v = val.upper()
    if "ОНЛАЙН" in v: return "background-color: #DBEAFE; color: #1E40AF;"
    if "ПРАКТИКА" in v: return "background-color: #F3E8FF; color: #6B21A8; font-weight: bold;"
    if "ПОТІК" in v: return "background-color: #D1FAE5; color: #065F46;"
    return "background-color: #F3F4F6;"

# --- ФУНКЦІЯ ІМПОРТУ JSON ---
def handle_upload():
    uploaded_file = st.session_state.uploader
    if uploaded_file:
        try:
            data = json.load(uploaded_file)
            st.session_state.cfg["max_weeks"] = data.get("max_weeks", 15)
            st.session_state.cfg["groups"] = pd.DataFrame(data.get("groups", []))
            st.session_state.cfg["teachers"] = data.get("teachers", "")
            st.session_state.cfg["rooms"] = data.get("rooms", "")
            st.session_state.cfg["curriculum"] = pd.DataFrame(data.get("curriculum", []))
            st.session_state.cfg["limits"] = pd.DataFrame(data.get("limits", []))
            st.success("✅ Налаштування завантажено!")
        except Exception as e:
            st.error(f"Помилка файлу: {e}")

# --- ГОЛОВНИЙ ЕКРАН ---
st.markdown('<div class="main-title">🎓 Система автоматизованого розкладу</div>', unsafe_allow_html=True)

tabs = st.tabs(["⚙️ Основні налаштування", "📚 Навчальний план", "🚫 Обмеження", "📊 Результати"])

# --- TAB 1: БАЗОВІ НАЛАШТУВАННЯ ---
with tabs[0]:
    col_set, col_io = st.columns([2, 1])
    with col_set:
        st.subheader("Параметри семестру")
        c1, c2, c3 = st.columns(3)
        st.session_state.cfg["max_weeks"] = c1.number_input("Тижнів у семестрі", 1, 25, st.session_state.cfg["max_weeks"])
        st.session_state.cfg["days_count"] = c2.number_input("Днів на тиждень", 1, 6, st.session_state.cfg["days_count"])
        st.session_state.cfg["slots_count"] = c3.number_input("Пар на день", 1, 5, st.session_state.cfg["slots_count"])

    with col_io:
        st.subheader("💾 Проєкт")
        st.file_uploader("Завантажити .json", type="json", key="uploader", on_change=handle_upload)
        export_content = json.dumps({
            "max_weeks": st.session_state.cfg["max_weeks"],
            "groups": st.session_state.cfg["groups"].to_dict('records'),
            "teachers": st.session_state.cfg["teachers"],
            "rooms": st.session_state.cfg["rooms"],
            "curriculum": st.session_state.cfg["curriculum"].to_dict('records'),
            "limits": st.session_state.cfg["limits"].to_dict('records')
        }, ensure_ascii=False, indent=2)
        st.download_button("📥 Зберегти конфігурацію", export_content, "schedule_config.json", use_container_width=True)

    st.divider()
    g_col, t_col, r_col = st.columns(3)
    with g_col:
        st.markdown("**Групи**")
        st.session_state.cfg["groups"] = st.data_editor(
            st.session_state.cfg["groups"], num_rows="dynamic", use_container_width=True,
            column_config={"День практики": st.column_config.SelectboxColumn(options=["Немає"] + DAY_NAMES)}
        )
    with t_col:
        st.markdown("**Викладачі**")
        st.session_state.cfg["teachers"] = st.text_area("Список", st.session_state.cfg["teachers"], height=200, label_visibility="collapsed")
    with r_col:
        st.markdown("**Аудиторії**")
        st.session_state.cfg["rooms"] = st.text_area("Фонд", st.session_state.cfg["rooms"], height=200, label_visibility="collapsed")

# --- TAB 2: ПЛАН ---
with tabs[1]:
    t_list, r_list, g_list = get_active_lists()
    st.subheader("Розподіл годин")
    st.session_state.cfg["curriculum"] = st.data_editor(
        st.session_state.cfg["curriculum"], num_rows="dynamic", use_container_width=True,
        column_config={
            "Групи": st.column_config.MultiselectColumn(options=g_list),
            "Викладач": st.column_config.SelectboxColumn(options=t_list),
            "Аудиторія": st.column_config.SelectboxColumn(options=r_list),
            "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
            "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"])
        }
    )

# --- TAB 3: ОБМЕЖЕННЯ ---
with tabs[2]:
    st.subheader("Побажання викладачів")
    st.session_state.cfg["limits"] = st.data_editor(
        st.session_state.cfg["limits"], num_rows="dynamic", use_container_width=True,
        column_config={
            "Викладач": st.column_config.SelectboxColumn(options=t_list),
            "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + DAY_NAMES[:st.session_state.cfg["days_count"]]),
            "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + SLOT_LABELS[:st.session_state.cfg["slots_count"]])
        }
    )

# --- TAB 4: ГЕНЕРАЦІЯ ТА РЕЗУЛЬТАТИ ---
with tabs[3]:
    btn_col, info_col = st.columns([1, 2])
    
    if btn_col.button("🚀 ЗГЕНЕРУВАТИ РОЗКЛАД", type="primary", use_container_width=True):
        model = CpModel()
        curr = st.session_state.cfg["curriculum"]
        grps_df = st.session_state.cfg["groups"]
        
        # 1. Формування списку занять
        lessons = []
        for _, row in curr.iterrows():
            if not row["Групи"] or pd.isna(row["Предмет"]): continue
            pairs = int(round(row["Годин на семестр"] / 2))
            eff_w = int(min([grps_df[grps_df["Група"] == g]["Кількість тижнів"].values[0] for g in row["Групи"]] or [st.session_state.cfg["max_weeks"]]))
            
            for p in range(pairs):
                lessons.append({
                    "id": len(lessons), "groups": row["Групи"], "subject": row["Предмет"],
                    "teacher": row["Викладач"], "room": row["Аудиторія"], 
                    "is_online": row["Формат"] == "Онлайн", "eff_weeks": eff_w,
                    "is_stream": row["Потокова лекція?"] == "Так"
                })

        if not lessons:
            st.error("Навчальний план порожній!")
        else:
            # 2. Створення змінних
            x = {}
            for l in lessons:
                for w in range(l["eff_weeks"]):
                    for d in range(st.session_state.cfg["days_count"]):
                        for s in range(st.session_state.cfg["slots_count"]):
                            x[l["id"], w, d, s] = model.NewBoolVar(f'l{l["id"]}w{w}d{d}s{s}')

            # 3. Базові обмеження
            for l in lessons:
                model.Add(sum(x[l["id"], w, d, s] for w in range(l["eff_weeks"]) for d in range(st.session_state.cfg["days_count"]) for s in range(st.session_state.cfg["slots_count"])) == 1)

            # Конфлікти груп та викладачів
            for w in range(st.session_state.cfg["max_weeks"]):
                for d in range(st.session_state.cfg["days_count"]):
                    for s in range(st.session_state.cfg["slots_count"]):
                        for g in g_list:
                            model.Add(sum(x[l["id"], w, d, s] for l in lessons if g in l["groups"] and w < l["eff_weeks"]) <= 1)
                        for t in t_list:
                            model.Add(sum(x[l["id"], w, d, s] for l in lessons if l["teacher"] == t and w < l["eff_weeks"]) <= 1)
                        for r in r_list:
                            if "ОНЛАЙН" not in r.upper():
                                model.Add(sum(x[l["id"], w, d, s] for l in lessons if l["room"] == r and w < l["eff_weeks"]) <= 1)

            # 4. Вирішення
            solver = CpSolver()
            solver.parameters.max_time_in_seconds = 10.0
            status = solver.Solve(model)

            if status in [OPTIMAL, FEASIBLE]:
                final_res = []
                for l in lessons:
                    for w in range(l["eff_weeks"]):
                        for d in range(st.session_state.cfg["days_count"]):
                            for s in range(st.session_state.cfg["slots_count"]):
                                if solver.Value(x[l["id"], w, d, s]):
                                    final_res.append({
                                        "w": w+1, "d": DAY_NAMES[d], "s": s, 
                                        "groups": l["groups"], "subj": l["subject"], 
                                        "t": l["teacher"], "r": l["room"], "online": l["is_online"]
                                    })
                st.session_state.cfg["results"] = final_res
                st.success("Розклад готовий!")
            else:
                st.error("Неможливо скласти розклад. Спробуйте зменшити кількість годин або додати авдиторії.")

    # --- ВІДОБРАЖЕННЯ РЕЗУЛЬТАТІВ ---
    if st.session_state.cfg["results"]:
        res = st.session_state.cfg["results"]
        view_opt = st.radio("Перегляд:", ["По тижнях", "Викладачі"], horizontal=True)
        
        if view_opt == "По тижнях":
            sel_w = st.selectbox("Тиждень", range(1, st.session_state.cfg["max_weeks"]+1))
            grid = []
            for d in DAY_NAMES[:st.session_state.cfg["days_count"]]:
                for s_idx in range(st.session_state.cfg["slots_count"]):
                    row = {"День": d, "Пара": SLOT_DETAILS[s_idx]["label"]}
                    for g in g_list:
                        cell = "-"
                        match = [item for item in res if item["w"] == sel_w and item["d"] == d and item["s"] == s_idx and g in item["groups"]]
                        if match:
                            m = match[0]
                            loc = "ОНЛАЙН" if m["online"] else m["r"]
                            cell = f"{m['subj']}\n{m['t']}\n{loc}"
                        row[g] = cell
                    grid.append(row)
            st.dataframe(pd.DataFrame(grid).style.map(style_cell), use_container_width=True, height=500)

        # Експорт в Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            pd.DataFrame(res).to_excel(writer, index=False, sheet_name="Data")
        st.download_button("📦 Скачати розклад (Excel)", output.getvalue(), "rozklad.xlsx", use_container_width=True)
    else:
        st.info("Натисніть кнопку вище, щоб згенерувати розклад.")
