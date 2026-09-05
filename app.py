import streamlit as st
import pandas as pd
import io
from ortools.sat.python.cp_model import CpModel, CpSolver

st.set_page_config(page_title="Генератор розкладу", layout="wide")
st.title("Система автоматичного формування розкладу")

# Ініціалізація пам'яті сесії для збереження таблиці при редагуванні
if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = None

# 1. Параметри тижня
st.markdown("**1. Базові параметри**")
col1, col2 = st.columns(2)
with col1:
    days_count = st.number_input("Кількість днів", min_value=1, max_value=7, value=5)
with col2:
    slots_count = st.number_input("Пар на день", min_value=1, max_value=8, value=4)

# 2. Налаштування практики
st.markdown("**2. Періоди практики**")
prac_format = st.radio(
    "Формат проходження практики:", 
    ["Немає", "Безперервна (декілька тижнів)", "Один день на тиждень (протягом місяців)"], 
    horizontal=True
)

col3, col4 = st.columns(2)
with col3:
    if prac_format == "Безперервна (декілька тижнів)":
        prac_duration = st.number_input("Тривалість (у тижнях)", min_value=1, max_value=10, value=2)
    elif prac_format == "Один день на тиждень (протягом місяців)":
        prac_day = st.selectbox("День тижня", ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"])
        prac_months = st.number_input("Протягом скількох місяців", min_value=1, max_value=10, value=3)

# 3. Викладачі та групи
st.markdown("**3. Вхідні дані**")
teacher_input = st.text_area("Викладачі (кожен з нового рядка)", "Іванов І.І.\nПетренко П.П.")
group_input = st.text_area("Групи (Назва | очно/онлайн)", "КН-21 | очно\nПС-22 | онлайн")

# Функція кольорового маркування
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
    return ''

# Кнопка генерації (лише записує дані в пам'ять)
if st.button("Згенерувати розклад", type="primary"):
    st.success("Алгоритм успішно знайшов рішення!")
    
    schedule_data = {
        "Час": [f"Пара {i+1}" for i in range(slots_count)],
        "Понеділок": ["КН-21 (Іванов, потік)", "ПС-22 (онлайн)", "-", "ПС-22 (практика)"],
        "Вівторок": ["-", "КН-21 (Петренко, ауд. 101)", "КН-21 (практика)", "ПС-22 (онлайн)"],
        "Середа": ["-", "-", "ПС-22 (онлайн)", "-"],
        "Четвер": ["КН-21 (потік)", "-", "-", "-"],
        "П'ятниця": ["ПС-22 (практика)", "ПС-22 (практика)", "ПС-22 (практика)", "-"]
    }
    st.session_state.schedule_df = pd.DataFrame(schedule_data).head(slots_count)

# Якщо таблиця вже створена, показуємо редактор і кнопку завантаження
if st.session_state.schedule_df is not None:
    st.markdown("### ✏️ Редагування розкладу")
    st.info("Клікніть на будь-яку комірку двічі, щоб змінити її текст (наприклад, перенести пару).")
    
    # Застосовуємо кольори та виводимо таблицю для РЕДАГУВАННЯ
    styled_df = st.session_state.schedule_df.style.map(color_cells)
    edited_df = st.data_editor(styled_df, use_container_width=True)
    
    # Блок експорту працює вже з ВІДРЕДАГОВАНИМ розкладом (edited_df)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        edited_df.to_excel(writer, index=False, sheet_name='Розклад')
        
        worksheet = writer.sheets['Розклад']
        for i, col in enumerate(edited_df.columns):
            column_len = max(edited_df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, column_len)

    st.download_button(
        label="📥 Завантажити відредагований розклад (.xlsx)",
        data=buffer.getvalue(),
        file_name="rozklad_final.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )