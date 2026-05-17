# db.py
import os
import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

def get_database_url():
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

def has_database_url():
    return bool(get_database_url())

def get_conn():
    url = get_database_url()
    if not url:
        raise RuntimeError("PostgreSQL接続URLが設定されていません。")
    return psycopg2.connect(url)

def execute(sql, params=None):
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

def fetch_df(sql, params=None):
    conn = None
    try:
        conn = get_conn()
        return pd.read_sql_query(sql, conn, params=params or {})
    finally:
        if conn:
            conn.close()

def fetch_one(sql, params=None):
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

def init_db(hash_password_func, make_id_func, now_text_func):
    # 起動時はCREATE TABLE / CREATE INDEX IF NOT EXISTSのみ。ALTER TABLEは実行しない。
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
            CREATE TABLE IF NOT EXISTS photos (
                photo_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
                client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
                created_at TIMESTAMP,
                photo_type TEXT,
                file_name TEXT,
                storage_note TEXT,
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
                template_type TEXT,
                template_text TEXT,
                active INTEGER DEFAULT 1,
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
                action TEXT,
                table_name TEXT,
                record_id TEXT,
                memo TEXT
            )
        """)

        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)",
            "CREATE INDEX IF NOT EXISTS idx_cases_client_id ON cases(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)",
            "CREATE INDEX IF NOT EXISTS idx_cases_next_check_date ON cases(next_check_date)",
            "CREATE INDEX IF NOT EXISTS idx_cases_case_title ON cases(case_title)",
            "CREATE INDEX IF NOT EXISTS idx_history_case_id ON history(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_history_record_date ON history(record_date)",
            "CREATE INDEX IF NOT EXISTS idx_properties_case_id ON properties(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_cats_case_id ON cats(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_family_case_id ON family(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_photos_case_id ON photos(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_summaries_case_id ON ai_summaries(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_line_messages_case_id ON line_messages(case_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at)",
        ]:
            cur.execute(sql)

        cur.execute("SELECT COUNT(*) FROM app_users")
        count = cur.fetchone()[0]
        if count == 0:
            cur.execute("""
                INSERT INTO app_users
                (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """, (make_id_func("user"), now_text_func(), now_text_func(), "admin", hash_password_func("admin123"), "管理者", "管理者"))

            cur.execute("""
                INSERT INTO app_users
                (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """, (make_id_func("user"), now_text_func(), now_text_func(), "staff", hash_password_func("staff123"), "職員", "職員"))

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
