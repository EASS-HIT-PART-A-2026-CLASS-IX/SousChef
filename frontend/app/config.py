import os

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
AI_IMPORT_TIMEOUT = int(os.getenv("AI_IMPORT_TIMEOUT", "180"))

VALID_CATEGORIES = ["ארוחת בוקר", "ארוחת צהריים", "ארוחת ערב", "קינוח", "חטיף", "אחר"]

CAT_KEY_MAP = {
    "הכל":          "all",
    "ארוחת בוקר":   "breakfast",
    "ארוחת צהריים": "lunch",
    "ארוחת ערב":    "dinner",
    "קינוח":        "dessert",
    "חטיף":         "snack",
    "אחר":          "other",
}

CATEGORY_COLORS = {
    "ארוחת בוקר":   {"bg": "#FCE9C9", "fg": "#8A5A1F"},
    "ארוחת צהריים": {"bg": "#D6F1DC", "fg": "#1F6B36"},
    "ארוחת ערב":    {"bg": "#D8DEFB", "fg": "#3946A8"},
    "קינוח":        {"bg": "#FBD7E5", "fg": "#9B2A55"},
    "חטיף":         {"bg": "#CDEBF4", "fg": "#1E6E84"},
    "אחר":          {"bg": "#EAE5DC", "fg": "#5C5247"},
}

PAGES = [
    ("recipes",     "🍽 כל המתכונים"),
    ("create",      "➕ צור מתכון"),
    ("url_import",  "🔗 ייבוא מ-URL"),
    ("text_import", "📝 ייבוא מטקסט"),
]

AI_STAGE_ORDER = ["name", "description", "meta", "ingredients", "steps"]
AI_STAGE_LABELS = {
    "name":        "שם המתכון",
    "description": "תיאור",
    "meta":        "קטגוריה, זמנים ומנות",
    "ingredients": "מרכיבים",
    "steps":       "שלבי הכנה",
}
AI_STAGE_FIELDS = {
    "name":        ["name"],
    "description": ["description"],
    "meta":        ["category", "prep_time", "cook_time", "servings"],
    "ingredients": ["ingredients"],
    "steps":       ["steps"],
}
