import html

import streamlit as st

from app.api_client import api_delete, api_get, api_get_result, api_put
from app.config import CAT_KEY_MAP, CATEGORY_COLORS, PAGES, VALID_CATEGORIES
from app.state import _clear_recipe_drawer, _go, _set_open_recipe


def render_header(recipe_count: int) -> None:
    active_page = st.session_state.page
    active_cat_key = CAT_KEY_MAP.get(st.session_state.get("active_category", "הכל"), "all")
    st.markdown(f"""<style>
    [class*="st-key-nav_{active_page}"] button {{
        background: #C5552D !important; color: #FFFFFF !important;
    }}
    [class*="st-key-nav_{active_page}"] button:hover {{ background: #B14A26 !important; }}
    [class*="st-key-cat_{active_cat_key}"] button {{
        background: #C5552D !important; color: #FFFFFF !important;
    }}
    [class*="st-key-cat_{active_cat_key}"] button:hover {{ background: #B14A26 !important; }}
    </style>""", unsafe_allow_html=True)

    cols = st.columns([2.2, 2.0, 1.6, 1.8, 2.0, 2.5, 1.3])
    with cols[0]:
        st.markdown("""
        <div class="sc-brand">
            <span class="sc-brand-icon">🍳</span>
            <div class="sc-brand-text">
                <div class="sc-brand-title">SousChef</div>
                <div class="sc-brand-tag">Your Personal SousChef</div>
            </div>
        </div>""", unsafe_allow_html=True)
    for i, (page_id, label) in enumerate(PAGES):
        with cols[1 + i]:
            if st.button(label, key=f"nav_{page_id}", use_container_width=True):
                _go(page_id)
                st.rerun()
    with cols[6]:
        st.markdown(
            f'<div class="sc-count-pill">{recipe_count} מתכונים</div>',
            unsafe_allow_html=True,
        )


def render_recipe_card(recipe: dict, idx: int) -> None:
    cat = recipe.get("category") or ""
    colors = CATEGORY_COLORS.get(cat, {"bg": "#F1EAD9", "fg": "#6E5F47"})
    safe_cat = html.escape(cat)
    safe_name = html.escape(str(recipe.get("name", "")))
    badge_html = (
        f'<span class="sc-card-badge" '
        f'style="background:{colors["bg"]};color:{colors["fg"]};">{safe_cat}</span>'
        if cat else ""
    )
    desc = html.escape((recipe.get("description") or "").strip())
    st.markdown(
        f"""
        <a class="sc-card-link" href="?recipe_id={recipe['id']}" target="_self">
            <div class="sc-card">
                <div class="sc-card-main">
                    {badge_html}
                    <div class="sc-card-title">{safe_name}</div>
                    <div class="sc-card-desc">{desc}</div>
                </div>
                <div class="sc-card-meta">
                    <span>⏱ הכנה: {recipe.get('prep_time') or 0} דק'</span>
                    <span>🍳 בישול: {recipe.get('cook_time') or 0} דק'</span>
                    <span>🍽 מנות: {recipe.get('servings') or 1}</span>
                </div>
            </div>
        </a>
        """,
        unsafe_allow_html=True,
    )


def _recipe_tip_cache_key(recipe: dict, key_prefix: str) -> str:
    recipe_id = recipe.get("id")
    if recipe_id is None:
        return f"{key_prefix}_preview"
    return f"{key_prefix}_{recipe_id}"


def _render_recipe_stats(recipe: dict) -> None:
    stats = [
        ("מנות", recipe.get("servings") or 1),
        ("דק' בישול", recipe.get("cook_time") or 0),
        ("דק' הכנה", recipe.get("prep_time") or 0),
    ]
    stats_html = "".join(
        f'<div class="sc-detail-stat">'
        f'<div class="sc-detail-stat-value">{html.escape(str(value))}</div>'
        f'<div class="sc-detail-stat-label">{html.escape(label)}</div>'
        f"</div>"
        for label, value in stats
    )
    st.markdown(f'<div class="sc-detail-stats">{stats_html}</div>', unsafe_allow_html=True)


