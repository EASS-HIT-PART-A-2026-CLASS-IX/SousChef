import streamlit as st

from app.api_client import api_post
from app.components import render_recipe_content
from app.config import AI_IMPORT_TIMEOUT


def page_text_import() -> None:
    st.markdown("## 📝 ייבוא מתכון מטקסט / תמונה")
    st.caption("הדבק טקסט של מתכון בכל פורמט, עם תמונה אופציונלית — ה-AI יבנה אותו מחדש.")

    text = st.text_area("טקסט המתכון", height=160, placeholder="הדבק כאן את הטקסט של המתכון בכל שפה ובכל פורמט...")
    uploaded_file = st.file_uploader("📸 תמונת מתכון (אופציונלי)", type=["jpg", "jpeg", "png", "webp"])

    if uploaded_file:
        st.image(uploaded_file, width=300, caption="תמונה שהועלתה")

    can_submit = bool(text.strip()) or uploaded_file is not None
    if st.button("✨ עבד עם AI", type="primary", use_container_width=True, disabled=not can_submit):
        with st.spinner("🤖 מעבד עם AI..."):
            files = None
            if uploaded_file:
                files = {"image": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            result = api_post(
                "/recipes/from-text",
                data={"text": text or ""},
                files=files,
                timeout=AI_IMPORT_TIMEOUT,
            )

            if result:
                st.success("✅ המתכון חולץ בהצלחה!")
                st.markdown(f"### {result['name']}")
                st.markdown(f'<span class="badge">{result.get("category", "")}</span>', unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("⏱ הכנה", f"{result.get('prep_time', 0)} דק'")
                col2.metric("🍳 בישול", f"{result.get('cook_time', 0)} דק'")
                col3.metric("🍽 מנות", result.get("servings", 1))
                with st.expander("הצג פרטים מלאים"):
                    render_recipe_content(result, key_prefix=f"text_import_{result.get('id', 'preview')}")
                st.info(f"💾 המתכון נשמר אוטומטית (ID: {result.get('id')})")
