import streamlit as st

from app.api_client import api_post, api_post_result
from app.config import AI_IMPORT_TIMEOUT, AI_STAGE_FIELDS, AI_STAGE_LABELS, AI_STAGE_ORDER, VALID_CATEGORIES
from app.state import _go


def _form_key(gen: int, field: str, index: int | None = None) -> str:
    suffix = f"_{index}" if index is not None else ""
    return f"create_{field}_{gen}{suffix}"


def _default_ingredient(suggested: dict, index: int) -> tuple[str, float, str]:
    suggested_ings = suggested.get("ingredients", [])
    if index >= len(suggested_ings):
        return "", 0.0, ""
    item = suggested_ings[index]
    return item.get("name", ""), float(item.get("amount") or 0.0), item.get("unit") or ""


def _default_step(suggested: dict, index: int) -> str:
    suggested_steps = suggested.get("steps", [])
    if index >= len(suggested_steps):
        return ""
    return suggested_steps[index].get("instruction", "")


def _build_recipe_from_widget_state(gen: int, fallback: dict) -> dict:
    name = str(st.session_state.get(_form_key(gen, "name"), fallback.get("name", ""))).strip()
    description = str(st.session_state.get(_form_key(gen, "desc"), fallback.get("description", "") or "")).strip()
    category = st.session_state.get(_form_key(gen, "category"), fallback.get("category", "ארוחת ערב"))
    prep_time = int(st.session_state.get(_form_key(gen, "prep_time"), int(fallback.get("prep_time") or 0)))
    cook_time = int(st.session_state.get(_form_key(gen, "cook_time"), int(fallback.get("cook_time") or 0)))
    servings = int(st.session_state.get(_form_key(gen, "servings"), int(fallback.get("servings") or 2)))

    n_ingredients = int(
        st.session_state.get(
            _form_key(gen, "n_ingredients"),
            min(20, max(1, len(fallback.get("ingredients", [])))),
        )
    )
    ingredients = []
    for i in range(n_ingredients):
        default_name, default_amount, default_unit = _default_ingredient(fallback, i)
        ing_name = str(st.session_state.get(_form_key(gen, "ing_name", i), default_name)).strip()
        ing_amount = float(st.session_state.get(_form_key(gen, "ing_amt", i), default_amount))
        ing_unit = str(st.session_state.get(_form_key(gen, "ing_unit", i), default_unit)).strip()
        if ing_name:
            entry = {"name": ing_name}
            if ing_amount > 0:
                entry["amount"] = ing_amount
                if ing_unit:
                    entry["unit"] = ing_unit
            ingredients.append(entry)

    n_steps = int(
        st.session_state.get(
            _form_key(gen, "n_steps"),
            min(20, max(1, len(fallback.get("steps", [])))),
        )
    )
    steps = []
    for i in range(n_steps):
        default_instruction = _default_step(fallback, i)
        instruction = str(st.session_state.get(_form_key(gen, "step", i), default_instruction)).strip()
        if instruction:
            steps.append({"order": i + 1, "instruction": instruction})

    return {
        "name": name,
        "description": description or None,
        "category": category,
        "prep_time": prep_time,
        "cook_time": cook_time,
        "servings": servings,
        "ingredients": ingredients,
        "steps": steps,
    }


def _recipe_for_retry(gen: int, fallback: dict, failed_stage_index: int) -> dict:
    recipe = _build_recipe_from_widget_state(gen, fallback)
    allowed_fields = []
    for stage in AI_STAGE_ORDER[:failed_stage_index]:
        allowed_fields.extend(AI_STAGE_FIELDS[stage])
    return {field: recipe[field] for field in allowed_fields if field in recipe}


