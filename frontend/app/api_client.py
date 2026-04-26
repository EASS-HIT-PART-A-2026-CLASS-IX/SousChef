import requests
import streamlit as st

from app.config import API_BASE


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
        r = requests.delete(f"{API_BASE}{path}", timeout=8)
        return r.status_code == 204
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return False
