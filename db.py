# ============================================================
# にゃんとも相談管理システム Ver3.2.0 安定稼働版
# db.py：PostgreSQL接続・SQL実行・初期化
# ============================================================

import os
import uuid
import hashlib
import hmac
from datetime import datetime, date

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st


def get_database_url() -> str:
    try:
        if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
            return st.secrets["postgres"]["url"]
    except Exception:
        pass

    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass

    return os.environ.get("DATABASE_URL", "")


def has_database_url() -> bool:
    return bool(get_database_url())


def get_conn():
    url = get_database_url()
    if not url:
        raise RuntimeError("PostgreSQL接続URLが設定されていません。")
    return psycopg2.connect(url)


def execute(sql: str, params=None) -> None:
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql, params or {})
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def fetch_df(sql: str, params=None) -> pd.DataFrame:
    conn = None
    try:
        conn = get_conn()
        return pd.read_sql_query(sql, conn, params=params or {})
    finally:
        if conn:
            conn.close()


def fetch_one(sql: str, params=None):
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or {})
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return date.today().strftime("%Y-%m-%d")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), str(hashed))


def log_action(action: str, table_name: str = "", record_id: str = "", memo: str = "") -> None:
    try:
        execute(
            """
            INSERT INTO audit_logs
            (audit_id, created_at, login_id, role, action, table_name, record_id, memo)
            VALUES (%(audit_id)s, %(created_at)s, %(login_id)s, %(role)s, %(action)s, %(table_name)s, %(record_id)s, %(memo)s)
            """,
            {
                "audit_id": make_id("audit"),
                "created_at": now_text(),
                "login_id": st.session_state.get("login_id", ""),
                "role": st.session_state.get("role", ""),
                "action": action,
                "table_name": table_name,
                "record_id": record_id,
                "memo": memo,
            },
        )
    except Exception:
        pass


def init_db() -> None:
    """初回起動用の CREATE TABLE / CREATE INDEX のみ。ALTER TABLE は実行しない。"""
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                name TEXT NOT NULL,
                age_group TEXT,
                area TEXT,
                contact_method TEXT,
                position TEXT,
                note TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                consult_date DATE,
                case_title TEXT,
                case_type TEXT,
                status TEXT,
                current_state TEXT,
                house_state TEXT,
                cat_relation TEXT,
                family_gap TEXT,
                pressure TEXT,
                worries TEXT,
                not_decide TEXT,
                first_check TEXT,
                free_memo TEXT,
                internal_memo TEXT,
                next_check TEXT,
                next_hearing_items TEXT,
                hearing_missing TEXT,
                do_not_do_now TEXT,
                next_check_date DATE,
                closed_date DATE,
                close_reason TEXT,
                final_memo TEXT,
                reopen_possibility TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS history (
                history_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                record_date DATE,
                record_type TEXT,
                before_status TEXT,
                after_status TEXT,
                record TEXT,
                next_action TEXT,
                internal_memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                property_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                property_name TEXT,
                address TEXT,
                property_status TEXT,
                vacant_status TEXT,
                key_hold TEXT,
                neighborhood TEXT,
                visit_frequency TEXT,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cats (
                cat_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                cat_name TEXT,
                age TEXT,
                sex TEXT,
                health_memo TEXT,
                life_status TEXT,
                future_plan TEXT,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS family (
                family_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                name TEXT,
                relation TEXT,
                contact_ok TEXT,
                temperature TEXT,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_summaries (
                summary_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                summary_type TEXT,
                source_text TEXT,
                summary_text TEXT,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS line_messages (
                message_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE SET NULL,
                client_id TEXT REFERENCES clients(client_id) ON DELETE SET NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                created_by TEXT,
                to_target TEXT,
                message_text TEXT,
                send_status TEXT,
                response_memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS line_templates (
                template_id TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                template_name TEXT,
                category TEXT,
                template_text TEXT,
                active INTEGER DEFAULT 1,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                attachment_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE SET NULL,
                client_id TEXT REFERENCES clients(client_id) ON DELETE SET NULL,
                created_at TIMESTAMP,
                file_name TEXT,
                mime_type TEXT,
                file_size INTEGER,
                file_data BYTEA,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                user_id TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                login_id TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                display_name TEXT,
                active INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                login_id TEXT,
                role TEXT,
                action TEXT,
                table_name TEXT,
                record_id TEXT,
                memo TEXT
            )
        """)

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)",
            "CREATE INDEX IF NOT EXISTS idx_clients_area ON clients(area)",
            "CREATE INDEX IF NOT EXISTS idx_cases_client_id ON cases(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)",
            "CREATE INDEX IF NOT EXISTS idx_cases_case_type ON cases(case_type)",
            "CREATE INDEX IF NOT EXISTS idx_cases_next_check_date ON cases(next_check_date)",
            "CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON cases(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_history_case_id ON history(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_history_record_date ON history(record_date)",
            "CREATE INDEX IF NOT EXISTS idx_properties_case_id ON properties(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_cats_case_id ON cats(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_family_case_id ON family(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_summaries_case_id ON ai_summaries(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_line_messages_case_id ON line_messages(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_line_templates_category ON line_templates(category)",
            "CREATE INDEX IF NOT EXISTS idx_attachments_case_id ON attachments(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at)",
        ]
        for sql in indexes:
            cur.execute(sql)

        cur.execute("SELECT COUNT(*) FROM app_users")
        count = cur.fetchone()[0]
        if count == 0:
            for login_id, password, role, display_name in [
                ("admin", "admin123", "管理者", "管理者"),
                ("staff", "staff123", "職員", "職員"),
                ("viewer", "viewer123", "閲覧者", "閲覧者"),
            ]:
                cur.execute(
                    """
                    INSERT INTO app_users
                    (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (make_id("user"), now_text(), now_text(), login_id, hash_password(password), role, display_name),
                )

        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
