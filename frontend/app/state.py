import streamlit as st

from app.config import AI_STAGE_ORDER


def _set_open_recipe(recipe_id: int | None) -> None:
    if recipe_id != st.session_state.get("open_recipe_id"):
        st.session_state.pop("edit_recipe_id", None)
    st.session_state.open_recipe_id = recipe_id
    if recipe_id is None:
        if "recipe_id" in st.query_params:
            del st.query_params["recipe_id"]
        return
    st.query_params["recipe_id"] = str(recipe_id)


def _sync_open_recipe_from_query_params() -> None:
    recipe_id_raw = st.query_params.get("recipe_id")
    if recipe_id_raw in (None, ""):
        if st.session_state.get("page") == "recipes":
            st.session_state.open_recipe_id = None
            st.session_state.pop("edit_recipe_id", None)
        return
    try:
        recipe_id = int(str(recipe_id_raw))
    except (TypeError, ValueError):
        if "recipe_id" in st.query_params:
            del st.query_params["recipe_id"]
        if st.session_state.get("page") == "recipes":
            st.session_state.open_recipe_id = None
            st.session_state.pop("edit_recipe_id", None)
        return
    st.session_state.page = "recipes"
    _set_open_recipe(recipe_id)


def _clear_recipe_drawer() -> None:
    st.session_state.pop("edit_recipe_id", None)
    _set_open_recipe(None)


def _go(page: str) -> None:
    st.session_state.page = page
    _set_open_recipe(None)


def _seed_create_draft(recipe: dict, *, notice: str | None = None) -> None:
    st.session_state["ai_suggested"] = dict(recipe)
    st.session_state["ai_draft_recipe"] = dict(recipe)
    st.session_state["ai_stage_statuses"] = {stage: "pending" for stage in AI_STAGE_ORDER}
    st.session_state["ai_current_stage_index"] = 0
    st.session_state["ai_failed_stage"] = None
    st.session_state["ai_generating"] = False
    st.session_state["ai_last_error"] = None
    st.session_state["suggest_gen"] = st.session_state.get("suggest_gen", 0) + 1
    if notice:
        st.session_state["create_prefill_notice"] = notice
