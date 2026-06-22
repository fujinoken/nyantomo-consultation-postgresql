import streamlit as st

from db import execute
from core.utils import make_id, now_text


def log_action(action, table_name="", record_id="", memo=""):
    try:
        execute("""
            INSERT INTO audit_logs
            (audit_id, created_at, login_id, action, table_name, record_id, memo)
            VALUES (%(audit_id)s, %(created_at)s, %(login_id)s, %(action)s, %(table_name)s, %(record_id)s, %(memo)s)
        """, {
            "audit_id": make_id("audit"),
            "created_at": now_text(),
            "login_id": st.session_state.get("login_id", ""),
            "action": action,
            "table_name": table_name,
            "record_id": record_id,
            "memo": memo,
        })
    except Exception:
        pass
