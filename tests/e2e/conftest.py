"""
Fixtures for the SousChef e2e suite.

Spins up three subprocesses per session (mock Ollama → backend → frontend),
waits for each to become healthy, and tears them all down at the end.
Selectable via env vars (see README.md):

    E2E_AI_MODE=mock|ollama       (default: mock)
    OLLAMA_BASE_URL / OLLAMA_MODEL (only when mode=ollama)
    E2E_HEADED=1                  (run Chromium headed)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import Page

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_FILE = REPO_ROOT / "frontend" / "main.py"
MOCK_OLLAMA_MODULE = "tests.e2e.mock_ollama"
ARTIFACT_DIR = REPO_ROOT / "tests" / "e2e" / "artifacts" / "latest"
SCREENSHOT_DIR = ARTIFACT_DIR / "screenshots"
REPORT_CASES: list[dict[str, Any]] = []
RUN_STARTED_AT = time.time()

E2E_AI_MODE = os.getenv("E2E_AI_MODE", "mock").lower()
HEADED = os.getenv("E2E_HEADED") == "1"
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _local_client() -> httpx.Client:
    """HTTP client that ignores system proxies (tests always hit localhost)."""
    return httpx.Client(trust_env=False, timeout=2.0)


def _slug(value: str, *, max_length: int = 80) -> str:
    cleaned = [
        ch.lower() if ch.isalnum() else "-"
        for ch in value
    ]
    slug = "".join(cleaned)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-") or "artifact"
    if len(slug) <= max_length:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{slug[: max_length - 11].rstrip('-')}-{digest}"


def _capture_page(page: Page, nodeid: str, label: str, screenshots: list[dict[str, str]]) -> dict[str, str]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    index = len(screenshots) + 1
    node_slug = _slug(nodeid, max_length=72)
    label_slug = _slug(label, max_length=28)
    file_path = SCREENSHOT_DIR / f"{node_slug}-{index:02d}-{label_slug}.png"
    page.screenshot(path=str(file_path), full_page=True, animations="disabled")
    shot = {"label": label, "path": file_path.relative_to(ARTIFACT_DIR).as_posix()}
    screenshots.append(shot)
    return shot


def _render_report_html(exitstatus: int) -> str:
    total = len(REPORT_CASES)
    passed = sum(1 for case in REPORT_CASES if case["status"] == "passed")
    failed = sum(1 for case in REPORT_CASES if case["status"] == "failed")
    skipped = sum(1 for case in REPORT_CASES if case["status"] == "skipped")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    case_cards = []
    for case in REPORT_CASES:
        badge_class = f"status-{case['status']}"
        screenshot_html = "".join(
            (
                f'<figure class="shot">'
                f'<a href="{escape(shot["path"])}" target="_blank">'
                f'<img src="{escape(shot["path"])}" alt="{escape(shot["label"])}"></a>'
                f'<figcaption>{escape(shot["label"])}</figcaption>'
                f"</figure>"
            )
            for shot in case["screenshots"]
        ) or '<div class="empty">No screenshots captured</div>'
        failure_html = ""
        if case.get("failure"):
            failure_html = (
                "<details><summary>Failure details</summary>"
                f"<pre>{escape(case['failure'])}</pre>"
                "</details>"
            )
        case_cards.append(
            f"""
            <section class="case">
                <div class="case-head">
                    <div>
                        <h2>{escape(case["name"])}</h2>
                        <div class="meta">{escape(case["nodeid"])} · {case["duration_s"]:.2f}s</div>
                    </div>
                    <span class="status {badge_class}">{escape(case["status"].upper())}</span>
                </div>
                <div class="shots">{screenshot_html}</div>
                {failure_html}
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SousChef E2E Report</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f7f2ea;
      color: #2d2419;
      margin: 0;
      padding: 32px;
    }}
    h1, h2 {{ margin: 0; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin: 24px 0 32px;
    }}
    .summary-card, .case {{
      background: white;
      border: 1px solid #e8dcc8;
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(62, 45, 27, 0.06);
    }}
    .summary-card {{
      padding: 18px 20px;
    }}
    .summary-card .label {{
      color: #8b7b66;
      font-size: 13px;
      margin-bottom: 10px;
    }}
    .summary-card .value {{
      font-size: 30px;
      font-weight: 800;
      color: #c5552d;
    }}
    .case {{
      padding: 22px;
      margin-bottom: 24px;
    }}
    .case-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 18px;
    }}
    .meta {{
      color: #8b7b66;
      font-size: 13px;
      margin-top: 6px;
      word-break: break-word;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 6px 14px;
      font-size: 12px;
      font-weight: 800;
    }}
    .status-passed {{ background: #dff3e3; color: #146c2e; }}
    .status-failed {{ background: #ffe0da; color: #9d2f1c; }}
    .status-skipped {{ background: #eee6da; color: #645949; }}
    .shots {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }}
    .shot {{
      margin: 0;
      border: 1px solid #ece3d2;
      border-radius: 14px;
      overflow: hidden;
      background: #fffdf9;
    }}
    .shot img {{
      width: 100%;
      display: block;
      background: #f3ede3;
    }}
    .shot figcaption {{
      padding: 10px 12px;
      font-size: 13px;
      color: #6f614d;
    }}
    details {{
      margin-top: 16px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #2b2118;
      color: #f7efe3;
      padding: 16px;
      border-radius: 14px;
      overflow-x: auto;
    }}
    .empty {{
      border: 1px dashed #d8ccb7;
      border-radius: 14px;
      padding: 24px;
      color: #8b7b66;
      text-align: center;
      background: #fffaf3;
    }}
  </style>
</head>
<body>
  <header>
    <h1>SousChef Playwright Validation Report</h1>
    <p>Generated at {escape(generated_at)} · AI mode: {escape(E2E_AI_MODE)} · Exit status: {exitstatus}</p>
  </header>
  <section class="summary">
    <div class="summary-card"><div class="label">Total</div><div class="value">{total}</div></div>
    <div class="summary-card"><div class="label">Passed</div><div class="value">{passed}</div></div>
    <div class="summary-card"><div class="label">Failed</div><div class="value">{failed}</div></div>
    <div class="summary-card"><div class="label">Skipped</div><div class="value">{skipped}</div></div>
  </section>
  {''.join(case_cards)}
</body>
</html>"""


def _wait_http(
    url: str,
    timeout: float = 60.0,
    expect_status: tuple[int, ...] = (200,),
    proc: subprocess.Popen | None = None,
    name: str = "service",
) -> None:
    """Poll *url* until it answers with one of *expect_status* or *timeout* elapses.

    If *proc* exits before the service is healthy, surface its captured output
    rather than waiting out the full timeout.
    """
    deadline = time.time() + timeout
    last_exc: Exception | None = None
    with _local_client() as client:
        while time.time() < deadline:
            if proc is not None and proc.poll() is not None:
                out = ""
                try:
                    out = proc.stdout.read() if proc.stdout else ""
                except Exception:
                    pass
                raise RuntimeError(
                    f"{name} exited early (code={proc.returncode}) before becoming "
                    f"healthy at {url}.\n---output---\n{out[:4000]}"
                )
            try:
                r = client.get(url)
                if r.status_code in expect_status:
                    return
            except Exception as e:  # noqa: BLE001
                last_exc = e
            time.sleep(0.4)
    out = ""
    if proc is not None and proc.stdout is not None:
        try:
            proc.terminate()
            out, _ = proc.communicate(timeout=3)
        except Exception:
            pass
    raise RuntimeError(
        f"Service at {url} did not become healthy within {timeout}s "
        f"(last error: {last_exc}).\n---output---\n{out[:4000]}"
    )


def _spawn(cmd: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        env={**os.environ, **env},
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _terminate(proc: subprocess.Popen | None, name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def pytest_sessionstart(session):  # noqa: ARG001
    global RUN_STARTED_AT
    RUN_STARTED_AT = time.time()
    REPORT_CASES.clear()
    if ARTIFACT_DIR.exists():
        shutil.rmtree(ARTIFACT_DIR)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "generated_at": datetime.now().isoformat(),
        "duration_s": round(time.time() - RUN_STARTED_AT, 3),
        "ai_mode": E2E_AI_MODE,
        "exitstatus": exitstatus,
        "cases": REPORT_CASES,
    }
    (ARTIFACT_DIR / "report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "index.html").write_text(
        _render_report_html(exitstatus),
        encoding="utf-8",
    )
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal:
        terminal.write_line(f"E2E report written to {ARTIFACT_DIR / 'index.html'}")


# ── Mock Ollama (only when E2E_AI_MODE=mock) ─────────────────────────────────

@pytest.fixture(scope="session")
def ollama_url() -> Iterator[str]:
    if E2E_AI_MODE != "mock":
        # Use whatever the user configured for a real Ollama
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            _wait_http(f"{url}/", timeout=5.0, expect_status=(200, 404))
        except Exception:
            pytest.skip(f"E2E_AI_MODE=ollama but no daemon reachable at {url}")
        yield url
        return

    port = _free_port()
    proc = _spawn(
        [sys.executable, "-m", MOCK_OLLAMA_MODULE, "--port", str(port)],
        env={"PYTHONPATH": str(REPO_ROOT)},
        cwd=REPO_ROOT,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/", timeout=15.0,
                   proc=proc, name="mock_ollama")
        yield f"http://127.0.0.1:{port}"
    finally:
        _terminate(proc, "mock_ollama")


# ── Backend ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def backend_url(ollama_url: str) -> Iterator[str]:
    port = _free_port()
    tmp_dir = Path(tempfile.mkdtemp(prefix="souschef-e2e-"))
    db_path = tmp_dir / "recipes.db"

    env = {
        "AI_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": ollama_url,
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "gemma4:26b"),
        "OLLAMA_TIMEOUT": "120",
        # Isolate the per-run sqlite file so we never collide with the dev DB
        # or a stale journal sitting next to backend/app.
        "DATABASE_URL": f"sqlite:///{db_path}",
        "LOG_LEVEL": "WARNING",
    }
    proc = _spawn(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        env=env,
        cwd=BACKEND_DIR,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/recipes", timeout=60.0,
                   proc=proc, name="backend")
        yield f"http://127.0.0.1:{port}"
    finally:
        _terminate(proc, "backend")
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Frontend (Streamlit) ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def frontend_url(backend_url: str) -> Iterator[str]:
    port = _free_port()
    env = {
        "API_BASE_URL": backend_url,
        "STREAMLIT_SERVER_HEADLESS": "true",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "STREAMLIT_SERVER_PORT": str(port),
        "STREAMLIT_SERVER_ADDRESS": "127.0.0.1",
        "STREAMLIT_GLOBAL_DEVELOPMENT_MODE": "false",
    }
    proc = _spawn(
        [
            sys.executable, "-m", "streamlit", "run", str(FRONTEND_FILE),
            "--server.port", str(port),
            "--server.address", "127.0.0.1",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        env=env,
        cwd=REPO_ROOT,
    )
    try:
        # Streamlit's /_stcore/health returns "ok" when ready.
        _wait_http(f"http://127.0.0.1:{port}/_stcore/health", timeout=60.0,
                   proc=proc, name="frontend")
        yield f"http://127.0.0.1:{port}"
    finally:
        _terminate(proc, "frontend")


# ── DB seeding helper ────────────────────────────────────────────────────────

def _seed_recipe(backend: str, **overrides) -> dict:
    body = {
        "name": "סלט ירקות לדוגמה",
        "description": "סלט ים-תיכוני קליל",
        "category": "ארוחת צהריים",
        "prep_time": 10,
        "cook_time": 0,
        "servings": 2,
        "ingredients": [
            {"name": "מלפפון", "amount": 2, "unit": "יח'"},
            {"name": "עגבנייה", "amount": 3, "unit": "יח'"},
        ],
        "steps": [{"order": 1, "instruction": "לחתוך הכל ולערבב"}],
    }
    body.update(overrides)
    with _local_client() as c:
        r = c.post(f"{backend}/recipes", json=body, timeout=10)
    r.raise_for_status()
    return r.json()


@pytest.fixture
def seed_recipes(backend_url: str):
    """Per-test fixture that wipes the DB and seeds three recipes."""
    # Wipe existing recipes
    with _local_client() as c:
        existing = c.get(f"{backend_url}/recipes").json()
        for rec in existing:
            c.delete(f"{backend_url}/recipes/{rec['id']}")

    a = _seed_recipe(backend_url, name="חביתה זריזה", category="ארוחת בוקר",
                     description="חביתה מהירה לבוקר", prep_time=2, cook_time=3, servings=1)
    b = _seed_recipe(backend_url, name="פסטה ברוטב עגבניות", category="ארוחת ערב",
                     description="פסטה איטלקית קלאסית", prep_time=10, cook_time=20, servings=4)
    c = _seed_recipe(backend_url, name="עוגת שוקולד", category="קינוח",
                     description="עוגת שוקולד עשירה", prep_time=20, cook_time=35, servings=8)
    return [a, b, c]


@pytest.fixture
def empty_db(backend_url: str):
    with _local_client() as c:
        existing = c.get(f"{backend_url}/recipes").json()
        for rec in existing:
            c.delete(f"{backend_url}/recipes/{rec['id']}")


# ── Playwright config overrides ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):  # noqa: PT004
    return {**browser_type_launch_args, "headless": not HEADED}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):  # noqa: PT004
    # Streamlit's UI is wide; give the viewport room.
    return {**browser_context_args, "viewport": {"width": 1400, "height": 1000},
            "locale": "he-IL"}


class _RecipeSourceHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args):  # noqa: A003
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        host = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        if parsed.path == "/recipe":
            payload = {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "פסטה ביתית",
                "recipeIngredient": ["פסטה", "עגבניות", "שמן זית"],
                "recipeInstructions": ["לבשל", "לערבב", "להגיש"],
            }
            html_doc = f"""<!doctype html>
<html lang="he">
  <head>
    <meta charset="utf-8">
    <title>מתכון לדוגמה</title>
    <meta property="og:image" content="{host}/og-image.png">
    <script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>
  </head>
  <body>
    <article>
      <h1>פסטה ביתית</h1>
      <p>פסטה עם עגבניות, שמן זית ועשבי תיבול.</p>
    </article>
  </body>
</html>"""
            body = html_doc.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/og-image.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_TINY_PNG)))
            self.end_headers()
            self.wfile.write(_TINY_PNG)
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="session")
def recipe_source_url() -> Iterator[str]:
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _RecipeSourceHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def sample_upload_image(tmp_path: Path) -> Path:
    image_path = tmp_path / "sample-upload.png"
    image_path.write_bytes(_TINY_PNG)
    return image_path


@pytest.fixture
def capture_step(request, page: Page):
    screenshots = getattr(request.node, "_e2e_screenshots", None)
    if screenshots is None:
        screenshots = []
        request.node._e2e_screenshots = screenshots

    def _capture(label: str) -> str:
        shot = _capture_page(page, request.node.nodeid, label, screenshots)
        return shot["path"]

    return _capture


@pytest.fixture(autouse=True)
def _capture_test_artifacts(request, page: Page):
    screenshots: list[dict[str, str]] = []
    request.node._e2e_screenshots = screenshots
    yield
    try:
        if not page.is_closed():
            _capture_page(page, request.node.nodeid, "final", screenshots)
    except Exception:
        pass

    rep_call = getattr(request.node, "rep_call", None)
    rep_setup = getattr(request.node, "rep_setup", None)
    if rep_call is not None:
        status = "passed" if rep_call.passed else "failed" if rep_call.failed else "skipped"
        duration = rep_call.duration
        failure = getattr(rep_call, "longreprtext", None) if rep_call.failed else None
    elif rep_setup is not None:
        status = "failed" if rep_setup.failed else "skipped"
        duration = rep_setup.duration
        failure = getattr(rep_setup, "longreprtext", None) if rep_setup.failed else None
    else:
        status = "unknown"
        duration = 0.0
        failure = None

    REPORT_CASES.append(
        {
            "nodeid": request.node.nodeid,
            "name": request.node.name,
            "status": status,
            "duration_s": round(duration, 3),
            "screenshots": screenshots,
            "failure": failure,
        }
    )
