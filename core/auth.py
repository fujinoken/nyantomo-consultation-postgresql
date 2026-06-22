import hashlib
import hmac

import streamlit as st

from config import APP_TITLE, APP_CAPTION, ADMIN_ROLE, STAFF_ROLE
from db import fetch_one
from core.audit import log_action


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password, hashed):
    return hmac.compare_digest(hash_password(password), str(hashed))


def clear_app_cache():
    """
    登録・更新・削除後に一覧やダッシュボードのキャッシュをクリアします。
    30秒キャッシュで画面切替を軽くしつつ、更新直後は最新表示に戻します。
    """
    try:
        st.cache_data.clear()
    except Exception:
        pass


def can_write():
    return st.session_state.get("role") in [ADMIN_ROLE, STAFF_ROLE]


def can_admin():
    return st.session_state.get("role") == ADMIN_ROLE


def show_db_setup_screen():
    st.title(APP_TITLE)
    st.error("PostgreSQL接続URLがまだ設定されていません。")
    st.markdown("""
### Streamlit Cloud の Secrets 設定例

```toml
[postgres]
url = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```

または

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```
""")
    st.stop()


def login_screen():
    st.title(APP_TITLE)
    st.caption(APP_CAPTION)
    st.subheader("ログイン")
    with st.form("login_form"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")
    if ok:
        user = fetch_one("""
            SELECT user_id, login_id, password_hash, role, display_name, active
            FROM app_users WHERE login_id = %(login_id)s
        """, {"login_id": login_id})
        if user and int(user.get("active", 0)) == 1 and verify_password(password, user["password_hash"]):
            st.session_state["logged_in"] = True
            st.session_state["user_id"] = user["user_id"]
            st.session_state["login_id"] = user["login_id"]
            st.session_state["role"] = user["role"]
            st.session_state["display_name"] = user["display_name"]
            log_action("login", "app_users", user["user_id"], "ログイン")
            st.success("ログインしました。")
            clear_app_cache()
            st.rerun()
        else:
            st.error("ログインIDまたはパスワードが違います。")
    st.info("初期設定：管理者 admin / admin123　職員 staff / staff123")


def require_login():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
    if not st.session_state["logged_in"]:
        login_screen()
        st.stop()


def logout_button():
    with st.sidebar:
        st.markdown("---")
        st.write(f"ログイン：{st.session_state.get('display_name', '')}")
        st.write(f"権限：{st.session_state.get('role', '')}")
        if st.button("ログアウト"):
            log_action("logout", "app_users", st.session_state.get("user_id", ""), "ログアウト")
            st.session_state.clear()
            clear_app_cache()
            st.rerun()
