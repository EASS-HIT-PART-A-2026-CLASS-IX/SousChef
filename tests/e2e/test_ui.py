"""
Comprehensive Playwright-driven end-to-end coverage for the SousChef UI.

These tests boot the real backend + Streamlit frontend via conftest.py and
exercise the major user-facing flows end to end.
"""
from __future__ import annotations

import os
import re

import httpx
import pytest
from playwright.sync_api import Page, expect


def _http() -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=10.0)


DEFAULT_TIMEOUT_MS = 15_000


def _open_app(page: Page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    expect(page.locator('div[data-testid="stAppViewContainer"]')).to_be_visible(
        timeout=DEFAULT_TIMEOUT_MS,
    )


def _wait_idle(page: Page) -> None:
    page.wait_for_load_state("networkidle")


def _goto_nav(page: Page, label: str) -> None:
    page.get_by_role("button", name=label).first.click()
    _wait_idle(page)


def _commit_text_input(locator) -> None:
    locator.press("Enter")


def _commit_text_area(locator) -> None:
    locator.press("Meta+Enter")


def _reset_mock(ollama_url: str) -> None:
    if os.getenv("E2E_AI_MODE", "mock") != "mock":
        return
    with _http() as client:
        client.post(f"{ollama_url}/__reset").raise_for_status()


def _configure_mock(ollama_url: str, *, fail_stage_once=None, fail_stage_always=None) -> None:
    if os.getenv("E2E_AI_MODE", "mock") != "mock":
        return
    with _http() as client:
        client.post(
            f"{ollama_url}/__configure",
            json={
                "fail_stage_once": fail_stage_once or [],
                "fail_stage_always": fail_stage_always or [],
            },
        ).raise_for_status()


def _open_first_recipe_drawer(page: Page) -> None:
    page.locator("a.sc-card-link").first.click()
    _wait_idle(page)
    expect(page.locator('section[data-testid="stSidebar"] .sc-recipe-drawer')).to_be_visible(
        timeout=DEFAULT_TIMEOUT_MS,
    )


def _backdrop_button(page: Page):
    return page.locator('[class*="st-key-drawer_backdrop_"] button').first


class TestHeader:
    def test_brand_and_count_pill_render(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.get_by_text("SousChef", exact=False).first).to_be_visible()
        expect(page.get_by_text("Your Personal SousChef")).to_be_visible()
        expect(page.locator(".sc-count-pill")).to_contain_text("3")
        expect(page.locator(".sc-count-pill")).to_contain_text("מתכונים")
        capture_step("header-and-count")

    def test_count_updates_after_api_create(self, page: Page, frontend_url: str, backend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.locator(".sc-count-pill")).to_contain_text("3")
        with _http() as client:
            client.post(
                f"{backend_url}/recipes",
                json={"name": "מרק עוף", "category": "אחר"},
            ).raise_for_status()
        page.reload(wait_until="networkidle")
        expect(page.locator(".sc-count-pill")).to_contain_text("4")
        capture_step("count-updated")


class TestNavigation:
    @pytest.mark.parametrize(
        ("label", "heading"),
        [
            ("צור מתכון", "צור מתכון חדש"),
            ("ייבוא מ-URL", "ייבוא מתכון מ-URL"),
            ("ייבוא מטקסט", "ייבוא מתכון מטקסט / תמונה"),
        ],
    )
    def test_nav_switches_pages(self, page: Page, frontend_url: str, seed_recipes, label, heading, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, label)
        expect(page.get_by_text(heading)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step(f"nav-{label}")

    def test_back_to_recipes_from_create(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")
        expect(page.get_by_text("צור מתכון חדש")).to_be_visible()

        _goto_nav(page, "כל המתכונים")
        expect(page.locator(".sc-card").first).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("recipes-grid-after-nav")


class TestRecipeGrid:
    def test_cards_render_with_badges(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.locator(".sc-card")).to_have_count(3)
        for recipe in seed_recipes:
            expect(page.locator(".sc-card-title", has_text=recipe["name"])).to_be_visible()
        expect(page.locator(".sc-card-badge")).to_have_count(3)
        capture_step("grid-cards")

    def test_empty_state(self, page: Page, frontend_url: str, empty_db, capture_step):
        _open_app(page, frontend_url)
        expect(page.get_by_text("לא נמצאו מתכונים")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("empty-state")

    def test_search_filters_grid(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.locator(".sc-card")).to_have_count(3)

        search = page.get_by_placeholder("חיפוש מתכון...")
        search.fill("פסטה")
        _commit_text_input(search)
        _wait_idle(page)

        expect(page.locator(".sc-card")).to_have_count(1, timeout=DEFAULT_TIMEOUT_MS)
        expect(page.locator(".sc-card-title")).to_contain_text("פסטה")
        capture_step("grid-search-filter")

    def test_category_filter_pills(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.locator(".sc-card")).to_have_count(3)

        page.get_by_role("button", name="ארוחת בוקר").click()
        _wait_idle(page)
        expect(page.locator(".sc-card")).to_have_count(1)
        expect(page.locator(".sc-card-title")).to_contain_text("חביתה")

        page.get_by_role("button", name="הכל").click()
        _wait_idle(page)
        expect(page.locator(".sc-card")).to_have_count(3)
        capture_step("category-filter-reset")


class TestRecipeDrawer:
    def test_open_card_shows_drawer_and_close_x(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _open_first_recipe_drawer(page)

        expect(page.get_by_text("מרכיבים", exact=False).first).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_text("שלבי הכנה", exact=False).first).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("drawer-open")

        page.get_by_role("button", name="✕").click()
        _wait_idle(page)
        expect(page.locator('section[data-testid="stSidebar"] .sc-recipe-drawer')).to_have_count(0)
        capture_step("drawer-closed-x")

    def test_drawer_closes_on_backdrop_click(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _open_first_recipe_drawer(page)

        expect(_backdrop_button(page)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        _backdrop_button(page).click()
        _wait_idle(page)
        expect(page.locator('section[data-testid="stSidebar"] .sc-recipe-drawer')).to_have_count(0)
        capture_step("drawer-closed-backdrop")

    def test_direct_recipe_link_opens_drawer(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        recipe_id = seed_recipes[1]["id"]
        page.goto(f"{frontend_url}?recipe_id={recipe_id}", wait_until="networkidle")
        expect(page.locator('section[data-testid="stSidebar"] .sc-recipe-drawer')).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        expect(page.locator(".recipe-title")).to_contain_text(seed_recipes[1]["name"])
        capture_step("drawer-deep-link")

    def test_drawer_inline_edit_updates_recipe(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _open_first_recipe_drawer(page)

        page.get_by_role("button", name=re.compile("ערוך")).click()
        _wait_idle(page)
        expect(page.get_by_text("עריכת מתכון")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)

        name_input = page.get_by_label("שם המתכון")
        name_input.fill("חביתה משודרגת")
        page.get_by_role("button", name=re.compile("שמור שינויים")).click()
        _wait_idle(page)

        expect(page.locator(".recipe-title")).to_contain_text("חביתה משודרגת")
        capture_step("drawer-edit-saved")

    def test_drawer_inline_edit_cancel_returns_to_detail(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _open_first_recipe_drawer(page)

        page.get_by_role("button", name=re.compile("ערוך")).click()
        _wait_idle(page)
        expect(page.get_by_text("עריכת מתכון")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)

        page.get_by_role("button", name="ביטול").click()
        _wait_idle(page)
        expect(page.get_by_text("עריכת מתכון")).to_have_count(0)
        expect(page.locator(".recipe-title")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("drawer-edit-cancelled")

    def test_drawer_delete_removes_recipe_and_closes(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.locator(".sc-card")).to_have_count(3)

        _open_first_recipe_drawer(page)
        page.get_by_role("button", name=re.compile("מחק")).click()
        _wait_idle(page)

        expect(page.locator('section[data-testid="stSidebar"] .sc-recipe-drawer')).to_have_count(0)
        expect(page.locator(".sc-card")).to_have_count(2)
        capture_step("drawer-delete")

    def test_ai_improve_renders_inside_drawer(self, page: Page, frontend_url: str, ollama_url: str, seed_recipes, capture_step):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _open_first_recipe_drawer(page)

        page.get_by_role("button", name=re.compile("שפר את המתכון")).click()
        _wait_idle(page)
        expect(page.locator('section[data-testid="stSidebar"] .ai-result')).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("drawer-ai-improve")


class TestCreateFlow:
    def test_manual_create_full_recipe_persists_and_opens(self, page: Page, frontend_url: str, empty_db, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")

        page.get_by_label("שם המתכון *").fill("טוסט גבינה")
        page.get_by_label("תיאור").fill("טוסט פשוט עם גבינה צהובה")
        page.get_by_label("זמן הכנה (דק')").fill("4")
        page.get_by_label("זמן בישול (דק')").fill("6")
        page.get_by_label("מנות").fill("2")
        page.get_by_placeholder("מרכיב 1").fill("גבינה צהובה")
        page.get_by_placeholder("גרם / כף...").fill("פרוסות")
        page.get_by_placeholder("שלב 1...").fill("לקלות את הטוסט עד שהגבינה נמסה")

        page.get_by_role("button", name=re.compile("שמור מתכון")).click()
        _wait_idle(page)

        expect(page.locator(".sc-card-title", has_text="טוסט גבינה")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        page.locator("a.sc-card-link").first.click()
        _wait_idle(page)
        sidebar = page.get_by_test_id("stSidebarUserContent")
        expect(sidebar.get_by_text("גבינה צהובה", exact=True)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        expect(sidebar.get_by_text("לקלות את הטוסט", exact=False)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("manual-create-saved")

    def test_manual_create_requires_name(self, page: Page, frontend_url: str, empty_db, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")
        page.get_by_role("button", name=re.compile("שמור מתכון")).click()
        _wait_idle(page)
        expect(page.get_by_text("חובה למלא שם מתכון")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("manual-create-validation")

    def test_ai_suggest_fills_form_via_staged_calls(self, page: Page, frontend_url: str, ollama_url: str, empty_db, capture_step):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")

        page.get_by_role("button", name=re.compile("הצע מתכון עם AI")).click()

        expect(page.get_by_label("שם המתכון *")).to_have_value("מתכון ניסוי E2E", timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_label("תיאור")).to_have_value(
            "מתכון שנוצר על ידי שרת ה-mock לבדיקות e2e",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("ai-suggest-filled")

        if os.getenv("E2E_AI_MODE", "mock") == "mock":
            with _http() as client:
                hits = client.get(f"{ollama_url}/__hits").json()
            prompts = [hit["prompt"] or "" for hit in hits["hits"]]
            assert any("שלב 1: החזר רק את שם המתכון" in prompt for prompt in prompts)
            assert any("שלב 2:" in prompt for prompt in prompts)
            assert any("שלב 3:" in prompt for prompt in prompts)
            assert any("שלב 4:" in prompt for prompt in prompts)
            assert any("שלב 5:" in prompt for prompt in prompts)

    def test_ai_suggest_can_be_saved_to_grid(self, page: Page, frontend_url: str, ollama_url: str, empty_db, capture_step):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")
        page.get_by_role("button", name=re.compile("הצע מתכון עם AI")).click()

        expect(page.get_by_label("שם המתכון *")).to_have_value("מתכון ניסוי E2E", timeout=DEFAULT_TIMEOUT_MS)
        page.get_by_role("button", name=re.compile("שמור מתכון")).click()
        _wait_idle(page)

        expect(page.locator(".sc-card-title", has_text="מתכון ניסוי E2E")).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        expect(page.locator(".sc-count-pill")).to_contain_text("1")
        capture_step("ai-suggest-saved")

    def test_ai_suggest_retry_from_failed_stage(self, page: Page, frontend_url: str, ollama_url: str, empty_db, capture_step):
        if os.getenv("E2E_AI_MODE", "mock") != "mock":
            pytest.skip("Retry orchestration is only deterministic with the mock Ollama server")

        _reset_mock(ollama_url)
        _configure_mock(ollama_url, fail_stage_always=["description"])

        _open_app(page, frontend_url)
        _goto_nav(page, "צור מתכון")
        page.get_by_role("button", name=re.compile("הצע מתכון עם AI")).click()

        expect(page.get_by_text(re.compile("יצירת המתכון נעצרה בשלב תיאור"))).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("ai-suggest-failed")

        _configure_mock(ollama_url)
        page.get_by_role("button", name=re.compile("נסה שוב משלב")).click()
        expect(page.get_by_label("שם המתכון *")).to_have_value("מתכון ניסוי E2E", timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_text(re.compile("טיוטת המתכון עודכנה"))).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("ai-suggest-retried")


class TestAIIntegration:
    def test_ai_search_button_renders(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        expect(page.get_by_role("button", name="חפש עם AI")).to_be_visible()
        expect(page.get_by_placeholder(re.compile("שאל AI"))).to_be_visible()
        capture_step("ai-search-input")

    def test_ai_search_hits_ollama(self, page: Page, frontend_url: str, ollama_url: str, seed_recipes, capture_step):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        ai_input = page.get_by_placeholder(re.compile("שאל AI"))
        ai_input.fill("משהו מהיר לארוחת ערב")
        _commit_text_input(ai_input)
        _wait_idle(page)

        page.get_by_role("button", name="חפש עם AI").click()
        _wait_idle(page)
        expect(page.locator(".ai-result")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        capture_step("ai-search-result")

        if os.getenv("E2E_AI_MODE", "mock") == "mock":
            with _http() as client:
                hits = client.get(f"{ollama_url}/__hits").json()
            assert hits["count"] >= 1
            assert any("המלץ בעברית" in (hit["prompt"] or "") for hit in hits["hits"])


class TestImportFlows:
    def test_url_import_page_renders(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, "ייבוא מ-URL")
        expect(page.get_by_placeholder(re.compile(r"https"))).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("ייבא מתכון"))).to_be_visible()
        capture_step("url-import-page")

    def test_text_import_page_renders(self, page: Page, frontend_url: str, seed_recipes, capture_step):
        _open_app(page, frontend_url)
        _goto_nav(page, "ייבוא מטקסט")
        expect(page.get_by_placeholder(re.compile("הדבק כאן את הטקסט"))).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("עבד עם AI"))).to_be_visible()
        capture_step("text-import-page")

    def test_url_import_extracts_recipe_and_opens_create_draft(
        self,
        page: Page,
        frontend_url: str,
        recipe_source_url: str,
        ollama_url: str,
        empty_db,
        capture_step,
    ):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _goto_nav(page, "ייבוא מ-URL")

        page.get_by_label("כתובת URL").fill(f"{recipe_source_url}/recipe")
        page.get_by_role("button", name=re.compile("ייבא מתכון")).click()
        _wait_idle(page)

        expect(page.get_by_text("צור מתכון חדש")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_text("טיוטת המתכון חולצה מהקישור", exact=False)).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        expect(page.get_by_label("שם המתכון *")).to_have_value("מתכון ניסוי E2E", timeout=DEFAULT_TIMEOUT_MS)
        capture_step("url-import-draft")

        page.get_by_role("button", name=re.compile("שמור מתכון")).click()
        _wait_idle(page)
        expect(page.locator(".sc-card-title", has_text="מתכון ניסוי E2E")).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        expect(page.locator(".sc-count-pill")).to_contain_text("1")
        capture_step("url-import-grid")

    def test_text_import_extracts_recipe_and_saves_to_grid(
        self,
        page: Page,
        frontend_url: str,
        ollama_url: str,
        empty_db,
        capture_step,
    ):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _goto_nav(page, "ייבוא מטקסט")

        text_input = page.get_by_label("טקסט המתכון")
        text_input.fill(
            "פסטה מהירה\nמרכיבים: פסטה, עגבניות, שמן זית\nשלבים: לבשל, לערבב, להגיש"
        )
        _commit_text_area(text_input)
        page.get_by_role("button", name=re.compile("עבד עם AI")).click()
        _wait_idle(page)

        expect(page.get_by_text("המתכון חולץ בהצלחה", exact=False)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_role("heading", name="מתכון ניסוי E2E")).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("text-import-result")

        _goto_nav(page, "כל המתכונים")
        expect(page.locator(".sc-card-title", has_text="מתכון ניסוי E2E")).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        expect(page.locator(".sc-count-pill")).to_contain_text("1")
        capture_step("text-import-grid")

    def test_image_import_extracts_recipe_and_shows_preview(
        self,
        page: Page,
        frontend_url: str,
        ollama_url: str,
        sample_upload_image,
        empty_db,
        capture_step,
    ):
        _reset_mock(ollama_url)

        _open_app(page, frontend_url)
        _goto_nav(page, "ייבוא מטקסט")

        page.locator('input[type="file"]').set_input_files(str(sample_upload_image))
        expect(page.get_by_text("תמונה שהועלתה")).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        page.get_by_role("button", name=re.compile("עבד עם AI")).click()
        _wait_idle(page)

        expect(page.get_by_text("המתכון חולץ בהצלחה", exact=False)).to_be_visible(timeout=DEFAULT_TIMEOUT_MS)
        expect(page.get_by_role("heading", name="מתכון ניסוי E2E")).to_be_visible(
            timeout=DEFAULT_TIMEOUT_MS,
        )
        capture_step("image-import-result")