def _render_create_form(container, suggested: dict, gen: int, *, disabled: bool = False):
    with container.container():
        with st.form(f"create_form_{gen}"):
            st.markdown("#### פרטי המתכון")
            name = st.text_input(
                "שם המתכון *",
                value=suggested.get("name", ""),
                key=_form_key(gen, "name"),
                disabled=disabled,
            )
            desc = st.text_area(
                "תיאור",
                value=suggested.get("description", "") or "",
                height=80,
                key=_form_key(gen, "desc"),
                disabled=disabled,
            )

            col1, col2, col3, col4 = st.columns(4)
            suggested_cat = suggested.get("category", "ארוחת ערב")
            cat_index = VALID_CATEGORIES.index(suggested_cat) if suggested_cat in VALID_CATEGORIES else 2
            with col1:
                category = st.selectbox(
                    "קטגוריה", VALID_CATEGORIES, index=cat_index,
                    key=_form_key(gen, "category"), disabled=disabled,
                )
            with col2:
                prep_time = st.number_input(
                    "זמן הכנה (דק')", min_value=0,
                    value=int(suggested.get("prep_time") or 0),
                    key=_form_key(gen, "prep_time"), disabled=disabled,
                )
            with col3:
                cook_time = st.number_input(
                    "זמן בישול (דק')", min_value=0,
                    value=int(suggested.get("cook_time") or 0),
                    key=_form_key(gen, "cook_time"), disabled=disabled,
                )
            with col4:
                servings = st.number_input(
                    "מנות", min_value=1,
                    value=int(suggested.get("servings") or 2),
                    key=_form_key(gen, "servings"), disabled=disabled,
                )

            st.markdown("#### 🥕 מרכיבים")
            suggested_ings = suggested.get("ingredients", [])
            n_ingredients = st.number_input(
                "מספר מרכיבים", min_value=1, max_value=20,
                value=min(20, max(1, len(suggested_ings))),
                key=_form_key(gen, "n_ingredients"), disabled=disabled,
            )
            ingredients = []
            for i in range(int(n_ingredients)):
                c1, c2, c3 = st.columns([3, 1, 1])
                default_name, default_amount, default_unit = _default_ingredient(suggested, i)
                ing_name = c1.text_input(
                    "מרכיב", value=default_name, key=_form_key(gen, "ing_name", i),
                    label_visibility="collapsed", placeholder=f"מרכיב {i+1}", disabled=disabled,
                )
                ing_amount = c2.number_input(
                    "כמות", value=default_amount, key=_form_key(gen, "ing_amt", i),
                    label_visibility="collapsed", min_value=0.0, step=0.5, disabled=disabled,
                )
                ing_unit = c3.text_input(
                    "יח'", value=default_unit, key=_form_key(gen, "ing_unit", i),
                    label_visibility="collapsed", placeholder="גרם / כף...", disabled=disabled,
                )
                if ing_name.strip():
                    entry = {"name": ing_name.strip()}
                    if ing_amount > 0:
                        entry["amount"] = ing_amount
                        if ing_unit.strip():
                            entry["unit"] = ing_unit.strip()
                    ingredients.append(entry)

            st.markdown("#### 📋 שלבי הכנה")
            suggested_steps = suggested.get("steps", [])
            n_steps = st.number_input(
                "מספר שלבים", min_value=1, max_value=20,
                value=min(20, max(1, len(suggested_steps))),
                key=_form_key(gen, "n_steps"), disabled=disabled,
            )
            steps = []
            for i in range(int(n_steps)):
                default_instruction = _default_step(suggested, i)
                instruction = st.text_area(
                    f"שלב {i+1}", value=default_instruction, key=_form_key(gen, "step", i),
                    height=70, label_visibility="collapsed",
                    placeholder=f"שלב {i+1}...", disabled=disabled,
                )
                if instruction.strip():
                    steps.append({"order": i + 1, "instruction": instruction.strip()})

            submitted = st.form_submit_button(
                "💾 שמור מתכון", type="primary", use_container_width=True, disabled=disabled,
            )

    payload = {
        "name": name.strip(),
        "description": desc or None,
        "category": category,
        "prep_time": prep_time,
        "cook_time": cook_time,
        "servings": servings,
        "ingredients": ingredients,
        "steps": steps,
    }
    return submitted, payload


