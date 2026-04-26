import time

import streamlit as st

from app.api_client import api_post
from app.config import AI_IMPORT_TIMEOUT
from app.state import _go, _seed_create_draft


def page_url_import() -> None:
    st.markdown("## 🔗 ייבוא מתכון מ-URL")
    st.caption("הדבק קישור לאתר מתכונים, YouTube, Instagram או Facebook — ה-AI יחלץ טיוטת מתכון ויעביר אותה למסך היצירה.")

    with st.form("url_form"):
        url = st.text_input("כתובת URL", placeholder="https://www.example.com/recipe...")
        submitted = st.form_submit_button("🔗 ייבא מתכון", type="primary", use_container_width=True)

    if submitted and url:
        with st.spinner("🤖 מעבד עם AI..."):
            progress = st.progress(0, text="🔍 בודק קישור...")
            for i, msg in enumerate(["🔍 בודק קישור...", "🌐 מוריד תוכן...", "🤖 מעבד עם AI...", "✍️ בונה מבנה..."]):
                time.sleep(0.4)
                progress.progress((i + 1) * 25, text=msg)

            result = api_post("/recipes/from-url/preview", json_data={"url": url}, timeout=AI_IMPORT_TIMEOUT)
            progress.empty()

            if result:
                _seed_create_draft(
                    result,
                    notice="✅ טיוטת המתכון חולצה מהקישור. אפשר לעבור על הפרטים ולשמור אותה ממסך היצירה.",
                )
                _go("create")
                st.rerun()
