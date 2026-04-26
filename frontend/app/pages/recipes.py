import streamlit as st

from app.api_client import api_get, api_get_result, api_post
from app.components import render_recipe_card, render_recipe_drawer
from app.config import CAT_KEY_MAP, VALID_CATEGORIES
from app.state import _clear_recipe_drawer


def page_recipes() -> None:
    selected_recipe = None
    open_recipe_id = st.session_state.get("open_recipe_id")
    if open_recipe_id is not None:
        selected_recipe, _detail, _status_code = api_get_result(
            f"/recipes/{open_recipe_id}",
            show_error=False,
        )
        if selected_recipe is None:
            _clear_recipe_drawer()
            st.rerun()

    search = st.text_input(
        "חיפוש",
        key="search_box",
        label_visibility="collapsed",
        placeholder="חיפוש מתכון...",
    )

    ai_cols = st.columns([6, 1])
    with ai_cols[0]:
        ai_query = st.text_input(
            "AI search",
            key="ai_search",
            label_visibility="collapsed",
            placeholder="שאל AI מה לבשל היום...",
        )
    with ai_cols[1]:
        ai_clicked = st.button("חפש עם AI", key="ai_search_btn", use_container_width=True)

    if ai_clicked and ai_query:
        with st.spinner("מחפש..."):
            recipes_data = api_get("/recipes") or []
            names = [r["name"] for r in recipes_data]
            result = api_post(
                "/recipes/recommend",
                json_data={"query": ai_query, "recipe_names": names},
            )
            if result:
                st.markdown(
                    f'<div class="ai-result">{result["recommendation"]}</div>',
                    unsafe_allow_html=True,
                )

    cat_options = ["הכל"] + VALID_CATEGORIES
    cat_cols = st.columns(len(cat_options))
    for i, cat in enumerate(cat_options):
        with cat_cols[i]:
            safe_key = CAT_KEY_MAP.get(cat, cat)
            if st.button(cat, key=f"cat_{safe_key}"):
                st.session_state.active_category = cat
                st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    params = {}
    if st.session_state.active_category != "הכל":
        params["category"] = st.session_state.active_category
    recipes = api_get("/recipes", params=params) or []
    if search:
        recipes = [
            r for r in recipes
            if search in r.get("name", "") or search in (r.get("description") or "")
        ]

    if not recipes:
        st.info("לא נמצאו מתכונים. נסה להוסיף מתכונים חדשים מהתפריט למעלה!")
    else:
        cols_per_row = 3
        for row_start in range(0, len(recipes), cols_per_row):
            row_recipes = recipes[row_start:row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for i, recipe in enumerate(row_recipes):
                with cols[i]:
                    render_recipe_card(recipe, idx=row_start + i)

    if selected_recipe is not None:
        render_recipe_drawer(selected_recipe)