def _ai_status_text() -> str:
    statuses = st.session_state.get("ai_stage_statuses", {})
    parts = []
    for stage in AI_STAGE_ORDER:
        state = statuses.get(stage, "pending")
        if state == "done":
            parts.append(f"✅ {AI_STAGE_LABELS[stage]}")
        elif state == "running":
            parts.append(f"⏳ {AI_STAGE_LABELS[stage]}")
        elif state == "failed":
            parts.append(f"❌ {AI_STAGE_LABELS[stage]}")
        else:
            parts.append(f"• {AI_STAGE_LABELS[stage]}")
    return " | ".join(parts)


def _detail_message(detail) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def _run_ai_generation(form_placeholder, status_placeholder, *, start_stage_index: int, base_recipe: dict) -> None:
    st.session_state["ai_generating"] = True
    st.session_state["ai_failed_stage"] = None
    st.session_state["ai_last_error"] = None
    st.session_state["ai_draft_recipe"] = dict(base_recipe)
    preview_gen = st.session_state.get("suggest_gen", 0)

    for idx in range(start_stage_index, len(AI_STAGE_ORDER)):
        stage = AI_STAGE_ORDER[idx]
        statuses = dict(st.session_state.get("ai_stage_statuses", {}))
        statuses[stage] = "running"
        st.session_state["ai_stage_statuses"] = statuses
        st.session_state["ai_current_stage_index"] = idx
        status_placeholder.info(f"🤖 ממלא כעת: {AI_STAGE_LABELS[stage]}\n\n{_ai_status_text()}")

        preview_gen += 1
        _render_create_form(form_placeholder, st.session_state["ai_draft_recipe"], preview_gen, disabled=True)

        result, detail, _status_code = api_post_result(
            "/recipes/suggest/stage",
            json_data={
                "stage": stage,
                "recipe": st.session_state["ai_draft_recipe"],
                "prompt": st.session_state.get("ai_suggest_prompt"),
            },
            timeout=AI_IMPORT_TIMEOUT,
        )

        if result is None:
            statuses[stage] = "failed"
            st.session_state["ai_stage_statuses"] = statuses
            st.session_state["ai_generating"] = False
            st.session_state["ai_failed_stage"] = stage
            st.session_state["ai_last_error"] = _detail_message(detail)
            st.session_state["suggest_gen"] = preview_gen + 1
            st.rerun()

        st.session_state["ai_draft_recipe"] = result["recipe"]
        st.session_state["ai_suggested"] = result["recipe"]
        statuses[stage] = "done"
        st.session_state["ai_stage_statuses"] = statuses

        preview_gen += 1
        _render_create_form(form_placeholder, st.session_state["ai_draft_recipe"], preview_gen, disabled=True)

    st.session_state["ai_generating"] = False
    st.session_state["ai_failed_stage"] = None
    st.session_state["ai_last_error"] = None
    st.session_state["ai_current_stage_index"] = len(AI_STAGE_ORDER)
    st.session_state["suggest_gen"] = preview_gen + 1
    st.rerun()


