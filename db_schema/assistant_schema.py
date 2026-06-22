from db import execute


def ensure_assistant_tables():
    """にゃんともアシスタント用ログテーブル。古いDBでもapp.pyだけで追加できるようにする。"""
    execute("""
        CREATE TABLE IF NOT EXISTS assistant_logs (
            assistant_log_id TEXT PRIMARY KEY,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            created_by TEXT,
            case_id TEXT REFERENCES cases(case_id) ON DELETE SET NULL,
            client_id TEXT REFERENCES clients(client_id) ON DELETE SET NULL,
            mode TEXT,
            user_question TEXT,
            source_text TEXT,
            answer_text TEXT,
            model TEXT,
            memo TEXT
        )
    """)
