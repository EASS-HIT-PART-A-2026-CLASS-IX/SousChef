import requests
import streamlit as st

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, API_BASE

# Cached admin JWT for protected backend routes. Obtained on demand and
# refreshed if the backend rejects it (expired/invalid).
_token_cache: dict = {"token": None}


def _get_admin_token(force_refresh: bool = False):
    if _token_cache["token"] and not force_refresh:
        return _token_cache["token"]
    if not ADMIN_PASSWORD:
        return None
    try:
        r = requests.post(
            f"{API_BASE}/token",
            data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            timeout=8,
        )
        if r.ok:
            _token_cache["token"] = r.json().get("access_token")
            return _token_cache["token"]
    except Exception:
        return None
    return None


def _auth_headers(force_refresh: bool = False) -> dict:
    token = _get_admin_token(force_refresh=force_refresh)
    return {"Authorization": f"Bearer {token}"} if token else {}


def _detail_message(detail) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def _extract_error_detail(r: requests.Response):
    try:
        return r.json().get("detail", r.text)
    except Exception:
        return r.text


def _show_error(r: requests.Response) -> None:
    detail = _extract_error_detail(r)
    st.error(f"שגיאה {r.status_code}: {_detail_message(detail)}")


def api_get_result(path: str, params: dict = None, timeout: int = 8, *, show_error: bool = True):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        if not r.ok:
            if show_error:
                _show_error(r)
            return None, _extract_error_detail(r), r.status_code
        return r.json(), None, r.status_code
    except requests.exceptions.ConnectionError:
        message = "❌ לא ניתן להתחבר ל-API. ודא שהשרת רץ על http://localhost:8000"
        if show_error:
            st.error(message)
        return None, message, None
    except Exception as e:
        if show_error:
            st.error(f"שגיאה: {e}")
        return None, str(e), None


def api_get(path: str, params: dict = None, timeout: int = 8):
    result, _detail, _status_code = api_get_result(path, params=params, timeout=timeout)
    return result


def api_post(path: str, json_data: dict = None, data: dict = None, files=None, timeout: int = 30):
    try:
        if data is not None or files:
            r = requests.post(f"{API_BASE}{path}", data=data, files=files or {}, timeout=timeout)
        else:
            r = requests.post(f"{API_BASE}{path}", json=json_data, timeout=timeout)
        if not r.ok:
            _show_error(r)
            return None
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ לא ניתן להתחבר ל-API.")
        return None
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return None


def api_post_result(path: str, json_data: dict = None, timeout: int = 30):
    try:
        r = requests.post(f"{API_BASE}{path}", json=json_data, timeout=timeout)
        if not r.ok:
            return None, _extract_error_detail(r), r.status_code
        return r.json(), None, r.status_code
    except requests.exceptions.ConnectionError:
        return None, "❌ לא ניתן להתחבר ל-API.", None
    except Exception as e:
        return None, str(e), None


def api_put(path: str, json_data: dict):
    try:
        r = requests.put(f"{API_BASE}{path}", json=json_data, timeout=8)
        if not r.ok:
            _show_error(r)
            return None
        return r.json()
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return None


def api_delete(path: str):
    try:
        r = requests.delete(f"{API_BASE}{path}", headers=_auth_headers(), timeout=8)
        if r.status_code == 401:
            # Token missing/expired — refresh once and retry before giving up.
            r = requests.delete(
                f"{API_BASE}{path}", headers=_auth_headers(force_refresh=True), timeout=8
            )
        if r.status_code == 204:
            return True
        _show_error(r)
        return False
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return False
