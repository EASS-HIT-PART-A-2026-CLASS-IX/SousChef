import streamlit as st

from app.api_client import api_get
from app.components import render_header
from app.config import CAT_KEY_MAP
from app.pages.create import page_create
from app.pages.recipes import page_recipes
from app.pages.text_import import page_text_import
from app.pages.url_import import page_url_import
from app.state import _sync_open_recipe_from_query_params
from app.styles import get_styles

st.set_page_config(
    page_title="SousChef 🍳",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _init_session_state() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "recipes"
    if "active_category" not in st.session_state:
        st.session_state.active_category = "הכל"
    if "open_recipe_id" not in st.session_state:
        st.session_state.open_recipe_id = None


def main() -> None:
    _init_session_state()
    _sync_open_recipe_from_query_params()

    active_page = st.session_state.page
    active_cat_key = CAT_KEY_MAP.get(st.session_state.get("active_category", "הכל"), "all")
    st.markdown(get_styles(active_page, active_cat_key), unsafe_allow_html=True)

    recipes_data = api_get("/recipes") or []
    render_header(recipe_count=len(recipes_data))

    page = st.session_state.page
    if page == "recipes":
        page_recipes()
    elif page == "create":
        page_create()
    elif page == "url_import":
        page_url_import()
    elif page == "text_import":
        page_text_import()
    else:
        page_recipes()


if __name__ == "__main__":
    main()
