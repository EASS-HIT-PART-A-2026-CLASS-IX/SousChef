_BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Heebo', sans-serif !important;
    direction: rtl;
}

html, body, .stApp, .block-container {
    direction: rtl !important;
    text-align: right !important;
}

h1, h2, h3, h4, h5, h6, p, label,
[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"],
[data-testid="stAlertContainer"],
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"],
[data-testid="stExpander"],
[data-testid="stFileUploader"],
[data-testid="stText"],
.stMarkdown, .stCaption {
    direction: rtl !important;
    text-align: right !important;
}

[data-testid="stHorizontalBlock"] { direction: rtl !important; }
[data-testid="column"] { direction: rtl !important; }

.stApp { background: #FAF4EA; }

header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu, footer { display: none !important; }

.block-container { padding-top: 0 !important; max-width: 1400px; }

[data-testid="stLayoutWrapper"]:has([class*="st-key-nav_"]) {
    background: #FFFFFF;
    border-bottom: 1px solid #ECE3D2;
    border-radius: 0;
    padding: 8px 80px;
}

.sc-brand { display: flex; align-items: center; gap: 10px; }
.sc-brand-icon { font-size: 28px; line-height: 1; }
.sc-brand-text { text-align: right; line-height: 1.05; }
.sc-brand-title { font-size: 18px; font-weight: 800; letter-spacing: -0.3px; color: #C5552D; unicode-bidi: plaintext; }
.sc-brand-tag { font-size: 11px; color: #9A8B78; margin-top: -2px; unicode-bidi: plaintext; }

.sc-count-pill {
    display: inline-block;
    background: #F1EAD9;
    color: #6E5F47;
    padding: 4px 12px;
    border-radius: 99px;
    font-weight: 600; font-size: 12px;
    direction: rtl;
    white-space: nowrap;
    line-height: 1.6;
}

[class*="st-key-nav_"] button {
    background: transparent !important;
    color: #4C3F2E !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 8px 16px !important;
    font-weight: 600 !important;
    font-family: 'Heebo', sans-serif !important;
    font-size: 14px !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    width: auto !important;
    min-width: 0 !important;
}
[class*="st-key-nav_"] button:hover { background: #F4ECDC !important; color: #4C3F2E !important; }

[class*="st-key-cat_"] button {
    background: #F1EAD9 !important;
    color: #4C3F2E !important;
    border: none !important;
    border-radius: 99px !important;
    padding: 6px 16px !important;
    font-weight: 600 !important;
    font-family: 'Heebo', sans-serif !important;
    font-size: 13px !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    width: auto !important;
}
[class*="st-key-cat_"] button:hover { background: #E6DCC4 !important; }

[class*="st-key-search_box"] input,
[class*="st-key-ai_search"] input {
    background: #FFFFFF !important;
    border-radius: 99px !important;
    padding: 14px 22px !important;
    font-family: 'Heebo', sans-serif !important;
    font-size: 15px !important;
    text-align: right !important;
    direction: rtl !important;
    unicode-bidi: plaintext !important;
}
[class*="st-key-search_box"] input::placeholder,
[class*="st-key-ai_search"] input::placeholder { color: #B0A290 !important; }
[class*="st-key-search_box"] div[data-baseweb="input"],
[class*="st-key-ai_search"] div[data-baseweb="input"] {
    background: #FFFFFF !important;
    border: 1px solid #ECE3D2 !important;
    border-radius: 99px !important;
    box-shadow: none !important;
}
[class*="st-key-search_box"] [data-testid="stTextInputRootElement"],
[class*="st-key-ai_search"] [data-testid="stTextInputRootElement"] {
    border-radius: 99px !important;
    overflow: hidden;
}

textarea, input, [data-baseweb="select"], [data-baseweb="input"] input,
[data-baseweb="textarea"] textarea {
    direction: rtl !important;
    text-align: right !important;
    unicode-bidi: plaintext !important;
}

[data-baseweb="select"] > div,
[data-baseweb="popover"] ul,
[role="listbox"],
[role="option"] {
    direction: rtl !important;
    text-align: right !important;
}

.stTextInput label, .stTextArea label, .stSelectbox label,
.stNumberInput label, .stFileUploader label {
    width: 100%;
    text-align: right !important;
    direction: rtl !important;
}

[data-testid="stLayoutWrapper"]:has([class*="st-key-ai_search_btn"]) {
    background: linear-gradient(135deg, #F1E8D5, #DCF0DC);
    border-radius: 14px;
    padding: 14px 18px;
    margin: 10px 0 14px 0;
}

[class*="st-key-ai_search_btn"] button {
    background: #C5552D !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 99px !important;
    padding: 14px 22px !important;
    font-family: 'Heebo', sans-serif !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    white-space: nowrap !important;
    width: 100%;
}
[class*="st-key-ai_search_btn"] button:hover { background: #B14A26 !important; }

.sc-card {
    background: #FFFFFF;
    border: 1px solid #ECE3D2;
    border-radius: 18px;
    padding: 22px 22px 18px 22px;
    margin-bottom: 18px;
    direction: rtl;
    transition: box-shadow .18s, transform .18s;
    height: 260px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
}
.sc-card-main { display: flex; flex-direction: column; gap: 8px; }
.sc-card:hover {
    box-shadow: 0 10px 26px rgba(120, 80, 40, 0.10);
    transform: translateY(-2px);
}
.sc-card-link {
    display: block;
    text-decoration: none !important;
    color: inherit !important;
}
.sc-card-link:hover,
.sc-card-link:focus,
.sc-card-link:visited,
.sc-card-link:active { text-decoration: none !important; color: inherit !important; }
.sc-card-link:hover .sc-card,
.sc-card-link:focus .sc-card {
    box-shadow: 0 12px 32px rgba(120, 80, 40, 0.16) !important;
    transform: translateY(-3px) !important;
}
.sc-card-link .sc-card { cursor: pointer; }
.sc-card-badge {
    display: inline-block;
    padding: 4px 12px; border-radius: 99px;
    font-size: 12px; font-weight: 700;
    margin-bottom: 10px;
}
.sc-card-title {
    font-size: 20px; font-weight: 800;
    color: #2A2118; margin-bottom: 6px;
    line-height: 1.35;
    direction: rtl; text-align: right; unicode-bidi: plaintext;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.sc-card-desc {
    font-size: 13px; color: #8A7B66;
    line-height: 1.55; margin-bottom: 14px;
    direction: rtl; text-align: right; unicode-bidi: plaintext;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.sc-card-meta {
    font-size: 12px; color: #6E5F47;
    display: flex; gap: 14px; flex-wrap: wrap;
    border-top: 1px dashed #ECE3D2;
    padding-top: 12px;
    direction: rtl; justify-content: flex-start;
}
.sc-card-meta span { white-space: nowrap; }

[class*="st-key-back_"] button {
    background: transparent !important;
    color: #6E5F47 !important;
    border: none !important;
    padding: 4px 10px !important;
    font-weight: 600 !important;
}
[class*="st-key-back_"] button:hover { background: #F1EAD9 !important; }

.recipe-title { font-size: 26px; font-weight: 800; color: #2A2118; margin: 4px 0 6px; }
.recipe-title, .rtl-copy {
    direction: rtl; text-align: right; unicode-bidi: plaintext;
}
.badge {
    display: inline-block;
    padding: 4px 12px; border-radius: 99px;
    font-size: 12px; font-weight: 700;
    background: #F1EAD9; color: #6E5F47;
    margin-bottom: 8px;
    direction: rtl; unicode-bidi: plaintext;
}

.ai-box {
    background: linear-gradient(135deg, #FCE9D7, #D6F1DC);
    border-radius: 14px; padding: 14px 18px; margin: 10px 0 18px;
    border: 1px solid #ECE3D2;
    color: #4C3F2E; direction: rtl; text-align: right;
}
.ai-result {
    background: #FFFDF7;
    border: 1px solid #ECE3D2;
    border-radius: 12px; padding: 14px 18px; margin-top: 10px;
    font-size: 14px; line-height: 1.8;
    direction: rtl; text-align: right; unicode-bidi: plaintext;
    white-space: pre-wrap;
}

.step-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 50%;
    background: #C5552D; color: white;
    font-size: 13px; font-weight: 700;
    margin-left: 10px; flex-shrink: 0;
}
.ing-row {
    display: flex; justify-content: space-between;
    padding: 10px 14px;
    background: #FAF4EA;
    border-radius: 10px; margin-bottom: 6px;
    font-size: 14px; direction: rtl; align-items: center; unicode-bidi: plaintext;
}
.sc-section-title {
    font-size: 18px; font-weight: 800; color: #2A2118;
    margin: 28px 0 12px; direction: rtl; text-align: right;
}
.sc-detail-desc { color: #9A8B78; font-size: 16px; line-height: 1.7; margin-bottom: 24px; }
.sc-detail-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    background: #F5ECDE;
    border: 1px solid #ECE3D2;
    border-radius: 18px;
    overflow: hidden;
    margin: 20px 0 28px;
    direction: ltr;
}
.sc-detail-stat { padding: 20px 12px 18px; text-align: center; direction: rtl; }
.sc-detail-stat + .sc-detail-stat { border-right: 1px solid #E6D9C4; }
.sc-detail-stat-value { font-size: 30px; font-weight: 800; color: #C5552D; line-height: 1.1; }
.sc-detail-stat-label { font-size: 14px; color: #8A7B66; margin-top: 8px; }
.sc-step-row {
    display: flex; flex-direction: row-reverse;
    gap: 12px; align-items: flex-start; margin-bottom: 14px;
}
.sc-step-text { flex: 1; padding-top: 2px; line-height: 1.8; }

.sc-recipe-drawer { padding-bottom: 28px; }
[class*="st-key-drawer_backdrop_"] {
    position: fixed !important; inset: 0 !important;
    z-index: 999 !important; margin: 0 !important; padding: 0 !important;
}
[class*="st-key-drawer_backdrop_"] button {
    width: 100vw !important; height: 100vh !important; min-height: 100vh !important;
    background: rgba(44, 34, 23, 0.34) !important;
    backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    border: none !important; border-radius: 0 !important; box-shadow: none !important;
    color: transparent !important; font-size: 0 !important; padding: 0 !important;
}
[class*="st-key-drawer_backdrop_"] button:hover { background: rgba(44, 34, 23, 0.34) !important; }

section[data-testid="stSidebar"]:has(.sc-recipe-drawer) {
    position: fixed !important; left: 0 !important; top: 0 !important;
    height: 100vh !important; transform: translateX(0%) !important;
    margin-left: 0 !important;
    min-width: min(44vw, 820px) !important; max-width: 92vw !important;
    width: min(44vw, 820px) !important;
    z-index: 1000 !important;
    border-right: 1px solid #E8DCC7 !important;
    box-shadow: 22px 0 54px rgba(55, 40, 25, 0.18) !important;
}
section[data-testid="stSidebar"]:has(.sc-recipe-drawer) > div {
    background: #FFFBF5 !important; width: 100% !important; min-width: 100% !important;
}
section[data-testid="stSidebar"]:has(.sc-recipe-drawer) [data-testid="stSidebarUserContent"] {
    padding: 18px 28px 24px 28px !important;
}
section[data-testid="stSidebar"]:has(.sc-recipe-drawer) [data-testid="stSidebarCollapseButton"] { display: none !important; }

[class*="st-key-drawer_close_"] button {
    background: transparent !important; color: #8E8275 !important;
    border: none !important; box-shadow: none !important;
    font-size: 42px !important; line-height: 1 !important;
    padding: 0 !important; min-height: 0 !important; min-width: 0 !important;
}
[class*="st-key-drawer_close_"] button:hover { background: transparent !important; color: #5E5247 !important; }

[class*="st-key-drawer_edit_"] button,
[class*="st-key-drawer_delete_"] button {
    border: none !important; border-radius: 999px !important;
    box-shadow: none !important; font-family: 'Heebo', sans-serif !important;
    font-weight: 700 !important; padding: 10px 18px !important;
}
[class*="st-key-drawer_edit_"] button { background: #F1EAD9 !important; color: #4C3F2E !important; }
[class*="st-key-drawer_edit_"] button:hover { background: #E5D9BD !important; }
[class*="st-key-drawer_delete_"] button { background: #FFD7D0 !important; color: #9A3E31 !important; }
[class*="st-key-drawer_delete_"] button:hover { background: #F6C3BA !important; }

[class*="st-key-drawer_recipe_"][class*="_enhance"] button {
    background: linear-gradient(135deg, #FCE9D7, #D6F1DC) !important;
    color: #2E2418 !important; border: 1px solid #E6DCCB !important;
    border-radius: 999px !important; box-shadow: none !important;
    font-weight: 800 !important; padding: 14px 20px !important;
}
[class*="st-key-drawer_recipe_"][class*="_enhance"] button:hover { filter: brightness(0.98); }

div[data-testid="stMetricValue"] {
    font-family: 'Heebo', sans-serif;
    font-size: 22px; font-weight: 700; color: #C5552D;
}
[data-testid="stMetric"] { direction: rtl !important; text-align: right !important; }
[data-testid="stSpinner"] { direction: rtl !important; text-align: right !important; }
[data-testid="stExpanderDetails"] { direction: rtl !important; text-align: right !important; }
[data-testid="stFileUploaderDropzone"] * { direction: rtl !important; text-align: right !important; }

.stButton > button[kind="primary"] {
    background: #C5552D !important;
    border: none !important; border-radius: 99px !important;
    color: white !important; font-family: 'Heebo', sans-serif !important;
    font-weight: 700 !important; padding: 10px 22px !important;
    direction: rtl !important;
}
.stButton > button[kind="primary"]:hover { background: #B14A26 !important; }
.stButton > button { direction: rtl !important; }

@media (max-width: 960px) {
    section[data-testid="stSidebar"]:has(.sc-recipe-drawer) {
        width: min(92vw, 620px) !important;
        min-width: min(92vw, 620px) !important;
    }
}
</style>
"""


def get_styles(active_page: str, active_cat_key: str) -> str:
    dynamic = f"""
<style>
[class*="st-key-nav_{active_page}"] button {{
    background: #C5552D !important; color: #FFFFFF !important;
    box-shadow: 0 2px 8px rgba(197, 85, 45, 0.3) !important;
}}
[class*="st-key-nav_{active_page}"] button:hover {{ background: #B14A26 !important; }}
[class*="st-key-cat_{active_cat_key}"] button {{
    background: #C5552D !important; color: #FFFFFF !important;
}}
[class*="st-key-cat_{active_cat_key}"] button:hover {{ background: #B14A26 !important; }}
</style>
"""
    return _BASE_CSS + dynamic
