import json
import os
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from config import APP_TITLE, TABLES
from db import execute, fetch_df, fetch_one
from core.audit import log_action
from core.utils import make_id, now_jst, now_text


BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)
DEFAULT_AUTO_BACKUP_HOURS = 24
DEFAULT_BACKUP_KEEP = 14
DEFAULT_AUTO_BACKUP_CHECK_MINUTES = 60


def get_secret_value(key, default=""):
    """st.secrets と環境変数の両方から設定値を取得する。"""
    try:
        if key in st.secrets:
            return st.secrets.get(key, default)
    except Exception:
        pass
    return os.environ.get(key, default)


def get_backup_tables():
    """config.TABLESに存在する主要テーブルをバックアップ対象にする。"""
    seen = set()
    tables = []
    for table, label in TABLES:
        if table not in seen:
            tables.append((table, label))
            seen.add(table)
    for table, label in [("nyantomo_backup_logs", "自動バックアップログ"), ("consultation_cards", "相談カード整理"), ("pending_items", "保留事項"), ("policy_candidates", "制度候補整理"), ("guardian_wards", "後見_被後見人"), ("guardian_cards", "後見_カード"), ("guardian_interview_logs", "後見_面談記録"), ("guardian_resource_map", "後見_リソース地図"), ("guardian_ai_support", "後見_AI支援")]:
        if table not in seen:
            tables.append((table, label))
    return tables


def build_csv_zip_bytes():
    """全テーブルをCSV ZIP化してbytesで返す。"""
    data = {}
    for table, label in get_backup_tables():
        try:
            data[label] = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
        except Exception as e:
            data[label] = pd.DataFrame([{"error": str(e)}])

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "app": APP_TITLE,
            "created_at": now_text(),
            "backup_type": "csv_zip",
            "tables": [label for _, label in get_backup_tables()],
        }
        zf.writestr("backup_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        for label, df in data.items():
            safe_name = str(label).replace("/", "_").replace("\\", "_")
            zf.writestr(f"{safe_name}.csv", df.to_csv(index=False).encode("utf-8-sig"))
    buffer.seek(0)
    return buffer.getvalue(), len(data)


def save_backup_file(backup_type="manual", note=""):
    """CSV ZIPバックアップをbackupsフォルダへ保存し、ログを残す。"""
    zip_bytes, table_count = build_csv_zip_bytes()
    stamp = now_jst().strftime("%Y%m%d_%H%M%S")
    file_name = f"nyantomo_backup_{backup_type}_{stamp}.zip"
    path = BACKUP_DIR / file_name
    path.write_bytes(zip_bytes)
    backup_id = make_id("backup")
    execute("""
        INSERT INTO nyantomo_backup_logs
        (backup_id, created_at, created_by, backup_type, file_name, table_count, note)
        VALUES (%(backup_id)s, %(created_at)s, %(created_by)s, %(backup_type)s, %(file_name)s, %(table_count)s, %(note)s)
    """, {
        "backup_id": backup_id,
        "created_at": now_text(),
        "created_by": st.session_state.get("login_id", "system"),
        "backup_type": backup_type,
        "file_name": file_name,
        "table_count": table_count,
        "note": note,
    })
    log_action("backup", "nyantomo_backup_logs", backup_id, f"{backup_type}: {file_name}")
    return path


def cleanup_old_backups(keep=None):
    """古いバックアップファイルを指定件数だけ残して削除する。"""
    try:
        keep = int(keep or get_secret_value("AUTO_BACKUP_KEEP", DEFAULT_BACKUP_KEEP))
    except Exception:
        keep = DEFAULT_BACKUP_KEEP
    files = sorted(BACKUP_DIR.glob("nyantomo_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in files[keep:]:
        try:
            p.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def maybe_run_auto_backup():
    """最終自動バックアップから指定時間以上経っていれば自動作成する。

    軽量化：
    画面操作のたびにDBへ確認しないよう、セッション内では
    AUTO_BACKUP_CHECK_MINUTES ごとにだけ確認します。
    """
    try:
        check_minutes = int(get_secret_value("AUTO_BACKUP_CHECK_MINUTES", DEFAULT_AUTO_BACKUP_CHECK_MINUTES))
    except Exception:
        check_minutes = DEFAULT_AUTO_BACKUP_CHECK_MINUTES
    if check_minutes > 0:
        last_check = st.session_state.get("_last_auto_backup_check")
        now_dt = now_jst().replace(tzinfo=None)
        if last_check:
            try:
                elapsed_minutes = (now_dt - last_check).total_seconds() / 60
                if elapsed_minutes < check_minutes:
                    return None
            except Exception:
                pass
        st.session_state["_last_auto_backup_check"] = now_dt

    try:
        hours = int(get_secret_value("AUTO_BACKUP_HOURS", DEFAULT_AUTO_BACKUP_HOURS))
    except Exception:
        hours = DEFAULT_AUTO_BACKUP_HOURS
    if hours <= 0:
        return None

    row = fetch_one("""
        SELECT created_at
        FROM nyantomo_backup_logs
        WHERE backup_type = 'auto'
        ORDER BY created_at DESC
        LIMIT 1
    """)
    should_run = False
    if not row or not row.get("created_at"):
        should_run = True
    else:
        try:
            last = pd.to_datetime(row["created_at"]).to_pydatetime()
            elapsed_hours = (now_jst().replace(tzinfo=None) - last).total_seconds() / 3600
            should_run = elapsed_hours >= hours
        except Exception:
            should_run = True

    if should_run:
        path = save_backup_file("auto", f"AUTO_BACKUP_HOURS={hours}")
        cleanup_old_backups()
        return path
    return None