def page_create() -> None:
    st.markdown("## ➕ צור מתכון חדש")

    notice = st.session_state.pop("create_prefill_notice", None)
    if notice:
        st.success(notice)

    if "ai_draft_recipe" not in st.session_state:
        st.session_state["ai_draft_recipe"] = dict(st.session_state.get("ai_suggested", {}))
    if "ai_stage_statuses" not in st.session_state:
        st.session_state["ai_stage_statuses"] = {stage: "pending" for stage in AI_STAGE_ORDER}
    if "ai_current_stage_index" not in st.session_state:
        st.session_state["ai_current_stage_index"] = 0
    if "ai_failed_stage" not in st.session_state:
        st.session_state["ai_failed_stage"] = None
    if "ai_generating" not in st.session_state:
        st.session_state["ai_generating"] = False
    if "ai_last_error" not in st.session_state:
        st.session_state["ai_last_error"] = None

    actions = st.container()
    status_placeholder = st.empty()
    form_placeholder = st.empty()

    suggested = st.session_state.get("ai_draft_recipe", {}) or st.session_state.get("ai_suggested", {})
    gen = st.session_state.get("suggest_gen", 0)
    generating = st.session_state.get("ai_generating", False)
    failed_stage = st.session_state.get("ai_failed_stage")

    with actions:
        suggest_prompt = st.text_input(
            "רעיון למתכון (אופציונלי)",
            key="ai_suggest_prompt_input",
            placeholder="למשל: פסטה עם עוף, קינוח קל לשבת...",
            disabled=generating,
        )
        start_clicked = st.button("✨ הצע מתכון עם AI", type="secondary", disabled=generating)
        retry_clicked = False
        if failed_stage:
            retry_clicked = st.button(
                f"🔁 נסה שוב משלב {AI_STAGE_LABELS[failed_stage]}",
                type="secondary",
                disabled=generating,
            )

    if generating:
        current_stage = AI_STAGE_ORDER[min(
            st.session_state.get("ai_current_stage_index", 0), len(AI_STAGE_ORDER) - 1
        )]
        status_placeholder.info(f"🤖 ממלא כעת: {AI_STAGE_LABELS[current_stage]}\n\n{_ai_status_text()}")
    elif failed_stage and st.session_state.get("ai_last_error"):
        status_placeholder.error(
            f"יצירת המתכון נעצרה בשלב {AI_STAGE_LABELS[failed_stage]}: "
            f"{st.session_state['ai_last_error']}"
        )
    elif any(state == "done" for state in st.session_state.get("ai_stage_statuses", {}).values()):
        status_placeholder.success(f"✨ טיוטת המתכון עודכנה.\n\n{_ai_status_text()}")

    submitted, payload = _render_create_form(form_placeholder, suggested, gen, disabled=generating)

    if start_clicked:
        st.session_state["ai_draft_recipe"] = {}
        st.session_state["ai_suggested"] = {}
        st.session_state["ai_stage_statuses"] = {stage: "pending" for stage in AI_STAGE_ORDER}
        st.session_state["ai_current_stage_index"] = 0
        st.session_state["ai_suggest_prompt"] = suggest_prompt.strip() or None
        _run_ai_generation(form_placeholder, status_placeholder, start_stage_index=0, base_recipe={})

    if retry_clicked and failed_stage:
        failed_index = AI_STAGE_ORDER.index(failed_stage)
        base_recipe = _recipe_for_retry(gen, suggested, failed_index)
        statuses = dict(st.session_state.get("ai_stage_statuses", {}))
        for stage in AI_STAGE_ORDER[failed_index:]:
            statuses[stage] = "pending"
        st.session_state["ai_stage_statuses"] = statuses
        _run_ai_generation(
            form_placeholder, status_placeholder,
            start_stage_index=failed_index, base_recipe=base_recipe,
        )

    if submitted:
        if not payload["name"]:
            st.error("חובה למלא שם מתכון")
        else:
            result = api_post("/recipes", json_data=payload)
            if result:
                st.success(f"✅ המתכון '{payload['name']}' נשמר בהצלחה!")
                for key in [
                    "ai_suggested", "ai_draft_recipe", "ai_stage_statuses",
                    "ai_current_stage_index", "ai_failed_stage", "ai_generating", "ai_last_error",
                ]:
                    st.session_state.pop(key, None)
                st.session_state["suggest_gen"] = st.session_state.get("suggest_gen", 0) + 1
                _go("recipes")
                st.rerun()