def render_recipe_content(recipe: dict, *, key_prefix: str) -> None:
    if "recipe_ai_tips" not in st.session_state:
        st.session_state["recipe_ai_tips"] = {}

    safe_category = html.escape(recipe.get("category", "") or "")
    safe_name = html.escape(str(recipe.get("name", "")))
    safe_description = html.escape(recipe.get("description", "") or "")

    if safe_category:
        st.markdown(f'<span class="badge">{safe_category}</span>', unsafe_allow_html=True)
    st.markdown(f'<div class="recipe-title">{safe_name}</div>', unsafe_allow_html=True)
    if safe_description:
        st.markdown(f'<div class="rtl-copy sc-detail-desc">{safe_description}</div>', unsafe_allow_html=True)

    _render_recipe_stats(recipe)

    st.markdown('<div class="sc-section-title">מרכיבים 🥕</div>', unsafe_allow_html=True)
    for ing in recipe.get("ingredients", []):
        amount_str = f"{ing['amount']} {ing.get('unit', '')}".strip() if ing.get("amount") else ""
        safe_ing_name = html.escape(str(ing.get("name", "")))
        safe_amount = html.escape(amount_str)
        st.markdown(
            f'<div class="ing-row">'
            f'<span style="font-weight:500">{safe_ing_name}</span>'
            f'<span style="color:#8A7B66">{safe_amount}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="sc-section-title">שלבי הכנה 📋</div>', unsafe_allow_html=True)
    for step in sorted(recipe.get("steps", []), key=lambda s: s.get("order", 0)):
        safe_instruction = html.escape(str(step.get("instruction", "")))
        step_order = html.escape(str(step.get("order", "")))
        st.markdown(
            f'<div class="sc-step-row">'
            f'<span class="step-num">{step_order}</span>'
            f'<div class="rtl-copy sc-step-text">{safe_instruction}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if recipe.get("id") is None:
        return

    cache_key = _recipe_tip_cache_key(recipe, key_prefix)
    st.divider()
    if st.button("שפר את המתכון עם AI ✨", key=f"{key_prefix}_enhance", use_container_width=True):
        with st.spinner("🤖 מנתח..."):
            result = api_get(f"/recipes/{recipe['id']}/enhance", timeout=120)
            if result:
                st.session_state["recipe_ai_tips"][cache_key] = result["tips"]

    tips = st.session_state["recipe_ai_tips"].get(cache_key)
    if tips:
        st.markdown(f'<div class="ai-result">{html.escape(str(tips))}</div>', unsafe_allow_html=True)


def render_edit_form(recipe: dict, *, compact: bool = False) -> None:
    with st.form(f"edit_form_{recipe['id']}"):
        st.markdown("#### ✏️ עריכת מתכון")
        name = st.text_input("שם המתכון", value=recipe.get("name", ""))
        desc = st.text_area("תיאור", value=recipe.get("description", "") or "", height=80)

        current_cat = recipe.get("category") or VALID_CATEGORIES[0]
        cat_index = VALID_CATEGORIES.index(current_cat) if current_cat in VALID_CATEGORIES else 0
        if compact:
            top_left, top_right = st.columns(2)
            bottom_left, bottom_right = st.columns(2)
            with top_left:
                category = st.selectbox("קטגוריה", VALID_CATEGORIES, index=cat_index)
            with top_right:
                servings = st.number_input("מנות", min_value=1, value=int(recipe.get("servings") or 1))
            with bottom_left:
                prep_time = st.number_input("זמן הכנה (דק')", min_value=0, value=int(recipe.get("prep_time") or 0))
            with bottom_right:
                cook_time = st.number_input("זמן בישול (דק')", min_value=0, value=int(recipe.get("cook_time") or 0))
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                category = st.selectbox("קטגוריה", VALID_CATEGORIES, index=cat_index)
            with col2:
                prep_time = st.number_input("זמן הכנה (דק')", min_value=0, value=int(recipe.get("prep_time") or 0))
            with col3:
                cook_time = st.number_input("זמן בישול (דק')", min_value=0, value=int(recipe.get("cook_time") or 0))
            with col4:
                servings = st.number_input("מנות", min_value=1, value=int(recipe.get("servings") or 1))

        col_save, col_cancel = st.columns([1, 1])
        saved = col_save.form_submit_button("💾 שמור שינויים", type="primary")
        cancelled = col_cancel.form_submit_button("ביטול")

    if saved:
        if not name or not name.strip():
            st.error("חובה למלא שם מתכון")
        else:
            payload = {
                "name": name,
                "description": desc or None,
                "category": category,
                "prep_time": prep_time,
                "cook_time": cook_time,
                "servings": servings,
            }
            result = api_put(f"/recipes/{recipe['id']}", payload)
            if result:
                st.success("✅ המתכון עודכן בהצלחה!")
                st.session_state.pop("edit_recipe_id", None)
                st.rerun()

    if cancelled:
        st.session_state.pop("edit_recipe_id", None)
        st.rerun()


def render_recipe_drawer(recipe: dict) -> None:
    if st.button("סגור חלונית מתכון", key=f"drawer_backdrop_{recipe['id']}"):
        _clear_recipe_drawer()
        st.rerun()
    with st.sidebar:
        st.markdown('<div class="sc-recipe-drawer" data-testid="recipe-drawer"></div>', unsafe_allow_html=True)

        close_col, spacer, edit_col, delete_col = st.columns([0.9, 3.8, 1.4, 1.4])
        with close_col:
            if st.button("✕", key=f"drawer_close_{recipe['id']}"):
                _clear_recipe_drawer()
                st.rerun()
        with edit_col:
            if st.session_state.get("edit_recipe_id") != recipe["id"]:
                if st.button("ערוך ✏️", key=f"drawer_edit_{recipe['id']}", use_container_width=True):
                    st.session_state["edit_recipe_id"] = recipe["id"]
                    st.rerun()
        with delete_col:
            if st.button("מחק 🗑", key=f"drawer_delete_{recipe['id']}", use_container_width=True):
                if api_delete(f"/recipes/{recipe['id']}"):
                    st.session_state.get("recipe_ai_tips", {}).pop(
                        _recipe_tip_cache_key(recipe, f"drawer_recipe_{recipe['id']}"),
                        None,
                    )
                    _clear_recipe_drawer()
                    st.rerun()

        if st.session_state.get("edit_recipe_id") == recipe["id"]:
            render_edit_form(recipe, compact=True)
        else:
            render_recipe_content(recipe, key_prefix=f"drawer_recipe_{recipe['id']}")
