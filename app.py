# app.py
import uuid
import hashlib
import hmac
import os
import json
import html
from datetime import date, datetime
from io import BytesIO
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    APP_TITLE, APP_CAPTION, ADMIN_ROLE, STAFF_ROLE, VIEWER_ROLE,
    ADMIN_MENUS, STAFF_MENUS, VIEWER_MENUS,
    STATUS_OPTIONS, CASE_TYPE_OPTIONS, AGE_OPTIONS, CONTACT_OPTIONS, POSITION_OPTIONS, TABLES
)
from db import has_database_url, init_db, execute, fetch_df, fetch_one

st.set_page_config(page_title=APP_TITLE, page_icon="🐾", layout="wide")


# ============================================================
# 追加機能：自動バックアップ / AI要約連携
# ------------------------------------------------------------
# ・自動バックアップは「アプリ起動・画面操作時」に最終実行時刻を確認し、
#   指定時間を超えていればCSV ZIPを自動生成して backups/ に保存します。
#   Streamlit Cloudは常時バックグラウンド実行ではないため、
#   完全な時刻指定ジョブではなく「アクセス時自動実行」です。
# ・AI要約は OpenAI APIキーがある場合のみ実行します。
#   st.secrets または環境変数に OPENAI_API_KEY を設定してください。
#
# Secrets例：
# OPENAI_API_KEY = "sk-..."
# OPENAI_MODEL = "gpt-4o-mini"
# AUTO_BACKUP_HOURS = "24"
# AUTO_BACKUP_KEEP = "14"
# ============================================================

BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)
DEFAULT_AUTO_BACKUP_HOURS = 24
DEFAULT_BACKUP_KEEP = 14
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


# ============================================================
# にゃんとも相談管理 Ver2.0：カード整理OS 設定
# ============================================================

NYANTOMO_CARD_TYPES = [
    "猫カード",
    "住まいカード",
    "家族カード",
    "健康カード",
    "お金カード",
    "制度カード",
    "支援者カード",
    "その他カード",
]

NYANTOMO_CARD_STATUS_OPTIONS = ["気になる", "検討中", "保留", "整理済"]

PENDING_STATUS_OPTIONS = [
    "保留中",
    "次回確認",
    "家族確認待ち",
    "専門家確認待ち",
    "整理済",
    "終了",
]

PENDING_DEADLINE_OPTIONS = ["期限なし", "目安あり", "期限あり", "要確認"]

SUPPORT_CATEGORY_OPTIONS = [
    "包括",
    "ケアマネ",
    "主治医",
    "宅建士",
    "司法書士",
    "弁護士",
    "税理士",
    "動物病院",
    "行政",
    "親族",
    "近隣",
    "その他",
]

# Ver2.1：判断カードと基本情報カードの紐付け
# 猫情報カード・空き家カード・家族関係メモは「基本情報」、
# Ver2.xカードは「悩み・判断・保留」を整理する上位カードとして扱います。
RELATED_BASE_CARD_MAP = {
    "猫カード": {
        "table": "cats",
        "id_col": "cat_id",
        "label_sql": "COALESCE(NULLIF(cat_name,''), '猫情報') || COALESCE('｜' || NULLIF(age,''), '') || COALESCE('｜' || NULLIF(sex,''), '')",
        "label": "猫情報カード",
    },
    "住まいカード": {
        "table": "properties",
        "id_col": "property_id",
        "label_sql": "COALESCE(NULLIF(property_name,''), '物件') || COALESCE('｜' || NULLIF(address,''), '')",
        "label": "空き家カード",
    },
    "家族カード": {
        "table": "family",
        "id_col": "family_id",
        "label_sql": "COALESCE(NULLIF(name,''), '家族') || COALESCE('｜' || NULLIF(relation,''), '') || COALESCE('｜' || NULLIF(temperature,''), '')",
        "label": "家族関係メモ",
    },
}




def apply_dashboard_css():
    st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1280px;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e9edf5;
        padding: 18px 18px;
        border-radius: 18px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.06);
    }
    div[data-testid="stMetric"] label {
        color: #475569 !important;
        font-weight: 700;
    }
    div[data-testid="stMetricValue"] {
        color: #172033;
        font-weight: 800;
    }
    .ny-card-soft {
        background: linear-gradient(135deg, #fffaf0 0%, #ffffff 72%);
        border: 1px solid #f4ddb3;
        border-radius: 20px;
        padding: 22px;
        min-height: 130px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.045);
    }
    .ny-card-blue {
        background: linear-gradient(135deg, #f3f9ff 0%, #ffffff 75%);
        border: 1px solid #cfe1f7;
        border-radius: 20px;
        padding: 22px;
        min-height: 130px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.045);
    }
    .ny-hero {
        background: #ffffff;
        border: 1px solid #edf0f7;
        border-radius: 22px;
        overflow: hidden;
        box-shadow: 0 10px 26px rgba(30, 41, 59, 0.06);
        margin-bottom: 18px;
    }
    .ny-hero-caption {
        background: #fff1f1;
        padding: 14px 18px;
        font-weight: 700;
        color: #3f3f46;
        border-top: 1px solid #f5d6d6;
    }
    .ny-section-title {
        font-size: 1.18rem;
        font-weight: 800;
        color: #172033;
        margin-bottom: 0.35rem;
    }
    .ny-muted {
        color: #64748b;
        font-size: 0.92rem;
    }
    .ny-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #eef6ff;
        color: #2563eb;
        font-weight: 700;
        font-size: 0.85rem;
        margin-left: 8px;
    }
    .ny-footer {
        text-align: center;
        color: #64748b;
        font-size: 0.88rem;
        padding: 18px 0 4px;
    }
    </style>
    """, unsafe_allow_html=True)


def safe_df_display(df, message, columns=None, height=None):
    if df is None or df.empty:
        st.info(message)
    else:
        show_df = df[columns] if columns else df
        st.dataframe(show_df, use_container_width=True, hide_index=True, height=height)



def make_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    return date.today().strftime("%Y-%m-%d")


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password, hashed):
    return hmac.compare_digest(hash_password(password), str(hashed))


def normalize_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def date_or_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


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


def get_clients():
    return fetch_df("""
        SELECT client_id, created_at, updated_at, name, age_group, area, contact_method, position, note
        FROM clients
        ORDER BY created_at DESC NULLS LAST
    """)


def get_cases():
    return fetch_df("""
        SELECT c.case_id, c.client_id, cl.name AS client_name, c.created_at, c.updated_at,
               c.consult_date, c.case_title, c.case_type, c.status, c.current_state,
               c.house_state, c.cat_relation, c.family_gap, c.pressure, c.worries,
               c.not_decide, c.first_check, c.free_memo, c.internal_memo, c.next_check,
               c.next_hearing_items, c.hearing_missing, c.do_not_do_now, c.next_check_date,
               c.closed_date, c.close_reason, c.final_memo, c.reopen_possibility
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
    """)


def get_case_options():
    df = get_cases()
    if df.empty:
        return {}, []
    labels = []
    mapping = {}
    for _, r in df.iterrows():
        label = f"{r['client_name']}｜{r['case_title']}｜{r['status']}｜{r['case_id']}"
        labels.append(label)
        mapping[label] = r["case_id"]
    return mapping, labels


def get_client_options():
    df = get_clients()
    if df.empty:
        return {}, []
    labels = []
    mapping = {}
    for _, r in df.iterrows():
        label = f"{r['name']}｜{r['area']}｜{r['client_id']}"
        labels.append(label)
        mapping[label] = r["client_id"]
    return mapping, labels


def case_to_client(case_id):
    row = fetch_one("SELECT client_id FROM cases WHERE case_id = %(case_id)s", {"case_id": case_id})
    return row["client_id"] if row else ""


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
            st.rerun()


def render_dashboard():
    apply_dashboard_css()

    st.subheader("ダッシュボード")

    counts = fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM clients) AS clients_count,
            (SELECT COUNT(*) FROM cases) AS cases_count,
            (SELECT COUNT(*) FROM cases WHERE COALESCE(status,'') <> '終了') AS open_cases_count,
            (SELECT COUNT(*) FROM cases
                WHERE COALESCE(status,'') <> '終了'
                AND next_check_date IS NOT NULL
                AND next_check_date <= CURRENT_DATE + INTERVAL '7 days') AS need_check_count
    """)

    clients_count = int(counts.get("clients_count", 0))
    cases_count = int(counts.get("cases_count", 0))
    open_cases_count = int(counts.get("open_cases_count", 0))
    need_check_count = int(counts.get("need_check_count", 0))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("相談者数", clients_count, help="登録済み相談者の総数")
    k2.metric("案件数", cases_count, help="登録済み案件の総数")
    k3.metric("進行中案件", open_cases_count, help="終了以外の案件数")
    k4.metric("要確認案件", need_check_count, help="次回確認日が7日以内または期限超過の案件数")

    st.markdown("---")

    notice_col, task_col, image_col = st.columns([1.05, 1.05, 1.45])

    with notice_col:
        st.markdown("""
        <div class="ny-card-soft">
            <div class="ny-section-title">🔔 お知らせ</div>
            <div class="ny-muted">現在、重要なお知らせはありません。</div>
        </div>
        """, unsafe_allow_html=True)

    with task_col:
        st.markdown("""
        <div class="ny-card-blue">
            <div class="ny-section-title">📋 やることリスト</div>
            <div class="ny-muted">要確認案件・ヒアリング漏れ・LINE返信などをここで確認します。</div>
        </div>
        """, unsafe_allow_html=True)

    with image_col:
        st.markdown('<div class="ny-hero">', unsafe_allow_html=True)
        image_path = Path(__file__).parent / "assets" / "dashboard_cat.png"
        if image_path.exists():
            # イラストを大きく出しすぎないため、固定幅で中央表示します。
            # サイズを変えたい場合は width=300〜420 の範囲で調整してください。
            img_left, img_center, img_right = st.columns([1, 1.15, 1])
            with img_center:
                st.image(str(image_path), width=340)
        else:
            st.info("ダッシュボード画像が見つかりません。assets/dashboard_cat.png を配置してください。")
        st.markdown(
            '<div class="ny-hero-caption">♡「急がせない判断を支える」ために、情報を安心して蓄積・整理できる仕組みです。 🐾</div></div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    need_check = fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.next_check_date, c.next_check
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND c.next_check_date IS NOT NULL
          AND c.next_check_date <= CURRENT_DATE + INTERVAL '7 days'
        ORDER BY c.next_check_date ASC, c.updated_at DESC
    """)

    hearing = fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.hearing_missing, c.next_hearing_items
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND NULLIF(TRIM(COALESCE(c.hearing_missing,'')), '') IS NOT NULL
        ORDER BY c.updated_at DESC
    """)

    do_not = fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.do_not_do_now, c.not_decide
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND NULLIF(TRIM(COALESCE(c.do_not_do_now,'')), '') IS NOT NULL
        ORDER BY c.updated_at DESC
    """)

    left_mid, right_mid = st.columns(2)

    with left_mid:
        st.markdown(f'<div class="ny-section-title">ヒアリング漏れがある案件 <span class="ny-pill">{len(hearing)}件</span></div>', unsafe_allow_html=True)
        safe_df_display(
            hearing,
            "ヒアリング漏れが登録されている案件はありません。",
            ["client_name", "case_title", "status", "hearing_missing", "next_hearing_items"],
            height=210
        )

    with right_mid:
        st.markdown(f'<div class="ny-section-title">今やらない方がいいこと <span class="ny-pill">{len(do_not)}件</span></div>', unsafe_allow_html=True)
        safe_df_display(
            do_not,
            "今やらない方がいいことが登録されている案件はありません。",
            ["client_name", "case_title", "status", "do_not_do_now", "not_decide"],
            height=210
        )

    st.markdown("---")

    bottom_left, bottom_right = st.columns([1.25, 1])

    with bottom_left:
        st.markdown('<div class="ny-section-title">最近の案件</div>', unsafe_allow_html=True)
        recent = fetch_df("""
            SELECT cl.name AS client_name, c.case_title, c.case_type, c.status, c.consult_date, c.updated_at
            FROM cases c JOIN clients cl ON c.client_id = cl.client_id
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC LIMIT 20
        """)
        safe_df_display(
            recent,
            "案件がありません。",
            ["client_name", "case_title", "case_type", "status", "consult_date", "updated_at"],
            height=260
        )

    with bottom_right:
        st.markdown('<div class="ny-section-title">状態別件数</div>', unsafe_allow_html=True)
        status_df = fetch_df("""
            SELECT COALESCE(status, '未設定') AS status, COUNT(*) AS 件数
            FROM cases GROUP BY COALESCE(status, '未設定') ORDER BY 件数 DESC
        """)
        safe_df_display(status_df, "案件がありません。", ["status", "件数"], height=210)

        st.markdown('<div class="ny-section-title">要確認案件</div>', unsafe_allow_html=True)
        safe_df_display(
            need_check,
            "要確認案件はありません。",
            ["client_name", "case_title", "status", "next_check_date", "next_check"],
            height=180
        )

    st.markdown('<div class="ny-footer">© にゃんとも相談管理 Ver3.2.6｜安定・安全・効率的な相談業務をサポートします 🐾</div>', unsafe_allow_html=True)



def render_clients():
    st.subheader("相談者 登録・検索・更新・削除")
    st.markdown("### 登録")
    with st.form("client_create"):
        name = st.text_input("お名前")
        age_group = st.selectbox("年代", AGE_OPTIONS)
        area = st.text_input("地域")
        contact_method = st.selectbox("連絡方法", CONTACT_OPTIONS)
        position = st.selectbox("立場", POSITION_OPTIONS)
        note = st.text_area("備考")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        if not name.strip():
            st.error("お名前を入力してください。")
        else:
            client_id = make_id("client")
            execute("""
                INSERT INTO clients
                (client_id, created_at, updated_at, name, age_group, area, contact_method, position, note)
                VALUES (%(client_id)s, %(created_at)s, %(updated_at)s, %(name)s, %(age_group)s, %(area)s, %(contact_method)s, %(position)s, %(note)s)
            """, {
                "client_id": client_id, "created_at": now_text(), "updated_at": now_text(),
                "name": name.strip(), "age_group": age_group, "area": area,
                "contact_method": contact_method, "position": position, "note": note
            })
            log_action("create", "clients", client_id, "相談者登録")
            st.success("相談者を登録しました。")
            st.rerun()

    st.markdown("---")
    keyword = st.text_input("検索語（名前・地域・備考）", key="client_search")
    clients = get_clients()
    filtered = clients.copy()
    if keyword and not filtered.empty:
        filtered = filtered[
            filtered["name"].astype(str).str.contains(keyword, na=False) |
            filtered["area"].astype(str).str.contains(keyword, na=False) |
            filtered["note"].astype(str).str.contains(keyword, na=False)
        ]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    if not filtered.empty and can_write():
        selected = st.selectbox("更新・削除する相談者", filtered["client_id"].tolist())
        row = clients[clients["client_id"] == selected].iloc[0]
        with st.form("client_edit"):
            new_name = st.text_input("お名前", normalize_text(row["name"]))
            new_age = st.selectbox("年代", AGE_OPTIONS, index=AGE_OPTIONS.index(row["age_group"]) if row["age_group"] in AGE_OPTIONS else 0)
            new_area = st.text_input("地域", normalize_text(row["area"]))
            new_contact = st.selectbox("連絡方法", CONTACT_OPTIONS, index=CONTACT_OPTIONS.index(row["contact_method"]) if row["contact_method"] in CONTACT_OPTIONS else 0)
            new_position = st.selectbox("立場", POSITION_OPTIONS, index=POSITION_OPTIONS.index(row["position"]) if row["position"] in POSITION_OPTIONS else 0)
            new_note = st.text_area("備考", normalize_text(row["note"]))
            delete_confirm = st.checkbox("この相談者を削除することを確認しました。関連案件も削除されます。")
            delete_text = st.text_input("削除する場合は DELETE と入力")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")
        if update:
            execute("""
                UPDATE clients SET updated_at=%(updated_at)s, name=%(name)s, age_group=%(age_group)s, area=%(area)s,
                    contact_method=%(contact_method)s, position=%(position)s, note=%(note)s
                WHERE client_id=%(client_id)s
            """, {
                "updated_at": now_text(), "name": new_name.strip(), "age_group": new_age, "area": new_area,
                "contact_method": new_contact, "position": new_position, "note": new_note, "client_id": selected
            })
            log_action("update", "clients", selected, "相談者更新")
            st.success("相談者を更新しました。")
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM clients WHERE client_id=%(client_id)s", {"client_id": selected})
                log_action("delete", "clients", selected, "相談者削除")
                st.success("相談者を削除しました。")
                st.rerun()


def render_cases():
    st.subheader("案件 登録・検索・更新・削除")
    client_map, client_labels = get_client_options()

    st.markdown("### 登録")
    if not client_labels:
        st.warning("先に相談者を登録してください。")
    else:
        with st.form("case_create"):
            client_label = st.selectbox("相談者", client_labels)
            consult_date = st.date_input("相談日", date.today())
            case_title = st.text_input("案件名")
            case_type = st.selectbox("案件種別", CASE_TYPE_OPTIONS)
            status = st.selectbox("状態", STATUS_OPTIONS)
            current_state = st.text_area("現在の状態")
            house_state = st.text_area("住まい・空き家の状態")
            cat_relation = st.text_area("猫との関係")
            family_gap = st.text_area("家族間の温度差")
            pressure = st.text_area("急がされ感")
            worries = st.text_area("心配ごと")
            not_decide = st.text_area("今は決めないこと")
            first_check = st.text_area("初回確認事項")
            free_memo = st.text_area("外部向けメモ")
            internal_memo = st.text_area("内部メモ")
            next_check = st.text_area("次回確認")
            next_hearing_items = st.text_area("次回ヒアリング項目")
            hearing_missing = st.text_area("ヒアリング漏れ警告")
            do_not_do_now = st.text_area("今やらない方がいいこと")
            next_check_date = st.date_input("次回確認日", value=None)
            ok = st.form_submit_button("登録する", disabled=not can_write())

        if ok:
            if not case_title.strip():
                st.error("案件名を入力してください。")
            else:
                case_id = make_id("case")
                client_id = client_map[client_label]
                execute("""
                    INSERT INTO cases
                    (case_id, client_id, created_at, updated_at, consult_date, case_title, case_type, status,
                     current_state, house_state, cat_relation, family_gap, pressure, worries, not_decide,
                     first_check, free_memo, internal_memo, next_check, next_hearing_items, hearing_missing, do_not_do_now, next_check_date)
                    VALUES
                    (%(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(consult_date)s, %(case_title)s, %(case_type)s, %(status)s,
                     %(current_state)s, %(house_state)s, %(cat_relation)s, %(family_gap)s, %(pressure)s, %(worries)s, %(not_decide)s,
                     %(first_check)s, %(free_memo)s, %(internal_memo)s, %(next_check)s, %(next_hearing_items)s, %(hearing_missing)s, %(do_not_do_now)s, %(next_check_date)s)
                """, {
                    "case_id": case_id, "client_id": client_id, "created_at": now_text(), "updated_at": now_text(),
                    "consult_date": consult_date, "case_title": case_title.strip(), "case_type": case_type, "status": status,
                    "current_state": current_state, "house_state": house_state, "cat_relation": cat_relation,
                    "family_gap": family_gap, "pressure": pressure, "worries": worries, "not_decide": not_decide,
                    "first_check": first_check, "free_memo": free_memo, "internal_memo": internal_memo,
                    "next_check": next_check, "next_hearing_items": next_hearing_items, "hearing_missing": hearing_missing,
                    "do_not_do_now": do_not_do_now, "next_check_date": next_check_date
                })
                log_action("create", "cases", case_id, "案件登録")
                st.success("案件を登録しました。")
                st.rerun()

    st.markdown("---")
    keyword = st.text_input("検索語（相談者・案件名・状態・メモ）", key="case_search")
    cases = get_cases()
    filtered = cases.copy()
    if keyword and not filtered.empty:
        filtered = filtered[
            filtered["client_name"].astype(str).str.contains(keyword, na=False) |
            filtered["case_title"].astype(str).str.contains(keyword, na=False) |
            filtered["status"].astype(str).str.contains(keyword, na=False) |
            filtered["internal_memo"].astype(str).str.contains(keyword, na=False) |
            filtered["next_hearing_items"].astype(str).str.contains(keyword, na=False) |
            filtered["hearing_missing"].astype(str).str.contains(keyword, na=False) |
            filtered["do_not_do_now"].astype(str).str.contains(keyword, na=False)
        ]
    show_cols = ["case_id", "client_name", "case_title", "case_type", "status", "consult_date", "next_check_date", "updated_at"]
    st.dataframe(filtered[show_cols] if not filtered.empty else filtered, use_container_width=True, hide_index=True)

    if not filtered.empty and can_write():
        selected = st.selectbox("更新・削除する案件", filtered["case_id"].tolist())
        row = cases[cases["case_id"] == selected].iloc[0]
        with st.form("case_edit"):
            new_title = st.text_input("案件名", normalize_text(row["case_title"]))
            new_type = st.selectbox("案件種別", CASE_TYPE_OPTIONS, index=CASE_TYPE_OPTIONS.index(row["case_type"]) if row["case_type"] in CASE_TYPE_OPTIONS else 0)
            new_status = st.selectbox("状態", STATUS_OPTIONS, index=STATUS_OPTIONS.index(row["status"]) if row["status"] in STATUS_OPTIONS else 0)
            new_current_state = st.text_area("現在の状態", normalize_text(row["current_state"]))
            new_house_state = st.text_area("住まい・空き家の状態", normalize_text(row["house_state"]))
            new_cat_relation = st.text_area("猫との関係", normalize_text(row["cat_relation"]))
            new_family_gap = st.text_area("家族間の温度差", normalize_text(row["family_gap"]))
            new_pressure = st.text_area("急がされ感", normalize_text(row["pressure"]))
            new_worries = st.text_area("心配ごと", normalize_text(row["worries"]))
            new_not_decide = st.text_area("今は決めないこと", normalize_text(row["not_decide"]))
            new_internal_memo = st.text_area("内部メモ", normalize_text(row["internal_memo"]))
            new_next_check = st.text_area("次回確認", normalize_text(row["next_check"]))
            new_next_hearing_items = st.text_area("次回ヒアリング項目", normalize_text(row["next_hearing_items"]))
            new_hearing_missing = st.text_area("ヒアリング漏れ警告", normalize_text(row["hearing_missing"]))
            new_do_not_do_now = st.text_area("今やらない方がいいこと", normalize_text(row["do_not_do_now"]))
            new_next_check_date = st.date_input("次回確認日", date_or_none(row["next_check_date"]))
            new_final_memo = st.text_area("終了・最終メモ", normalize_text(row["final_memo"]))
            delete_confirm = st.checkbox("この案件を削除することを確認しました。関連データも削除されます。")
            delete_text = st.text_input("削除する場合は DELETE と入力", key="case_delete_text")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")
        if update:
            before_status = row["status"]
            execute("""
                UPDATE cases SET updated_at=%(updated_at)s, case_title=%(case_title)s, case_type=%(case_type)s, status=%(status)s,
                    current_state=%(current_state)s, house_state=%(house_state)s, cat_relation=%(cat_relation)s,
                    family_gap=%(family_gap)s, pressure=%(pressure)s, worries=%(worries)s, not_decide=%(not_decide)s,
                    internal_memo=%(internal_memo)s, next_check=%(next_check)s, next_hearing_items=%(next_hearing_items)s,
                    hearing_missing=%(hearing_missing)s, do_not_do_now=%(do_not_do_now)s,
                    next_check_date=%(next_check_date)s, final_memo=%(final_memo)s
                WHERE case_id=%(case_id)s
            """, {
                "updated_at": now_text(), "case_title": new_title, "case_type": new_type, "status": new_status,
                "current_state": new_current_state, "house_state": new_house_state, "cat_relation": new_cat_relation,
                "family_gap": new_family_gap, "pressure": new_pressure, "worries": new_worries, "not_decide": new_not_decide,
                "internal_memo": new_internal_memo, "next_check": new_next_check, "next_hearing_items": new_next_hearing_items,
                "hearing_missing": new_hearing_missing, "do_not_do_now": new_do_not_do_now,
                "next_check_date": new_next_check_date, "final_memo": new_final_memo, "case_id": selected
            })
            if before_status != new_status:
                history_id = make_id("hist")
                execute("""
                    INSERT INTO history
                    (history_id, case_id, client_id, created_at, record_date, record_type, before_status, after_status, record, next_action, internal_memo)
                    VALUES (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(before_status)s, %(after_status)s, %(record)s, %(next_action)s, %(internal_memo)s)
                """, {
                    "history_id": history_id, "case_id": selected, "client_id": row["client_id"], "created_at": now_text(),
                    "record_date": today_text(), "record_type": "状態変更", "before_status": before_status, "after_status": new_status,
                    "record": f"状態を {before_status} から {new_status} に変更", "next_action": new_next_check,
                    "internal_memo": "案件更新時に自動記録"
                })
            log_action("update", "cases", selected, "案件更新")
            st.success("案件を更新しました。")
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM cases WHERE case_id=%(case_id)s", {"case_id": selected})
                log_action("delete", "cases", selected, "案件削除")
                st.success("案件を削除しました。")
                st.rerun()


def related_card_page(table_name, id_col, title, fields):
    st.subheader(title)
    card_type = title
    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
        return
    selected_label = st.selectbox("対象案件", case_labels)
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)

    st.markdown("### 登録")
    with st.form(f"{table_name}_create"):
        values = {}
        for key, label, kind in fields:
            if card_type == "支援者カード" and key == "field_1":
                values[key] = st.selectbox(label, SUPPORT_CATEGORY_OPTIONS)
            elif card_type == "支援者カード" and key == "field_5":
                values[key] = st.selectbox(label, ["◎ 協力的", "○ 通常", "△ 慎重", "－ 未接続", "要注意", "不明"])
            elif card_type == "支援者カード" and key == "field_6":
                values[key] = st.selectbox(label, ["未連携", "連携候補", "連携中", "安定連携", "一時停止", "終了"])
            elif kind == "area":
                values[key] = st.text_area(label)
            else:
                values[key] = st.text_input(label)
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        new_id = make_id(id_col.replace("_id", ""))
        cols = [id_col, "case_id", "client_id", "created_at", "updated_at"] + [x[0] for x in fields]
        params = {id_col: new_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "updated_at": now_text(), **values}
        execute(f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({', '.join([f'%({c})s' for c in cols])})", params)
        log_action("create", table_name, new_id, f"{title}登録")
        st.success("登録しました。")
        st.rerun()

    st.markdown("---")
    df = fetch_df(f"SELECT * FROM {table_name} WHERE case_id=%(case_id)s ORDER BY created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty and can_write():
        selected = st.selectbox("編集するID", df[id_col].tolist(), key=f"{table_name}_select")
        row = df[df[id_col] == selected].iloc[0]
        with st.form(f"{table_name}_edit"):
            new_values = {}
            for key, label, kind in fields:
                if kind == "area":
                    new_values[key] = st.text_area(label, normalize_text(row[key]), key=f"{table_name}_{key}_edit")
                else:
                    new_values[key] = st.text_input(label, normalize_text(row[key]), key=f"{table_name}_{key}_edit")
            delete_confirm = st.checkbox("削除することを確認しました。", key=f"{table_name}_del_confirm")
            delete_text = st.text_input("削除する場合は DELETE と入力", key=f"{table_name}_del_text")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")
        if update:
            set_clause = ", ".join([f"{key}=%({key})s" for key, _, _ in fields])
            params = {**new_values, "updated_at": now_text(), "id": selected}
            execute(f"UPDATE {table_name} SET updated_at=%(updated_at)s, {set_clause} WHERE {id_col}=%(id)s", params)
            log_action("update", table_name, selected, f"{title}更新")
            st.success("更新しました。")
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute(f"DELETE FROM {table_name} WHERE {id_col}=%(id)s", {"id": selected})
                log_action("delete", table_name, selected, f"{title}削除")
                st.success("削除しました。")
                st.rerun()


def render_history():
    st.subheader("相談履歴 登録・確認")
    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
        return
    selected_label = st.selectbox("対象案件", case_labels)
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)
    with st.form("history_create"):
        record_date = st.date_input("記録日", date.today())
        record_type = st.selectbox("記録種別", ["相談", "電話", "LINE", "訪問", "状態変更", "内部メモ", "その他"])
        record = st.text_area("記録内容")
        next_action = st.text_area("次の対応")
        internal_memo = st.text_area("内部メモ")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        if not record.strip():
            st.error("記録内容を入力してください。")
        else:
            history_id = make_id("hist")
            execute("""
                INSERT INTO history
                (history_id, case_id, client_id, created_at, record_date, record_type, record, next_action, internal_memo)
                VALUES (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(record)s, %(next_action)s, %(internal_memo)s)
            """, {
                "history_id": history_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(),
                "record_date": record_date, "record_type": record_type, "record": record, "next_action": next_action, "internal_memo": internal_memo
            })
            execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
            log_action("create", "history", history_id, "相談履歴登録")
            st.success("相談履歴を登録しました。")
            st.rerun()
    df = fetch_df("""
        SELECT history_id, record_date, record_type, before_status, after_status, record, next_action, internal_memo, created_at
        FROM history WHERE case_id=%(case_id)s ORDER BY record_date DESC, created_at DESC
    """, {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_line_memos():
    related_card_page("line_messages", "message_id", "LINEメモ", [
        ("to_target", "送信先・対象", "text"),
        ("message_text", "送信文", "area"),
        ("send_status", "状態", "text"),
        ("response_memo", "返信・反応メモ", "area"),
    ])


def render_line_templates():
    st.subheader("LINEテンプレート")
    with st.form("line_template_create"):
        template_name = st.text_input("テンプレート名")
        template_type = st.text_input("種別")
        template_text = st.text_area("テンプレート本文")
        memo = st.text_area("メモ")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        template_id = make_id("tpl")
        execute("""
            INSERT INTO line_templates
            (template_id, created_at, updated_at, template_name, template_type, template_text, active, memo)
            VALUES (%(template_id)s, %(created_at)s, %(updated_at)s, %(template_name)s, %(template_type)s, %(template_text)s, 1, %(memo)s)
        """, {
            "template_id": template_id, "created_at": now_text(), "updated_at": now_text(),
            "template_name": template_name, "template_type": template_type, "template_text": template_text, "memo": memo
        })
        log_action("create", "line_templates", template_id, "LINEテンプレート登録")
        st.success("登録しました。")
        st.rerun()

    df = fetch_df("SELECT * FROM line_templates ORDER BY updated_at DESC NULLS LAST, created_at DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty and can_write():
        selected = st.selectbox("削除するテンプレートID", df["template_id"].tolist())
        if st.button("選択テンプレートを削除"):
            execute("DELETE FROM line_templates WHERE template_id=%(id)s", {"id": selected})
            log_action("delete", "line_templates", selected, "LINEテンプレート削除")
            st.success("削除しました。")
            st.rerun()



# ============================================================
# 自動バックアップ
# ============================================================

def get_secret_value(key, default=""):
    """st.secrets と環境変数の両方から設定値を取得する。"""
    try:
        if key in st.secrets:
            return st.secrets.get(key, default)
    except Exception:
        pass
    return os.environ.get(key, default)


def ensure_extension_tables():
    """app.py側で追加機能用テーブルを作る。db.py未改修でも動くようにする。"""
    execute("""
        CREATE TABLE IF NOT EXISTS nyantomo_backup_logs (
            backup_id TEXT PRIMARY KEY,
            created_at TIMESTAMP,
            created_by TEXT,
            backup_type TEXT,
            file_name TEXT,
            table_count INTEGER,
            note TEXT
        )
    """)
    # ai_summaries はdb.py側にある想定だが、古いDBでも落ちないよう最低限作成
    execute("""
        CREATE TABLE IF NOT EXISTS ai_summaries (
            summary_id TEXT PRIMARY KEY,
            case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
            client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            summary_type TEXT,
            source_text TEXT,
            summary_text TEXT,
            memo TEXT
        )
    """)
    try:
        execute("ALTER TABLE ai_summaries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP")
    except Exception:
        pass
    try:
        execute("ALTER TABLE ai_summaries ADD COLUMN IF NOT EXISTS model TEXT")
    except Exception:
        pass



    # PostgreSQLでは、過去の失敗したCREATE TABLE等で
    # テーブル本体は無いのに同名の型だけが残ることがあります。
    # その状態で CREATE TABLE IF NOT EXISTS を実行すると
    # duplicate key value violates unique constraint "pg_type_typname_nsp_index"
    # が出るため、テーブルが無く型だけ残っている場合のみ型を掃除します。
    for _table_name in ["consultation_cards", "pending_items"]:
        try:
            execute(f"""
                DO $$
                BEGIN
                    IF to_regclass('public.{_table_name}') IS NULL
                       AND EXISTS (
                           SELECT 1
                           FROM pg_type t
                           JOIN pg_namespace n ON n.oid = t.typnamespace
                           WHERE t.typname = '{_table_name}'
                             AND n.nspname = 'public'
                       ) THEN
                        EXECUTE 'DROP TYPE public.{_table_name} CASCADE';
                    END IF;
                END $$;
            """)
        except Exception:
            pass

    # ========================================================
    # にゃんとも相談管理 Ver2.0：カード整理OS 追加テーブル
    # ========================================================
    execute("""
        CREATE TABLE IF NOT EXISTS consultation_cards (
            card_id TEXT PRIMARY KEY,
            case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
            client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            card_type TEXT,
            card_status TEXT,
            concern TEXT,
            client_words TEXT,
            current_state TEXT,
            unknown_items TEXT,
            related_people_places TEXT,
            next_check_items TEXT,
            memo TEXT
        )
    """)
    # Ver2.1：基本情報カードとの紐付け用カラム
    # related_table: cats / properties / family
    # related_id: cat_id / property_id / family_id
    # related_label: 表示用ラベル（登録時点の控え）
    for _col_sql in [
        "ALTER TABLE consultation_cards ADD COLUMN IF NOT EXISTS related_table TEXT",
        "ALTER TABLE consultation_cards ADD COLUMN IF NOT EXISTS related_id TEXT",
        "ALTER TABLE consultation_cards ADD COLUMN IF NOT EXISTS related_label TEXT",
    ]:
        try:
            execute(_col_sql)
        except Exception:
            pass
    execute("""
        CREATE TABLE IF NOT EXISTS pending_items (
            pending_id TEXT PRIMARY KEY,
            case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
            client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            theme TEXT,
            reason TEXT,
            deadline_type TEXT,
            next_check_date DATE,
            related_people TEXT,
            caution TEXT,
            status TEXT,
            memo TEXT
        )
    """)




    # ========================================================
    # 後見モード Ver1.0 追加テーブル
    # ========================================================
    execute("""
        CREATE TABLE IF NOT EXISTS guardian_wards (
            ward_id TEXT PRIMARY KEY,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            created_by TEXT,
            confidentiality_level TEXT,
            status TEXT,
            name TEXT NOT NULL,
            birth_date DATE,
            address TEXT,
            phone TEXT,
            facility_name TEXT,
            guardian_type TEXT,
            petitioner TEXT,
            court_name TEXT,
            guardian_name TEXT,
            start_date DATE,
            end_date DATE,
            emergency_level TEXT,
            next_check_date DATE,
            memo TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS guardian_cards (
            card_id TEXT PRIMARY KEY,
            ward_id TEXT REFERENCES guardian_wards(ward_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            card_type TEXT,
            confidentiality_level TEXT,
            status TEXT,
            related_card_id TEXT,
            title TEXT,
            field_1 TEXT,
            field_2 TEXT,
            field_3 TEXT,
            field_4 TEXT,
            field_5 TEXT,
            field_6 TEXT,
            field_7 TEXT,
            field_8 TEXT,
            field_9 TEXT,
            field_10 TEXT,
            memo TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS guardian_interview_logs (
            log_id TEXT PRIMARY KEY,
            ward_id TEXT REFERENCES guardian_wards(ward_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            confidentiality_level TEXT,
            interview_date DATE,
            place TEXT,
            content TEXT,
            ward_words TEXT,
            family_words TEXT,
            action_taken TEXT,
            next_check TEXT,
            memo TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS guardian_resource_map (
            map_id TEXT PRIMARY KEY,
            ward_id TEXT REFERENCES guardian_wards(ward_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            confidentiality_level TEXT,
            family_status TEXT,
            medical_status TEXT,
            care_status TEXT,
            housing_status TEXT,
            asset_status TEXT,
            pet_status TEXT,
            professional_status TEXT,
            overall_status TEXT,
            shortage_memo TEXT,
            enough_memo TEXT,
            do_not_add_memo TEXT,
            next_check TEXT,
            memo TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS guardian_ai_support (
            ai_id TEXT PRIMARY KEY,
            ward_id TEXT REFERENCES guardian_wards(ward_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_by TEXT,
            support_type TEXT,
            source_text TEXT,
            result_text TEXT,
            model TEXT,
            memo TEXT
        )
    """)


def get_backup_tables():
    """config.TABLESに存在する主要テーブルをバックアップ対象にする。"""
    seen = set()
    tables = []
    for table, label in TABLES:
        if table not in seen:
            tables.append((table, label))
            seen.add(table)
    for table, label in [("nyantomo_backup_logs", "自動バックアップログ"), ("consultation_cards", "相談カード整理"), ("pending_items", "保留事項"), ("guardian_wards", "後見_被後見人"), ("guardian_cards", "後見_カード"), ("guardian_interview_logs", "後見_面談記録"), ("guardian_resource_map", "後見_リソース地図"), ("guardian_ai_support", "後見_AI支援")]:
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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    """最終自動バックアップから指定時間以上経っていれば自動作成する。"""
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
            elapsed_hours = (datetime.now() - last).total_seconds() / 3600
            should_run = elapsed_hours >= hours
        except Exception:
            should_run = True

    if should_run:
        path = save_backup_file("auto", f"AUTO_BACKUP_HOURS={hours}")
        cleanup_old_backups()
        return path
    return None


# ============================================================
# AI要約連携
# ============================================================

def get_openai_api_key():
    try:
        if "openai" in st.secrets and "api_key" in st.secrets["openai"]:
            return st.secrets["openai"]["api_key"]
    except Exception:
        pass
    return get_secret_value("OPENAI_API_KEY", "")


def get_openai_model():
    return get_secret_value("OPENAI_MODEL", DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL


def build_case_ai_source(case_id):
    """AI要約用に、案件・履歴・関連カードを1つの安全なテキストにまとめる。"""
    case = fetch_one("""
        SELECT c.*, cl.name AS client_name, cl.age_group, cl.area, cl.contact_method, cl.position, cl.note AS client_note
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        WHERE c.case_id = %(case_id)s
    """, {"case_id": case_id})
    if not case:
        return ""

    def df_to_lines(title, df, cols):
        lines = [f"\n■ {title}"]
        if df.empty:
            lines.append("未登録")
            return "\n".join(lines)
        for _, r in df.iterrows():
            parts = []
            for col in cols:
                if col in r and normalize_text(r[col]):
                    parts.append(f"{col}:{normalize_text(r[col])}")
            lines.append("- " + "／".join(parts))
        return "\n".join(lines)

    source = f"""【相談者】
氏名:{case.get('client_name','')}
地域:{case.get('area','')}
年代:{case.get('age_group','')}
連絡方法:{case.get('contact_method','')}
立場:{case.get('position','')}
相談者備考:{case.get('client_note','')}

【案件】
案件名:{case.get('case_title','')}
案件種別:{case.get('case_type','')}
状態:{case.get('status','')}
相談日:{case.get('consult_date','')}
現在の状態:{case.get('current_state','')}
住まい・空き家の状態:{case.get('house_state','')}
猫との関係:{case.get('cat_relation','')}
家族間の温度差:{case.get('family_gap','')}
急がされ感:{case.get('pressure','')}
心配ごと:{case.get('worries','')}
今は決めないこと:{case.get('not_decide','')}
初回確認事項:{case.get('first_check','')}
外部向けメモ:{case.get('free_memo','')}
内部メモ:{case.get('internal_memo','')}
次回確認:{case.get('next_check','')}
次回ヒアリング項目:{case.get('next_hearing_items','')}
ヒアリング漏れ警告:{case.get('hearing_missing','')}
今やらない方がいいこと:{case.get('do_not_do_now','')}
次回確認日:{case.get('next_check_date','')}
終了・最終メモ:{case.get('final_memo','')}
"""

    history = fetch_df("""
        SELECT record_date, record_type, before_status, after_status, record, next_action, internal_memo
        FROM history WHERE case_id=%(case_id)s
        ORDER BY record_date DESC NULLS LAST, created_at DESC LIMIT 20
    """, {"case_id": case_id})
    source += df_to_lines("相談履歴", history, ["record_date", "record_type", "before_status", "after_status", "record", "next_action", "internal_memo"])

    related_specs = [
        ("properties", "空き家カード", ["property_name", "address", "property_status", "vacant_status", "key_hold", "neighborhood", "visit_frequency", "memo"]),
        ("cats", "猫情報カード", ["cat_name", "age", "sex", "health_memo", "life_status", "future_plan", "memo"]),
        ("family", "家族関係メモ", ["name", "relation", "contact_ok", "temperature", "memo"]),
        ("consultation_cards", "Ver2.1カード整理", ["card_type", "card_status", "related_label", "concern", "client_words", "current_state", "unknown_items", "related_people_places", "next_check_items", "memo"]),
        ("pending_items", "Ver2.0保留事項", ["theme", "reason", "deadline_type", "next_check_date", "related_people", "caution", "status", "memo"]),
        ("line_messages", "LINEメモ", ["to_target", "message_text", "send_status", "response_memo"]),
    ]
    for table, title, cols in related_specs:
        try:
            df = fetch_df(f"SELECT * FROM {table} WHERE case_id=%(case_id)s ORDER BY created_at DESC LIMIT 20", {"case_id": case_id})
            source += df_to_lines(title, df, cols)
        except Exception as e:
            source += f"\n■ {title}\n取得エラー:{e}"

    return source.strip()


def build_ai_prompt(summary_type, source_text):
    """Ver2.2：カード整理AI用プロンプト。
    相談記録の一般要約ではなく、カード・保留・次回確認を中心に整理する。
    """
    return f"""
あなたは『にゃんとも 住まいと猫の相談室』の内部用「カード整理AI」です。
役割は、相談記録を一般的に要約することではありません。
相談者の言葉・基本情報カード・Ver2.1判断カード・保留事項を読み取り、
「いま机の上に並んでいるカード」を見える化してください。

最重要ルール：
- 法律判断、医療判断、不動産判断、税務判断はしない
- 売却すべき、後見すべき、信託すべき等の結論を出さない
- 相談者を急がせない
- 断定しない
- 診断しない
- スコア化しない
- 相談者の言葉を勝手に強い表現へ変えない
- 事実、未確定、保留、次回確認を分ける
- にゃんともは「判断の時間を守る」立場で整理する

出力形式は必ず以下の見出しで作成してください。

## 1. 今回見えているテーマ
- 例：猫の将来
- 例：空き家管理
- 例：家族との温度差

## 2. いま机の上に並んでいるカード
カードごとに、次の形で整理してください。
- 🐾 カード種別：
- 関連する基本情報：
- 状態：
- 相談者の言葉・気になっていること：
- 未確認事項：
- 次回確認：

## 3. 今すぐ決めなくてよいこと
- 例：売却時期
- 例：後見制度を使うかどうか
- 例：猫の預け先を最終決定すること

## 4. 少し整理した方がよいこと
- 例：兄との話し合い状況
- 例：鍵の所在
- 例：動物病院・預け先候補

## 5. 次回確認
- 次回の面談・連絡で確認するとよいことを3〜5個に絞る

## 6. 専門家につなぐ可能性
- 弁護士、司法書士、税理士、宅建士、ケアマネ、包括、動物病院など
- ただし「必要」と断定せず「可能性」として整理する

## 7. にゃんともとして関われる範囲
- 相談整理、記録、空き家見守り、関係者整理、次回確認など
- 断定や交渉ではなく、整理・保留・伴走の範囲で書く

## 8. にゃんともでは扱わない方がよい範囲
- 紛争、税務判断、登記、医療判断、強い不動産判断など
- 必要に応じて他専門職へつなぐ可能性として書く

## 9. 内部メモ用の短い要約
3〜5行で、今回の相談の見取り図を短くまとめる。

整理種別：{summary_type}

以下の記録をカード整理してください。
---
{source_text}
""".strip()

def call_openai_summary(prompt):
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が設定されていません。")
    model = get_openai_model()
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("openai パッケージがありません。requirements.txt に openai を追加してください。") from e

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "あなたは相談記録を安全に整理する日本語の業務補助AIです。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip(), model


def save_ai_summary(case_id, client_id, summary_type, source_text, summary_text, memo="", model=""):
    summary_id = make_id("summary")
    # model列がないDBでも保存できるよう2段階にする
    try:
        execute("""
            INSERT INTO ai_summaries
            (summary_id, case_id, client_id, created_at, updated_at, summary_type, source_text, summary_text, memo, model)
            VALUES (%(summary_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(summary_type)s, %(source_text)s, %(summary_text)s, %(memo)s, %(model)s)
        """, {
            "summary_id": summary_id,
            "case_id": case_id,
            "client_id": client_id,
            "created_at": now_text(),
            "updated_at": now_text(),
            "summary_type": summary_type,
            "source_text": source_text,
            "summary_text": summary_text,
            "memo": memo,
            "model": model,
        })
    except Exception:
        execute("""
            INSERT INTO ai_summaries
            (summary_id, case_id, client_id, created_at, updated_at, summary_type, source_text, summary_text, memo)
            VALUES (%(summary_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(summary_type)s, %(source_text)s, %(summary_text)s, %(memo)s)
        """, {
            "summary_id": summary_id,
            "case_id": case_id,
            "client_id": client_id,
            "created_at": now_text(),
            "updated_at": now_text(),
            "summary_type": summary_type,
            "source_text": source_text,
            "summary_text": summary_text,
            "memo": memo,
        })
    log_action("create", "ai_summaries", summary_id, f"AI要約作成：{summary_type}")
    return summary_id



# ============================================================
# にゃんとも相談管理 Ver2.0：カード整理OS
# ============================================================

def get_case_selector(key):
    """案件選択UIを共通化する。"""
    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に相談者と案件を登録してください。")
        return None, None
    selected_label = st.selectbox("対象案件", case_labels, key=key)
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)
    return case_id, client_id


def get_related_base_options(card_type, case_id):
    """Ver2.1：カード種別に応じて、紐付け可能な基本情報カードを返す。"""
    spec = RELATED_BASE_CARD_MAP.get(card_type)
    if not spec:
        return {}, ["紐付けなし"], "", ""

    table = spec["table"]
    id_col = spec["id_col"]
    label_sql = spec["label_sql"]
    base_label = spec["label"]
    try:
        df = fetch_df(f"""
            SELECT {id_col} AS related_id, {label_sql} AS related_label
            FROM {table}
            WHERE case_id=%(case_id)s
            ORDER BY created_at DESC
        """, {"case_id": case_id})
    except Exception:
        return {}, ["紐付けなし"], spec["table"], base_label

    mapping = {"紐付けなし": ("", "")}
    labels = ["紐付けなし"]
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            rid = normalize_text(r.get("related_id", ""))
            rlabel = normalize_text(r.get("related_label", ""))
            if rid:
                label = f"{base_label}｜{rlabel}｜{rid}"
                labels.append(label)
                mapping[label] = (rid, f"{base_label}｜{rlabel}")
    return mapping, labels, spec["table"], base_label


def find_related_label(labels, mapping, related_id):
    """保存済みrelated_idからselectbox初期値のindexを探す。"""
    related_id = normalize_text(related_id)
    if not related_id:
        return "紐付けなし"
    for label, (rid, _) in mapping.items():
        if rid == related_id:
            return label
    return "紐付けなし"


def render_consultation_cards():
    st.subheader("Ver2.1｜カード整理")
    st.caption("相談者の悩みをカード化し、猫情報カード・空き家カード・家族関係メモなどの基本情報カードへ紐付けます。基本情報は台帳、Ver2.1カードは判断整理です。")

    case_id, client_id = get_case_selector("consultation_cards_case")
    if not case_id:
        return

    st.markdown("### カード登録")
    st.info("猫情報カード・空き家カード・家族関係メモは基本情報として先に登録しておくと、この画面で紐付けできます。")

    with st.form("consultation_card_create"):
        c1, c2 = st.columns(2)
        with c1:
            card_type = st.selectbox("カード種別", NYANTOMO_CARD_TYPES)
        with c2:
            card_status = st.selectbox("状態", NYANTOMO_CARD_STATUS_OPTIONS)

        related_mapping, related_labels, related_table, base_label = get_related_base_options(card_type, case_id)
        if related_table:
            related_select = st.selectbox(f"紐付ける基本情報（{base_label}）", related_labels)
        else:
            related_select = "紐付けなし"
            st.caption("このカード種別は、現時点では基本情報カードとの直接紐付け対象外です。")

        concern = st.text_area("気になっていること")
        client_words = st.text_area("相談者の言葉（できるだけ原文）")
        current_state = st.text_area("現在の状態")
        unknown_items = st.text_area("未確認事項")
        related_people_places = st.text_area("関係する人・場所")
        next_check_items = st.text_area("次回確認したいこと")
        memo = st.text_area("内部メモ")
        ok = st.form_submit_button("カードを登録する", disabled=not can_write())

    if ok:
        if not concern.strip() and not client_words.strip():
            st.error("「気になっていること」または「相談者の言葉」を入力してください。")
        else:
            related_id, related_label = related_mapping.get(related_select, ("", ""))
            card_id = make_id("card")
            execute("""
                INSERT INTO consultation_cards
                (card_id, case_id, client_id, created_at, updated_at, updated_by, card_type, card_status,
                 related_table, related_id, related_label,
                 concern, client_words, current_state, unknown_items, related_people_places, next_check_items, memo)
                VALUES
                (%(card_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s, %(card_type)s, %(card_status)s,
                 %(related_table)s, %(related_id)s, %(related_label)s,
                 %(concern)s, %(client_words)s, %(current_state)s, %(unknown_items)s, %(related_people_places)s, %(next_check_items)s, %(memo)s)
            """, {
                "card_id": card_id,
                "case_id": case_id,
                "client_id": client_id,
                "created_at": now_text(),
                "updated_at": now_text(),
                "updated_by": st.session_state.get("login_id", ""),
                "card_type": card_type,
                "card_status": card_status,
                "related_table": related_table if related_id else "",
                "related_id": related_id,
                "related_label": related_label,
                "concern": concern,
                "client_words": client_words,
                "current_state": current_state,
                "unknown_items": unknown_items,
                "related_people_places": related_people_places,
                "next_check_items": next_check_items,
                "memo": memo,
            })
            execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
            log_action("create", "consultation_cards", card_id, "Ver2.1カード登録")
            st.success("カードを登録しました。")
            st.rerun()

    st.markdown("---")
    st.markdown("### 登録済みカード")
    df = fetch_df("""
        SELECT card_id, card_type, card_status, related_table, related_id, related_label,
               concern, client_words, current_state, unknown_items,
               related_people_places, next_check_items, memo, updated_at
        FROM consultation_cards
        WHERE case_id=%(case_id)s
        ORDER BY
            CASE card_status
                WHEN '気になる' THEN 1
                WHEN '検討中' THEN 2
                WHEN '保留' THEN 3
                WHEN '整理済' THEN 4
                ELSE 9
            END,
            updated_at DESC NULLS LAST,
            created_at DESC
    """, {"case_id": case_id})

    show_cols = ["card_id", "card_type", "card_status", "related_label", "concern", "client_words", "current_state", "unknown_items", "next_check_items", "updated_at"]
    if df.empty:
        st.info("カードはまだ登録されていません。")
    else:
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

        st.markdown("### カード状態の俯瞰")
        view = df.groupby(["card_type", "card_status"], dropna=False).size().reset_index(name="件数")
        st.dataframe(view, use_container_width=True, hide_index=True)

    if not df.empty and can_write():
        st.markdown("---")
        selected = st.selectbox("更新・削除するカードID", df["card_id"].tolist(), key="consultation_card_edit_select")
        row = df[df["card_id"] == selected].iloc[0]
        with st.form("consultation_card_edit"):
            e1, e2 = st.columns(2)
            with e1:
                new_card_type = st.selectbox("カード種別", NYANTOMO_CARD_TYPES, index=NYANTOMO_CARD_TYPES.index(row["card_type"]) if row["card_type"] in NYANTOMO_CARD_TYPES else 0)
            with e2:
                new_card_status = st.selectbox("状態", NYANTOMO_CARD_STATUS_OPTIONS, index=NYANTOMO_CARD_STATUS_OPTIONS.index(row["card_status"]) if row["card_status"] in NYANTOMO_CARD_STATUS_OPTIONS else 0)

            edit_mapping, edit_labels, edit_related_table, edit_base_label = get_related_base_options(new_card_type, case_id)
            edit_default_label = find_related_label(edit_labels, edit_mapping, row.get("related_id", ""))
            if edit_related_table:
                new_related_select = st.selectbox(
                    f"紐付ける基本情報（{edit_base_label}）",
                    edit_labels,
                    index=edit_labels.index(edit_default_label) if edit_default_label in edit_labels else 0
                )
            else:
                new_related_select = "紐付けなし"
                st.caption("このカード種別は、現時点では基本情報カードとの直接紐付け対象外です。")

            new_concern = st.text_area("気になっていること", normalize_text(row["concern"]))
            new_client_words = st.text_area("相談者の言葉（できるだけ原文）", normalize_text(row["client_words"]))
            new_current_state = st.text_area("現在の状態", normalize_text(row["current_state"]))
            new_unknown_items = st.text_area("未確認事項", normalize_text(row["unknown_items"]))
            new_related_people_places = st.text_area("関係する人・場所", normalize_text(row["related_people_places"]))
            new_next_check_items = st.text_area("次回確認したいこと", normalize_text(row["next_check_items"]))
            new_memo = st.text_area("内部メモ", normalize_text(row["memo"]))
            delete_confirm = st.checkbox("このカードを削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力", key="consultation_card_delete_text")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            new_related_id, new_related_label = edit_mapping.get(new_related_select, ("", ""))
            execute("""
                UPDATE consultation_cards
                SET updated_at=%(updated_at)s, updated_by=%(updated_by)s, card_type=%(card_type)s, card_status=%(card_status)s,
                    related_table=%(related_table)s, related_id=%(related_id)s, related_label=%(related_label)s,
                    concern=%(concern)s, client_words=%(client_words)s, current_state=%(current_state)s, unknown_items=%(unknown_items)s,
                    related_people_places=%(related_people_places)s, next_check_items=%(next_check_items)s, memo=%(memo)s
                WHERE card_id=%(card_id)s
            """, {
                "updated_at": now_text(),
                "updated_by": st.session_state.get("login_id", ""),
                "card_type": new_card_type,
                "card_status": new_card_status,
                "related_table": edit_related_table if new_related_id else "",
                "related_id": new_related_id,
                "related_label": new_related_label,
                "concern": new_concern,
                "client_words": new_client_words,
                "current_state": new_current_state,
                "unknown_items": new_unknown_items,
                "related_people_places": new_related_people_places,
                "next_check_items": new_next_check_items,
                "memo": new_memo,
                "card_id": selected,
            })
            log_action("update", "consultation_cards", selected, "Ver2.1カード更新")
            st.success("カードを更新しました。")
            st.rerun()

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM consultation_cards WHERE card_id=%(card_id)s", {"card_id": selected})
                log_action("delete", "consultation_cards", selected, "Ver2.1カード削除")
                st.success("カードを削除しました。")
                st.rerun()


def render_pending_items():
    st.subheader("Ver2.0｜保留事項管理")
    st.caption("今すぐ決めなくてよいことを、安全に置いておくための画面です。保留は放置ではなく、次に確認する余白として管理します。")

    case_id, client_id = get_case_selector("pending_items_case")
    if not case_id:
        return

    st.markdown("### 保留事項登録")
    with st.form("pending_item_create"):
        theme = st.text_input("保留しているテーマ")
        reason = st.text_area("保留理由")
        c1, c2, c3 = st.columns(3)
        with c1:
            deadline_type = st.selectbox("期限の有無", PENDING_DEADLINE_OPTIONS)
        with c2:
            next_check_date = st.date_input("次回確認日", value=None)
        with c3:
            status = st.selectbox("状態", PENDING_STATUS_OPTIONS)
        related_people = st.text_area("関係者")
        caution = st.text_area("注意点")
        memo = st.text_area("内部メモ")
        ok = st.form_submit_button("保留事項を登録する", disabled=not can_write())

    if ok:
        if not theme.strip():
            st.error("保留しているテーマを入力してください。")
        else:
            pending_id = make_id("pending")
            execute("""
                INSERT INTO pending_items
                (pending_id, case_id, client_id, created_at, updated_at, updated_by, theme, reason,
                 deadline_type, next_check_date, related_people, caution, status, memo)
                VALUES
                (%(pending_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s, %(theme)s, %(reason)s,
                 %(deadline_type)s, %(next_check_date)s, %(related_people)s, %(caution)s, %(status)s, %(memo)s)
            """, {
                "pending_id": pending_id,
                "case_id": case_id,
                "client_id": client_id,
                "created_at": now_text(),
                "updated_at": now_text(),
                "updated_by": st.session_state.get("login_id", ""),
                "theme": theme,
                "reason": reason,
                "deadline_type": deadline_type,
                "next_check_date": next_check_date,
                "related_people": related_people,
                "caution": caution,
                "status": status,
                "memo": memo,
            })
            execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
            log_action("create", "pending_items", pending_id, "Ver2.0保留事項登録")
            st.success("保留事項を登録しました。")
            st.rerun()

    st.markdown("---")
    st.markdown("### 保留事項一覧")
    df = fetch_df("""
        SELECT pending_id, theme, reason, deadline_type, next_check_date, related_people, caution, status, memo, updated_at
        FROM pending_items
        WHERE case_id=%(case_id)s
        ORDER BY
            CASE status
                WHEN '保留中' THEN 1
                WHEN '次回確認' THEN 2
                WHEN '家族確認待ち' THEN 3
                WHEN '専門家確認待ち' THEN 4
                WHEN '整理済' THEN 5
                WHEN '終了' THEN 6
                ELSE 9
            END,
            next_check_date ASC NULLS LAST,
            updated_at DESC NULLS LAST
    """, {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty and can_write():
        st.markdown("---")
        selected = st.selectbox("更新・削除する保留事項ID", df["pending_id"].tolist(), key="pending_item_edit_select")
        row = df[df["pending_id"] == selected].iloc[0]
        with st.form("pending_item_edit"):
            new_theme = st.text_input("保留しているテーマ", normalize_text(row["theme"]))
            new_reason = st.text_area("保留理由", normalize_text(row["reason"]))
            e1, e2, e3 = st.columns(3)
            with e1:
                new_deadline_type = st.selectbox("期限の有無", PENDING_DEADLINE_OPTIONS, index=PENDING_DEADLINE_OPTIONS.index(row["deadline_type"]) if row["deadline_type"] in PENDING_DEADLINE_OPTIONS else 0)
            with e2:
                new_next_check_date = st.date_input("次回確認日", date_or_none(row["next_check_date"]))
            with e3:
                new_status = st.selectbox("状態", PENDING_STATUS_OPTIONS, index=PENDING_STATUS_OPTIONS.index(row["status"]) if row["status"] in PENDING_STATUS_OPTIONS else 0)
            new_related_people = st.text_area("関係者", normalize_text(row["related_people"]))
            new_caution = st.text_area("注意点", normalize_text(row["caution"]))
            new_memo = st.text_area("内部メモ", normalize_text(row["memo"]))
            delete_confirm = st.checkbox("この保留事項を削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力", key="pending_item_delete_text")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            execute("""
                UPDATE pending_items
                SET updated_at=%(updated_at)s, updated_by=%(updated_by)s, theme=%(theme)s, reason=%(reason)s,
                    deadline_type=%(deadline_type)s, next_check_date=%(next_check_date)s, related_people=%(related_people)s,
                    caution=%(caution)s, status=%(status)s, memo=%(memo)s
                WHERE pending_id=%(pending_id)s
            """, {
                "updated_at": now_text(),
                "updated_by": st.session_state.get("login_id", ""),
                "theme": new_theme,
                "reason": new_reason,
                "deadline_type": new_deadline_type,
                "next_check_date": new_next_check_date,
                "related_people": new_related_people,
                "caution": new_caution,
                "status": new_status,
                "memo": new_memo,
                "pending_id": selected,
            })
            log_action("update", "pending_items", selected, "Ver2.0保留事項更新")
            st.success("保留事項を更新しました。")
            st.rerun()

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM pending_items WHERE pending_id=%(pending_id)s", {"pending_id": selected})
                log_action("delete", "pending_items", selected, "Ver2.0保留事項削除")
                st.success("保留事項を削除しました。")
                st.rerun()


def ny_card_status_icon(status):
    """カード状態を視覚的に示すアイコンへ変換する。"""
    status = normalize_text(status)
    if status == "気になる":
        return "🟥"
    if status in ["検討中", "保留"]:
        return "🟨"
    if status == "整理済":
        return "🟩"
    return "⬜"


def ny_pending_status_icon(status):
    """保留事項の状態を視覚的に示すアイコンへ変換する。"""
    status = normalize_text(status)
    if status in ["家族確認待ち", "専門家確認待ち"]:
        return "🟧"
    if status in ["保留中", "次回確認"]:
        return "🟨"
    if status in ["整理済", "終了"]:
        return "🟩"
    return "⬜"


def ny_pick_summary(*values, max_len=36):
    """俯瞰カードに出す短い見出しを作る。"""
    for value in values:
        text_value = normalize_text(value)
        if text_value:
            text_value = " ".join(text_value.split())
            if len(text_value) > max_len:
                return text_value[:max_len] + "…"
            return text_value
    return "未入力"


def ny_html(value):
    return html.escape(normalize_text(value)).replace("\n", "<br>")


def render_nyantomo_card_tile(icon, title, headline, status, detail="", footer=""):
    """カードOS俯瞰用の小カードを表示する。"""
    title = ny_html(title)
    headline = ny_html(headline)
    status = ny_html(status)
    detail = ny_html(detail)
    footer = ny_html(footer)
    detail_html = f'<div class="ny-os-detail">{detail}</div>' if detail else ''
    footer_html = f'<div class="ny-os-footer">{footer}</div>' if footer else ''
    st.markdown(f"""
    <div class="ny-os-card">
        <div class="ny-os-title"><span class="ny-os-icon">{icon}</span> {title}</div>
        <div class="ny-os-headline">{headline}</div>
        <div class="ny-os-status">{status}</div>
        {detail_html}
        {footer_html}
    </div>
    """, unsafe_allow_html=True)


def render_card_os_overview():
    st.subheader("Ver2.1｜判断の時間を守るカード整理OS")
    st.caption("相談者の悩みを、件数表ではなく“見えるカード”として並べる画面です。何を急がず、何を次に確認するかを一目で確認します。")

    st.markdown("""
    <style>
    .ny-os-card {
        background: #ffffff;
        border: 1px solid #e8edf5;
        border-radius: 18px;
        padding: 16px 17px;
        margin-bottom: 12px;
        box-shadow: 0 7px 18px rgba(30, 41, 59, 0.06);
        min-height: 145px;
    }
    .ny-os-title {
        font-weight: 800;
        color: #172033;
        font-size: 1.04rem;
        margin-bottom: 8px;
    }
    .ny-os-icon {
        font-size: 1.12rem;
        margin-right: 2px;
    }
    .ny-os-headline {
        font-size: 1.02rem;
        font-weight: 700;
        color: #334155;
        line-height: 1.45;
        margin-bottom: 8px;
    }
    .ny-os-status {
        display: inline-block;
        padding: 3px 9px;
        border-radius: 999px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        color: #475569;
        font-size: 0.86rem;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .ny-os-detail {
        color: #64748b;
        font-size: 0.9rem;
        line-height: 1.45;
        margin-top: 6px;
    }
    .ny-os-footer {
        color: #94a3b8;
        font-size: 0.8rem;
        margin-top: 10px;
    }
    .ny-os-note {
        background: linear-gradient(135deg, #fffaf0 0%, #ffffff 80%);
        border: 1px solid #f4ddb3;
        border-radius: 18px;
        padding: 16px 18px;
        margin: 8px 0 16px;
        color: #475569;
        line-height: 1.55;
    }
    </style>
    """, unsafe_allow_html=True)

    case_id, client_id = get_case_selector("card_os_overview_case")
    if not case_id:
        return

    card_df = fetch_df("""
        SELECT card_id, card_type, card_status, related_table, related_id, related_label,
               concern, client_words, current_state,
               unknown_items, related_people_places, next_check_items, memo, updated_at
        FROM consultation_cards
        WHERE case_id=%(case_id)s
        ORDER BY
            CASE card_status
                WHEN '気になる' THEN 1
                WHEN '検討中' THEN 2
                WHEN '保留' THEN 3
                WHEN '整理済' THEN 4
                ELSE 9
            END,
            updated_at DESC NULLS LAST,
            created_at DESC
    """, {"case_id": case_id})

    pending_df = fetch_df("""
        SELECT pending_id, theme, status, next_check_date, reason, caution, related_people, memo, updated_at
        FROM pending_items
        WHERE case_id=%(case_id)s
        ORDER BY
            CASE status
                WHEN '家族確認待ち' THEN 1
                WHEN '専門家確認待ち' THEN 2
                WHEN '次回確認' THEN 3
                WHEN '保留中' THEN 4
                WHEN '整理済' THEN 5
                WHEN '終了' THEN 6
                ELSE 9
            END,
            next_check_date ASC NULLS LAST,
            updated_at DESC NULLS LAST
    """, {"case_id": case_id})

    summary_df = fetch_df("""
        SELECT created_at, summary_type, summary_text
        FROM ai_summaries
        WHERE case_id=%(case_id)s
        ORDER BY created_at DESC
        LIMIT 3
    """, {"case_id": case_id})

    urgent_cards = 0 if card_df.empty else len(card_df[card_df["card_status"].astype(str).isin(["気になる", "検討中"])])
    active_pending = 0 if pending_df.empty else len(pending_df[~pending_df["status"].astype(str).isin(["整理済", "終了"])])
    waiting_count = 0 if pending_df.empty else len(pending_df[pending_df["status"].astype(str).isin(["家族確認待ち", "専門家確認待ち", "次回確認"])])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("見えているカード", len(card_df))
    c2.metric("要整理カード", urgent_cards)
    c3.metric("保留中の事項", active_pending)
    c4.metric("確認待ち", waiting_count)

    st.markdown("""
    <div class="ny-os-note">
    🐾 この画面は、相談者の悩みを“処理する案件”ではなく、机の上に並べたカードとして眺めるための画面です。<br>
    🟥 気になる　🟧 確認待ち　🟨 検討・保留　🟩 整理済 の目安で確認します。
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### いま見えているカード")
    if card_df.empty:
        st.info("カードはまだ登録されていません。『Ver2.0｜カード整理』から登録してください。")
    else:
        for card_type in NYANTOMO_CARD_TYPES:
            group = card_df[card_df["card_type"] == card_type]
            if group.empty:
                continue
            st.markdown(f"#### {card_type}")
            cols = st.columns(2)
            for i, (_, row) in enumerate(group.iterrows()):
                icon = ny_card_status_icon(row.get("card_status", ""))
                headline = ny_pick_summary(row.get("concern", ""), row.get("current_state", ""), row.get("client_words", ""))
                detail_parts = []
                related_label = normalize_text(row.get("related_label", ""))
                next_check = normalize_text(row.get("next_check_items", ""))
                unknown = normalize_text(row.get("unknown_items", ""))
                if related_label:
                    detail_parts.append(f"基本情報：{related_label}")
                if next_check:
                    detail_parts.append(f"次回確認：{next_check}")
                elif unknown:
                    detail_parts.append(f"未確認：{unknown}")
                detail = "／".join(detail_parts)
                footer = f"更新：{normalize_text(row.get('updated_at', ''))}"
                with cols[i % 2]:
                    render_nyantomo_card_tile(icon, card_type.replace("カード", ""), headline, row.get("card_status", ""), detail, footer)

    st.markdown("---")
    st.markdown("### 保留事項カード")
    if pending_df.empty:
        st.info("保留事項はまだ登録されていません。『Ver2.0｜保留事項管理』から登録してください。")
    else:
        cols = st.columns(2)
        for i, (_, row) in enumerate(pending_df.iterrows()):
            icon = ny_pending_status_icon(row.get("status", ""))
            headline = ny_pick_summary(row.get("theme", ""), row.get("reason", ""))
            detail_parts = []
            if normalize_text(row.get("next_check_date", "")):
                detail_parts.append(f"次回確認日：{normalize_text(row.get('next_check_date', ''))}")
            if normalize_text(row.get("related_people", "")):
                detail_parts.append(f"関係者：{normalize_text(row.get('related_people', ''))}")
            if normalize_text(row.get("caution", "")):
                detail_parts.append(f"注意：{normalize_text(row.get('caution', ''))}")
            detail = "／".join(detail_parts)
            footer = f"更新：{normalize_text(row.get('updated_at', ''))}"
            with cols[i % 2]:
                render_nyantomo_card_tile(icon, "保留事項", headline, row.get("status", ""), detail, footer)

    st.markdown("---")
    with st.expander("表形式で確認する", expanded=False):
        st.markdown("#### カード整理データ")
        if card_df.empty:
            st.info("カードはありません。")
        else:
            st.dataframe(card_df, use_container_width=True, hide_index=True, height=260)

        st.markdown("#### 保留事項データ")
        if pending_df.empty:
            st.info("保留事項はありません。")
        else:
            st.dataframe(pending_df, use_container_width=True, hide_index=True, height=260)

    st.markdown("---")
    st.markdown("### 最近のAI要約")
    if summary_df.empty:
        st.info("AI要約はまだ保存されていません。")
    else:
        for _, row in summary_df.iterrows():
            with st.expander(f"{row.get('created_at', '')}｜{row.get('summary_type', '')}", expanded=False):
                st.write(row.get("summary_text", ""))


def render_ai_summary():
    st.subheader("カード整理AI")
    st.caption("相談記録を単に要約するのではなく、相談者の悩み・基本情報カード・保留事項を読み取り、カードとして並べ直します。")

    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
        return

    selected_label = st.selectbox("対象案件", case_labels, key="ai_case_select")
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)

    source_text = build_case_ai_source(case_id)

    st.info("出力の中心は「今回見えているテーマ」「今すぐ決めなくてよいこと」「次回確認」です。AIは判断者ではなく、カード整理係として使います。")

    preview_cols = st.columns(3)
    with preview_cols[0]:
        card_count = fetch_one("SELECT COUNT(*) AS count FROM consultation_cards WHERE case_id=%(case_id)s", {"case_id": case_id})
        st.metric("判断カード", int(card_count.get("count", 0)) if card_count else 0)
    with preview_cols[1]:
        pending_count = fetch_one("SELECT COUNT(*) AS count FROM pending_items WHERE case_id=%(case_id)s", {"case_id": case_id})
        st.metric("保留事項", int(pending_count.get("count", 0)) if pending_count else 0)
    with preview_cols[2]:
        summary_count = fetch_one("SELECT COUNT(*) AS count FROM ai_summaries WHERE case_id=%(case_id)s", {"case_id": case_id})
        st.metric("保存済み整理", int(summary_count.get("count", 0)) if summary_count else 0)

    with st.expander("AIに渡す元データを確認", expanded=False):
        st.text_area("元データ", source_text, height=320)

    summary_type = st.selectbox(
        "整理種別",
        [
            "カード整理AI｜初回整理",
            "カード整理AI｜次回確認",
            "カード整理AI｜保留事項整理",
            "カード整理AI｜家族共有前整理",
            "カード整理AI｜内部メモ",
            "カード整理AI｜相談者向けやわらか要約",
            "カード整理AI｜終了時整理",
            "その他",
        ],
    )
    extra_instruction = st.text_area(
        "追加指示（任意）",
        placeholder="例：今回は『今すぐ決めなくてよいこと』と『次回確認』を短く整理してください。",
    )

    with st.expander("カード整理AIの出力イメージ", expanded=False):
        st.markdown("""
```text
## 1. 今回見えているテーマ
- 猫の将来
- 空き家管理
- 家族との温度差

## 3. 今すぐ決めなくてよいこと
- 売却時期
- 後見制度を使うかどうか

## 5. 次回確認
- 兄との話し合い状況
- 猫の預け先候補
- 鍵の所在
```
""")

    col1, col2 = st.columns([1, 1])
    with col1:
        run_ai = st.button("カード整理AIを作成して保存", disabled=not can_write())
    with col2:
        st.caption(f"使用モデル：{get_openai_model()} / APIキー：{'設定あり' if get_openai_api_key() else '未設定'}")

    if run_ai:
        if not source_text.strip():
            st.error("整理対象のデータがありません。")
        else:
            prompt = build_ai_prompt(summary_type, source_text)
            if extra_instruction.strip():
                prompt += f"\n\n追加指示：{extra_instruction.strip()}"
            try:
                with st.spinner("カード整理AIを作成しています..."):
                    summary_text, model = call_openai_summary(prompt)
                    save_ai_summary(case_id, client_id, summary_type, source_text, summary_text, extra_instruction, model)
                st.success("カード整理AIを保存しました。")
                st.rerun()
            except Exception as e:
                st.error("カード整理AIの作成に失敗しました。")
                st.exception(e)

    st.markdown("---")
    st.markdown("### 保存済みカード整理AI")
    df = fetch_df("""
        SELECT summary_id, created_at, summary_type, summary_text, memo
        FROM ai_summaries
        WHERE case_id=%(case_id)s
        ORDER BY created_at DESC
    """, {"case_id": case_id})

    if df.empty:
        st.info("保存済みのカード整理AIはありません。")
    else:
        for _, row in df.iterrows():
            with st.expander(f"{row.get('created_at', '')}｜{row.get('summary_type', '')}", expanded=False):
                st.markdown(row.get("summary_text", ""))
                if normalize_text(row.get("memo", "")):
                    st.caption(f"追加指示：{row.get('memo', '')}")

        st.markdown("#### 一覧")
        st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty and can_write():
        selected = st.selectbox("削除するカード整理AI ID", df["summary_id"].tolist())
        delete_confirm = st.checkbox("このカード整理AIを削除することを確認しました。")
        if st.button("選択したカード整理AIを削除"):
            if not delete_confirm:
                st.error("削除するには確認チェックを入れてください。")
            else:
                execute("DELETE FROM ai_summaries WHERE summary_id=%(id)s", {"id": selected})
                log_action("delete", "ai_summaries", selected, "カード整理AI削除")
                st.success("削除しました。")
                st.rerun()

def render_backup():
    st.subheader("バックアップ・出力")
    st.caption("CSV ZIPの手動出力に加え、アプリ起動・画面操作時の自動バックアップを行います。")

    st.markdown("### 自動バックアップ設定")
    try:
        hours = int(get_secret_value("AUTO_BACKUP_HOURS", DEFAULT_AUTO_BACKUP_HOURS))
    except Exception:
        hours = DEFAULT_AUTO_BACKUP_HOURS
    try:
        keep = int(get_secret_value("AUTO_BACKUP_KEEP", DEFAULT_BACKUP_KEEP))
    except Exception:
        keep = DEFAULT_BACKUP_KEEP

    c1, c2, c3 = st.columns(3)
    c1.metric("自動バックアップ間隔", f"{hours}時間")
    c2.metric("保存件数", f"{keep}件")
    c3.metric("保存先", str(BACKUP_DIR))

    st.info("Streamlit Cloudでは常時バックグラウンド処理ではなく、アプリが開かれた時・操作された時に前回時刻を確認して自動作成します。")

    st.markdown("---")
    st.markdown("### 手動バックアップ")

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("今すぐバックアップを保存", disabled=not can_write()):
            try:
                path = save_backup_file("manual", "画面から手動作成")
                cleanup_old_backups(keep)
                st.success(f"バックアップを保存しました：{path.name}")
                st.rerun()
            except Exception as e:
                st.error("バックアップ作成に失敗しました。")
                st.exception(e)

    with col2:
        try:
            zip_bytes, _ = build_csv_zip_bytes()
            st.download_button(
                "全テーブルCSV ZIPを直接ダウンロード",
                zip_bytes,
                file_name=f"nyantomo_backup_direct_{today_text()}.zip",
                mime="application/zip"
            )
        except Exception as e:
            st.error("CSV ZIP作成に失敗しました。")
            st.exception(e)

    st.markdown("---")
    st.markdown("### 保存済みバックアップ")
    files = sorted(BACKUP_DIR.glob("nyantomo_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        st.info("保存済みバックアップはまだありません。")
    else:
        rows = []
        for p in files:
            rows.append({
                "ファイル名": p.name,
                "サイズKB": round(p.stat().st_size / 1024, 1),
                "更新日時": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        file_df = pd.DataFrame(rows)
        st.dataframe(file_df, use_container_width=True, hide_index=True)
        selected_file = st.selectbox("ダウンロードするバックアップ", [p.name for p in files])
        selected_path = BACKUP_DIR / selected_file
        if selected_path.exists():
            st.download_button(
                "選択したバックアップをダウンロード",
                selected_path.read_bytes(),
                file_name=selected_path.name,
                mime="application/zip"
            )

    st.markdown("---")
    st.markdown("### 自動バックアップログ")
    try:
        logs = fetch_df("SELECT * FROM nyantomo_backup_logs ORDER BY created_at DESC LIMIT 100")
        st.dataframe(logs, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"自動バックアップログを表示できません：{e}")

    st.markdown("---")
    st.markdown("### Excel出力")
    try:
        import openpyxl  # noqa: F401
        data = {}
        for table, label in get_backup_tables():
            try:
                data[label] = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
            except Exception as e:
                data[label] = pd.DataFrame([{"error": str(e)}])
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            for label, df in data.items():
                df.to_excel(writer, index=False, sheet_name=str(label)[:31])
        st.download_button(
            "全テーブルExcelダウンロード",
            excel_buffer.getvalue(),
            file_name=f"nyantomo_backup_{today_text()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except ModuleNotFoundError:
        st.warning("openpyxl が入っていないため、Excel出力は使えません。CSV ZIPバックアップは利用できます。")
    except Exception as e:
        st.error("Excel出力でエラーが発生しました。CSV ZIPバックアップをご利用ください。")
        st.exception(e)



# ============================================================
# 後見モード Ver1.0
# ============================================================

GUARDIAN_CARD_TYPES = {
    "本人希望カード": [
        ("field_1", "好きなこと", "area"),
        ("field_2", "嫌いなこと", "area"),
        ("field_3", "大切にしていること", "area"),
        ("field_4", "生活歴", "area"),
        ("field_5", "宗教・価値観", "text"),
        ("field_6", "延命治療意向", "area"),
        ("field_7", "施設希望", "area"),
        ("field_8", "住まい希望", "area"),
        ("field_9", "ペット希望", "area"),
        ("field_10", "本人の言葉", "area"),
    ],
    "家族カード": [
        ("field_1", "氏名", "text"),
        ("field_2", "続柄", "text"),
        ("field_3", "連絡先", "text"),
        ("field_4", "協力度", "text"),
        ("field_5", "温度感", "text"),
        ("field_6", "面会頻度", "text"),
        ("field_7", "注意事項", "area"),
    ],
    "医療カード": [
        ("field_1", "主治医", "text"),
        ("field_2", "病院", "text"),
        ("field_3", "診断名", "area"),
        ("field_4", "服薬", "area"),
        ("field_5", "訪問看護", "text"),
        ("field_6", "救急搬送先", "text"),
        ("field_7", "ACP状況", "area"),
    ],
    "介護カード": [
        ("field_1", "ケアマネ", "text"),
        ("field_2", "事業所", "text"),
        ("field_3", "ヘルパー", "text"),
        ("field_4", "デイサービス", "text"),
        ("field_5", "ショートステイ", "text"),
        ("field_6", "施設担当者", "text"),
        ("field_7", "介護メモ", "area"),
    ],
    "財産カード": [
        ("field_1", "年金", "area"),
        ("field_2", "預金", "area"),
        ("field_3", "保険", "area"),
        ("field_4", "不動産", "area"),
        ("field_5", "負債", "area"),
        ("field_6", "定期支払", "area"),
        ("field_7", "公共料金", "area"),
        ("field_8", "口座管理", "area"),
    ],
    "住まいカード": [
        ("field_1", "自宅", "area"),
        ("field_2", "施設", "area"),
        ("field_3", "空き家", "area"),
        ("field_4", "賃貸", "area"),
        ("field_5", "管理状況", "area"),
        ("field_6", "鍵管理", "area"),
    ],
    "ペットカード": [
        ("field_1", "猫情報", "area"),
        ("field_2", "動物病院", "text"),
        ("field_3", "預かり候補", "area"),
        ("field_4", "緊急時対応", "area"),
        ("field_5", "飼養継続計画", "area"),
    ],
    "支援者カード": [
        ("field_1", "区分", "text"),
        ("field_2", "氏名・機関名", "text"),
        ("field_3", "連絡先", "text"),
        ("field_4", "役割", "area"),
        ("field_5", "温度感", "text"),
        ("field_6", "連携状況", "text"),
        ("field_7", "注意事項", "area"),
    ],
    "判断保留カード": [
        ("field_1", "まだ決めないこと", "area"),
        ("field_2", "判断時期", "text"),
        ("field_3", "保留する理由", "area"),
        ("field_4", "見守り方", "area"),
        ("field_5", "急がせないための注意点", "area"),
    ],
    "家庭裁判所対応カード": [
        ("field_1", "報告書作成メモ", "area"),
        ("field_2", "収支状況", "area"),
        ("field_3", "財産変動", "area"),
        ("field_4", "重要事項", "area"),
        ("field_5", "年次報告管理", "area"),
        ("field_6", "次回提出期限", "text"),
    ],
}

RESOURCE_STATUS_OPTIONS = ["◎ 安定", "○ 利用中", "△ 要確認", "－ 未接続", "＋ 過剰気味", "□ 不明"]
RESOURCE_STATUS_LEGACY_MAP = {
    "安定": "◎ 安定",
    "利用中": "○ 利用中",
    "要確認": "△ 要確認",
    "未接続": "－ 未接続",
    "過剰気味": "＋ 過剰気味",
    "不明": "□ 不明",
}
SUPPORT_CATEGORY_OPTIONS = [
    "包括", "ケアマネ", "主治医", "宅建士", "司法書士", "動物病院",
    "訪問看護", "ヘルパー", "デイサービス", "ショートステイ",
    "施設担当者", "社協", "行政", "弁護士", "税理士", "行政書士",
    "不動産会社", "管理会社", "猫ボランティア", "家族", "親族", "その他"
]

def resource_display(value):
    value = normalize_text(value)
    if not value:
        return "□ 不明"
    if value in RESOURCE_STATUS_OPTIONS:
        return value
    return RESOURCE_STATUS_LEGACY_MAP.get(value, value)

def resource_symbol(value):
    return resource_display(value).split(" ")[0]

def resource_text(value):
    parts = resource_display(value).split(" ", 1)
    return parts[1] if len(parts) > 1 else resource_display(value)
CONFIDENTIALITY_OPTIONS = ["通常", "注意", "高", "最重要"]
GUARDIAN_STATUS_OPTIONS = ["準備中", "受任中", "見守り中", "要確認", "終了"]
EMERGENCY_OPTIONS = ["低", "中", "高", "緊急"]


def get_guardian_wards():
    return fetch_df("""
        SELECT * FROM guardian_wards
        ORDER BY COALESCE(next_check_date, DATE '2999-12-31') ASC, updated_at DESC NULLS LAST, created_at DESC
    """)


def get_guardian_ward_options():
    df = get_guardian_wards()
    mapping, labels = {}, []
    for _, r in df.iterrows():
        label = f"{r['name']}｜{r.get('guardian_type','')}｜{r.get('status','')}｜{r['ward_id']}"
        labels.append(label)
        mapping[label] = r["ward_id"]
    return mapping, labels


def render_guardian_dashboard():
    st.subheader("後見モード ダッシュボード")
    st.caption("本人・家族・医療・介護・財産・住まい・猫・専門職を、抱え込まずに見える化します。")

    counts = fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM guardian_wards) AS wards_count,
            (SELECT COUNT(*) FROM guardian_wards WHERE COALESCE(status,'') <> '終了') AS active_count,
            (SELECT COUNT(*) FROM guardian_cards) AS cards_count,
            (SELECT COUNT(*) FROM guardian_wards WHERE next_check_date IS NOT NULL AND next_check_date <= CURRENT_DATE + INTERVAL '7 days') AS need_check_count
    """)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("被後見人", int(counts.get("wards_count", 0)))
    c2.metric("進行中", int(counts.get("active_count", 0)))
    c3.metric("カード数", int(counts.get("cards_count", 0)))
    c4.metric("7日以内確認", int(counts.get("need_check_count", 0)))

    st.markdown("---")
    wards = get_guardian_wards()
    safe_df_display(wards, "被後見人はまだ登録されていません。", ["ward_id", "name", "guardian_type", "status", "emergency_level", "next_check_date", "updated_at"], height=260)

    st.markdown("### リソース地図一覧")
    maps = fetch_df("""
        SELECT w.name, r.family_status, r.medical_status, r.care_status, r.housing_status, r.asset_status,
               r.pet_status, r.professional_status, r.overall_status, r.next_check, r.updated_at
        FROM guardian_resource_map r
        JOIN guardian_wards w ON r.ward_id = w.ward_id
        ORDER BY r.updated_at DESC NULLS LAST, r.created_at DESC
        LIMIT 50
    """)
    if not maps.empty:
        for col in ["family_status", "medical_status", "care_status", "housing_status", "asset_status", "pet_status", "professional_status"]:
            maps[col] = maps[col].apply(resource_display)
    safe_df_display(maps, "リソース地図はまだ登録されていません。", height=260)


def render_guardian_wards():
    st.subheader("被後見人 登録・検索・更新")
    with st.form("guardian_ward_create"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("氏名")
            birth_date = st.date_input("生年月日", value=None)
            address = st.text_area("住所")
            phone = st.text_input("電話番号")
            facility_name = st.text_input("施設名")
            guardian_type = st.selectbox("後見種別", ["未選択", "成年後見", "保佐", "補助", "任意後見", "その他"])
        with c2:
            petitioner = st.text_input("申立人")
            court_name = st.text_input("担当裁判所")
            guardian_name = st.text_input("担当後見人")
            start_date = st.date_input("担当開始日", value=None)
            status = st.selectbox("状態", GUARDIAN_STATUS_OPTIONS)
            emergency_level = st.selectbox("緊急度", EMERGENCY_OPTIONS)
            next_check_date = st.date_input("次回確認日", value=None)
        memo = st.text_area("備考")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        if not name.strip():
            st.error("氏名を入力してください。")
        else:
            ward_id = make_id("ward")
            execute("""
                INSERT INTO guardian_wards
                (ward_id, created_at, updated_at, created_by, confidentiality_level, status, name, birth_date, address, phone,
                 facility_name, guardian_type, petitioner, court_name, guardian_name, start_date, emergency_level, next_check_date, memo)
                VALUES (%(ward_id)s, %(created_at)s, %(updated_at)s, %(created_by)s, %(confidentiality_level)s, %(status)s, %(name)s, %(birth_date)s, %(address)s, %(phone)s,
                 %(facility_name)s, %(guardian_type)s, %(petitioner)s, %(court_name)s, %(guardian_name)s, %(start_date)s, %(emergency_level)s, %(next_check_date)s, %(memo)s)
            """, {
                "ward_id": ward_id, "created_at": now_text(), "updated_at": now_text(), "created_by": st.session_state.get("login_id", ""),
                "confidentiality_level": "高", "status": status, "name": name.strip(), "birth_date": birth_date, "address": address,
                "phone": phone, "facility_name": facility_name, "guardian_type": guardian_type, "petitioner": petitioner,
                "court_name": court_name, "guardian_name": guardian_name, "start_date": start_date, "emergency_level": emergency_level,
                "next_check_date": next_check_date, "memo": memo,
            })
            log_action("create", "guardian_wards", ward_id, "被後見人登録")
            st.success("被後見人を登録しました。")
            st.rerun()

    st.markdown("---")
    keyword = st.text_input("検索語", key="guardian_ward_search")
    df = get_guardian_wards()
    if keyword and not df.empty:
        df = df[df.astype(str).apply(lambda row: row.str.contains(keyword, case=False, na=False).any(), axis=1)]
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty and can_write():
        selected = st.selectbox("更新する被後見人ID", df["ward_id"].tolist())
        row = df[df["ward_id"] == selected].iloc[0]
        with st.form("guardian_ward_edit"):
            new_status = st.selectbox("状態", GUARDIAN_STATUS_OPTIONS, index=GUARDIAN_STATUS_OPTIONS.index(row["status"]) if row["status"] in GUARDIAN_STATUS_OPTIONS else 0)
            new_emergency = st.selectbox("緊急度", EMERGENCY_OPTIONS, index=EMERGENCY_OPTIONS.index(row["emergency_level"]) if row["emergency_level"] in EMERGENCY_OPTIONS else 0)
            new_next = st.date_input("次回確認日", date_or_none(row["next_check_date"]))
            new_memo = st.text_area("備考", normalize_text(row["memo"]))
            update = st.form_submit_button("更新する")
        if update:
            execute("""
                UPDATE guardian_wards
                SET updated_at=%(updated_at)s, status=%(status)s, emergency_level=%(emergency_level)s, next_check_date=%(next_check_date)s, memo=%(memo)s
                WHERE ward_id=%(ward_id)s
            """, {"updated_at": now_text(), "status": new_status, "emergency_level": new_emergency, "next_check_date": new_next, "memo": new_memo, "ward_id": selected})
            log_action("update", "guardian_wards", selected, "被後見人更新")
            st.success("更新しました。")
            st.rerun()


def render_guardian_card(card_type):
    st.subheader(card_type)
    ward_map, ward_labels = get_guardian_ward_options()
    if not ward_labels:
        st.warning("先に被後見人を登録してください。")
        return
    selected_label = st.selectbox("対象被後見人", ward_labels, key=f"{card_type}_ward")
    ward_id = ward_map[selected_label]
    fields = GUARDIAN_CARD_TYPES[card_type]

    with st.form(f"guardian_card_create_{card_type}"):
        confidentiality_level = st.selectbox("機密レベル", CONFIDENTIALITY_OPTIONS, index=1)
        status = st.selectbox("ステータス", ["未確認", "確認中", "安定", "要確認", "終了"])
        title = st.text_input("タイトル", value=card_type)
        values = {}
        for key, label, kind in fields:
            if kind == "area":
                values[key] = st.text_area(label)
            else:
                values[key] = st.text_input(label)
        memo = st.text_area("備考")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        card_id = make_id("gcard")
        params = {
            "card_id": card_id, "ward_id": ward_id, "created_at": now_text(), "updated_at": now_text(),
            "updated_by": st.session_state.get("login_id", ""), "card_type": card_type,
            "confidentiality_level": confidentiality_level, "status": status, "related_card_id": "", "title": title,
            "memo": memo,
        }
        for i in range(1, 11):
            params[f"field_{i}"] = values.get(f"field_{i}", "")
        execute("""
            INSERT INTO guardian_cards
            (card_id, ward_id, created_at, updated_at, updated_by, card_type, confidentiality_level, status, related_card_id, title,
             field_1, field_2, field_3, field_4, field_5, field_6, field_7, field_8, field_9, field_10, memo)
            VALUES
            (%(card_id)s, %(ward_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s, %(card_type)s, %(confidentiality_level)s, %(status)s, %(related_card_id)s, %(title)s,
             %(field_1)s, %(field_2)s, %(field_3)s, %(field_4)s, %(field_5)s, %(field_6)s, %(field_7)s, %(field_8)s, %(field_9)s, %(field_10)s, %(memo)s)
        """, params)
        log_action("create", "guardian_cards", card_id, f"{card_type}登録")
        st.success("登録しました。")
        st.rerun()

    st.markdown("---")
    df = fetch_df("SELECT * FROM guardian_cards WHERE ward_id=%(ward_id)s AND card_type=%(card_type)s ORDER BY updated_at DESC NULLS LAST, created_at DESC", {"ward_id": ward_id, "card_type": card_type})
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_guardian_resource_map():
    st.subheader("リソース地図")
    st.caption("不足だけでなく、十分な支え・今は足さなくてよい支援も見える化します。")
    ward_map, ward_labels = get_guardian_ward_options()
    if not ward_labels:
        st.warning("先に被後見人を登録してください。")
        return
    selected_label = st.selectbox("対象被後見人", ward_labels, key="guardian_resource_ward")
    ward_id = ward_map[selected_label]

    with st.form("guardian_resource_create"):
        c1, c2, c3 = st.columns(3)
        with c1:
            family_status = st.selectbox("家族", RESOURCE_STATUS_OPTIONS)
            medical_status = st.selectbox("医療", RESOURCE_STATUS_OPTIONS)
            care_status = st.selectbox("介護", RESOURCE_STATUS_OPTIONS)
        with c2:
            housing_status = st.selectbox("住まい", RESOURCE_STATUS_OPTIONS)
            asset_status = st.selectbox("財産", RESOURCE_STATUS_OPTIONS)
            pet_status = st.selectbox("猫・ペット", RESOURCE_STATUS_OPTIONS)
        with c3:
            professional_status = st.selectbox("専門職", RESOURCE_STATUS_OPTIONS)
            overall_status = st.selectbox("総合状態", ["安定", "おおむね安定", "要確認", "不安定", "緊急"])
            confidentiality_level = st.selectbox("機密レベル", CONFIDENTIALITY_OPTIONS, index=1)
        enough_memo = st.text_area("すでに使えるリソース・十分な支え")
        shortage_memo = st.text_area("不足または将来確認したいリソース")
        do_not_add_memo = st.text_area("今は増やさなくてよい支援・抱え込まないための注意")
        next_check = st.text_area("次回確認")
        memo = st.text_area("備考")
        ok = st.form_submit_button("リソース地図を保存", disabled=not can_write())
    if ok:
        map_id = make_id("gmap")
        execute("""
            INSERT INTO guardian_resource_map
            (map_id, ward_id, created_at, updated_at, updated_by, confidentiality_level, family_status, medical_status, care_status,
             housing_status, asset_status, pet_status, professional_status, overall_status, shortage_memo, enough_memo, do_not_add_memo, next_check, memo)
            VALUES
            (%(map_id)s, %(ward_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s, %(confidentiality_level)s, %(family_status)s, %(medical_status)s, %(care_status)s,
             %(housing_status)s, %(asset_status)s, %(pet_status)s, %(professional_status)s, %(overall_status)s, %(shortage_memo)s, %(enough_memo)s, %(do_not_add_memo)s, %(next_check)s, %(memo)s)
        """, {
            "map_id": map_id, "ward_id": ward_id, "created_at": now_text(), "updated_at": now_text(), "updated_by": st.session_state.get("login_id", ""),
            "confidentiality_level": confidentiality_level, "family_status": family_status, "medical_status": medical_status, "care_status": care_status,
            "housing_status": housing_status, "asset_status": asset_status, "pet_status": pet_status, "professional_status": professional_status,
            "overall_status": overall_status, "shortage_memo": shortage_memo, "enough_memo": enough_memo, "do_not_add_memo": do_not_add_memo,
            "next_check": next_check, "memo": memo,
        })
        log_action("create", "guardian_resource_map", map_id, "リソース地図登録")
        st.success("保存しました。")
        st.rerun()

    st.markdown("---")
    df = fetch_df("SELECT * FROM guardian_resource_map WHERE ward_id=%(ward_id)s ORDER BY updated_at DESC NULLS LAST, created_at DESC", {"ward_id": ward_id})
    if not df.empty:
        latest = df.iloc[0]
        st.markdown("### 最新リソース地図")
        cols = st.columns(7)
        items = [
            ("家族", latest.get("family_status", "")),
            ("医療", latest.get("medical_status", "")),
            ("介護", latest.get("care_status", "")),
            ("住まい", latest.get("housing_status", "")),
            ("財産", latest.get("asset_status", "")),
            ("猫", latest.get("pet_status", "")),
            ("専門職", latest.get("professional_status", "")),
        ]
        for col, (label, value) in zip(cols, items):
            col.metric(label, resource_symbol(value), help=resource_text(value))
        st.info(f"総合状態：{normalize_text(latest.get('overall_status', '')) or '未設定'}")

        show_df = df.copy()
        for col in ["family_status", "medical_status", "care_status", "housing_status", "asset_status", "pet_status", "professional_status"]:
            show_df[col] = show_df[col].apply(resource_display)
        st.markdown("### 履歴")
        st.dataframe(show_df, use_container_width=True, hide_index=True)
    else:
        st.info("リソース地図はまだ登録されていません。")


def render_guardian_interviews():
    st.subheader("面談記録")
    ward_map, ward_labels = get_guardian_ward_options()
    if not ward_labels:
        st.warning("先に被後見人を登録してください。")
        return
    selected_label = st.selectbox("対象被後見人", ward_labels, key="guardian_interview_ward")
    ward_id = ward_map[selected_label]
    with st.form("guardian_interview_create"):
        interview_date = st.date_input("日時", date.today())
        place = st.text_input("訪問先")
        content = st.text_area("内容")
        ward_words = st.text_area("本人発言")
        family_words = st.text_area("家族発言")
        action_taken = st.text_area("対応内容")
        next_check = st.text_area("次回確認事項")
        memo = st.text_area("備考")
        ok = st.form_submit_button("登録する", disabled=not can_write())
    if ok:
        log_id = make_id("glog")
        execute("""
            INSERT INTO guardian_interview_logs
            (log_id, ward_id, created_at, updated_at, updated_by, confidentiality_level, interview_date, place, content, ward_words, family_words, action_taken, next_check, memo)
            VALUES (%(log_id)s, %(ward_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s, %(confidentiality_level)s, %(interview_date)s, %(place)s, %(content)s, %(ward_words)s, %(family_words)s, %(action_taken)s, %(next_check)s, %(memo)s)
        """, {"log_id": log_id, "ward_id": ward_id, "created_at": now_text(), "updated_at": now_text(), "updated_by": st.session_state.get("login_id", ""), "confidentiality_level": "高", "interview_date": interview_date, "place": place, "content": content, "ward_words": ward_words, "family_words": family_words, "action_taken": action_taken, "next_check": next_check, "memo": memo})
        log_action("create", "guardian_interview_logs", log_id, "後見面談記録")
        st.success("登録しました。")
        st.rerun()
    df = fetch_df("SELECT * FROM guardian_interview_logs WHERE ward_id=%(ward_id)s ORDER BY interview_date DESC NULLS LAST, created_at DESC", {"ward_id": ward_id})
    st.dataframe(df, use_container_width=True, hide_index=True)


def build_guardian_ai_source(ward_id):
    ward = fetch_one("SELECT * FROM guardian_wards WHERE ward_id=%(ward_id)s", {"ward_id": ward_id})
    if not ward:
        return ""
    text = ["【被後見人】"]
    for k, v in ward.items():
        text.append(f"{k}:{normalize_text(v)}")
    cards = fetch_df("SELECT * FROM guardian_cards WHERE ward_id=%(ward_id)s ORDER BY updated_at DESC NULLS LAST, created_at DESC", {"ward_id": ward_id})
    text.append("\n【カード】")
    if cards.empty:
        text.append("未登録")
    else:
        for _, r in cards.iterrows():
            text.append(f"- {r.get('card_type','')}｜{r.get('title','')}｜{r.get('status','')}｜{r.get('field_1','')}｜{r.get('field_2','')}｜{r.get('memo','')}")
    maps = fetch_df("SELECT * FROM guardian_resource_map WHERE ward_id=%(ward_id)s ORDER BY updated_at DESC NULLS LAST LIMIT 3", {"ward_id": ward_id})
    text.append("\n【リソース地図】")
    text.append(maps.to_string(index=False) if not maps.empty else "未登録")
    logs = fetch_df("SELECT * FROM guardian_interview_logs WHERE ward_id=%(ward_id)s ORDER BY interview_date DESC NULLS LAST, created_at DESC LIMIT 10", {"ward_id": ward_id})
    text.append("\n【面談記録】")
    text.append(logs.to_string(index=False) if not logs.empty else "未登録")
    return "\n".join(text)


def build_guardian_ai_prompt(support_type, source_text):
    return f"""
あなたは後見人の内部記録整理係です。
判断を代行せず、本人の意思・生活・支援関係を整理してください。
法的判断、医療判断、財産処分の断定、専門職への越権助言はしないでください。

出力形式：
1. 事実として確認できること
2. 未確認・不足している情報
3. 本人の意思・生活上大切にしたい点
4. 現在使えるリソース
5. 不足または将来確認したいリソース
6. 今は増やさなくてよい支援・後見人が抱え込まないための注意
7. 次回確認事項
8. 家庭裁判所報告に向けた内部メモ

支援種別：{support_type}
---
{source_text}
""".strip()




def build_guardian_card_ai_prompt(summary_type, source_text):
    """後見モード用：カード整理AIプロンプト。
    後見カード・面談記録・リソース地図を、本人中心のカード配置として整理する。
    """
    return f"""
あなたは『にゃんとも 住まいと猫の相談室』の後見モード用「カード整理AI」です。
役割は、後見記録を一般的に要約することではありません。
本人希望カード、家族カード、医療カード、介護カード、財産カード、住まいカード、ペットカード、支援者カード、判断保留カード、家庭裁判所対応カード、面談記録、リソース地図を読み取り、
「いま机の上に並んでいる後見カード」を見える化してください。

最重要ルール：
- 後見人・行政書士の判断を代行しない
- 法的判断、医療判断、財産処分、不動産処分、税務判断を断定しない
- 本人の意思を決めつけない
- 家族・支援者の善悪を決めつけない
- 支援を増やすことを当然の結論にしない
- 後見人が抱え込む方向へ誘導しない
- 家庭裁判所提出用の断定文ではなく、内部整理メモとして書く
- 事実、未確認、保留、次回確認を分ける
- 「本人の生活の安定」と「後見人が抱え込まない境界線」を両方守る

出力形式は必ず以下の見出しで作成してください。

## 1. 今回見えているテーマ
- 例：本人希望
- 例：家族との温度差
- 例：医療・介護連携
- 例：財産管理
- 例：住まい・施設
- 例：ペットの将来
- 例：家庭裁判所報告

## 2. いま机の上に並んでいる後見カード
カードごとに、次の形で整理してください。
- 🐾 カード種別：
- 現在見えていること：
- 本人の言葉・希望：
- 家族・支援者の関係：
- 未確認事項：
- 次回確認：

## 3. 今すぐ決めなくてよいこと
- 例：施設移動の最終判断
- 例：財産処分の方向性
- 例：家族との関係整理の結論
- 例：ペットの最終的な引き取り先
※ただし、緊急性がある可能性があるものは「保留ではなく確認が必要」と表現してください。

## 4. 少し整理した方がよいこと
- 例：本人の希望の原文
- 例：医療・介護の連絡先
- 例：家族の温度感
- 例：収支・定期支払
- 例：住まい・施設の安全面
- 例：家庭裁判所報告に必要な事実

## 5. 次回確認
次回の面談・連絡・記録確認で確認するとよいことを3〜7個に絞ってください。

## 6. つなぐ可能性がある専門職・支援者
- 主治医、ケアマネ、施設担当者、包括、社協、弁護士、司法書士、税理士、動物病院、親族など
- 「必要」と断定せず、「可能性」として整理してください。

## 7. 後見人として関われる範囲
- 記録、連絡調整、本人意思の確認、財産管理の事実整理、家庭裁判所報告準備など
- 断定や抱え込みではなく、確認・整理・報告・連携の範囲で書いてください。

## 8. 後見人が抱え込まない方がよい範囲
- 医療判断、法的紛争、税務判断、感情調整の抱え込み、家族間対立の仲裁、緊急対応の常時化など
- 必要に応じて他専門職・関係機関へつなぐ可能性として書いてください。

## 9. 家庭裁判所報告に向けた内部メモ
家庭裁判所にそのまま出す文章ではなく、後日報告書を作るための内部整理として、3〜6行でまとめてください。

## 10. 内部メモ用の短い要約
今回の後見カード全体の見取り図を3〜5行でまとめてください。

整理種別：{summary_type}

以下の後見記録をカード整理してください。
---
{source_text}
""".strip()


def render_guardian_card_ai():
    st.subheader("後見｜カード整理AI")
    st.caption("後見カード・面談記録・リソース地図を、本人中心のカード配置として整理します。AIは判断係ではなく、記録の整理係です。")

    ward_map, ward_labels = get_guardian_ward_options()
    if not ward_labels:
        st.warning("先に被後見人を登録してください。")
        return

    selected_label = st.selectbox("対象被後見人", ward_labels, key="guardian_card_ai_ward")
    ward_id = ward_map[selected_label]

    summary_type = st.selectbox(
        "整理種別",
        ["後見カード整理", "本人希望整理", "家族・支援者整理", "医療・介護整理", "財産・住まい整理", "ペット・生活整理", "家庭裁判所報告前整理", "その他"],
        key="guardian_card_ai_type"
    )

    source_text = build_guardian_ai_source(ward_id)

    with st.expander("AIに渡す元データを確認", expanded=False):
        st.text_area("元データ", source_text, height=320, key="guardian_card_ai_source")

    extra_instruction = st.text_area(
        "追加指示（任意）",
        placeholder="例：家庭裁判所提出前ではなく、内部用に短めに整理してください。",
        key="guardian_card_ai_extra"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        run_ai = st.button("後見カード整理AIを作成して保存", disabled=not can_write(), key="guardian_card_ai_run")
    with col2:
        st.caption(f"使用モデル：{get_openai_model()} / APIキー：{'設定あり' if get_openai_api_key() else '未設定'}")

    if run_ai:
        if not source_text.strip():
            st.error("整理対象のデータがありません。")
        else:
            try:
                prompt = build_guardian_card_ai_prompt(summary_type, source_text)
                if extra_instruction.strip():
                    prompt += f"\n\n追加指示：{extra_instruction.strip()}"
                with st.spinner("後見カード整理AIを作成しています..."):
                    result_text, model = call_openai_summary(prompt)
                ai_id = make_id("gai")
                execute("""
                    INSERT INTO guardian_ai_support
                    (ai_id, ward_id, created_at, updated_by, support_type, source_text, result_text, model, memo)
                    VALUES (%(ai_id)s, %(ward_id)s, %(created_at)s, %(updated_by)s, %(support_type)s, %(source_text)s, %(result_text)s, %(model)s, %(memo)s)
                """, {
                    "ai_id": ai_id,
                    "ward_id": ward_id,
                    "created_at": now_text(),
                    "updated_by": st.session_state.get("login_id", ""),
                    "support_type": f"カード整理AI｜{summary_type}",
                    "source_text": source_text,
                    "result_text": result_text,
                    "model": model,
                    "memo": extra_instruction,
                })
                log_action("create", "guardian_ai_support", ai_id, f"後見カード整理AI:{summary_type}")
                st.success("後見カード整理AIを保存しました。")
                st.rerun()
            except Exception as e:
                st.error("後見カード整理AIの作成に失敗しました。")
                st.exception(e)

    st.markdown("---")
    st.markdown("### 保存済み 後見カード整理AI")
    df = fetch_df("""
        SELECT ai_id, created_at, support_type, result_text, model, memo
        FROM guardian_ai_support
        WHERE ward_id=%(ward_id)s
          AND support_type LIKE 'カード整理AI%%'
        ORDER BY created_at DESC
    """, {"ward_id": ward_id})

    if df.empty:
        st.info("保存済みの後見カード整理AIはありません。")
    else:
        for _, r in df.iterrows():
            title = f"{r.get('created_at','')}｜{r.get('support_type','')}"
            with st.expander(title, expanded=False):
                st.markdown(normalize_text(r.get("result_text", "")))
                st.caption(f"model: {normalize_text(r.get('model',''))} / memo: {normalize_text(r.get('memo',''))}")

        if can_write():
            selected = st.selectbox("削除するAI整理ID", df["ai_id"].tolist(), key="guardian_card_ai_delete_select")
            delete_confirm = st.checkbox("この後見カード整理AIを削除することを確認しました。", key="guardian_card_ai_delete_confirm")
            if st.button("選択した後見カード整理AIを削除", key="guardian_card_ai_delete_button"):
                if not delete_confirm:
                    st.error("削除するには確認チェックを入れてください。")
                else:
                    execute("DELETE FROM guardian_ai_support WHERE ai_id=%(ai_id)s", {"ai_id": selected})
                    log_action("delete", "guardian_ai_support", selected, "後見カード整理AI削除")
                    st.success("削除しました。")
                    st.rerun()


def render_guardian_ai_support():
    st.subheader("後見AI支援")
    st.caption("AIは判断係ではなく、本人を支える関係性を整理する補助係です。")
    ward_map, ward_labels = get_guardian_ward_options()
    if not ward_labels:
        st.warning("先に被後見人を登録してください。")
        return
    selected_label = st.selectbox("対象被後見人", ward_labels, key="guardian_ai_ward")
    ward_id = ward_map[selected_label]
    support_type = st.selectbox("支援種別", ["リソース分析", "面談記録要約", "ヒアリング漏れ検出", "次回確認事項", "家庭裁判所報告メモ", "その他"])
    source_text = build_guardian_ai_source(ward_id)
    with st.expander("AIに渡す元データ", expanded=False):
        st.text_area("元データ", source_text, height=300)
    if st.button("後見AI整理を作成して保存", disabled=not can_write()):
        try:
            prompt = build_guardian_ai_prompt(support_type, source_text)
            with st.spinner("AI整理を作成しています..."):
                result_text, model = call_openai_summary(prompt)
            ai_id = make_id("gai")
            execute("""
                INSERT INTO guardian_ai_support
                (ai_id, ward_id, created_at, updated_by, support_type, source_text, result_text, model, memo)
                VALUES (%(ai_id)s, %(ward_id)s, %(created_at)s, %(updated_by)s, %(support_type)s, %(source_text)s, %(result_text)s, %(model)s, %(memo)s)
            """, {"ai_id": ai_id, "ward_id": ward_id, "created_at": now_text(), "updated_by": st.session_state.get("login_id", ""), "support_type": support_type, "source_text": source_text, "result_text": result_text, "model": model, "memo": ""})
            log_action("create", "guardian_ai_support", ai_id, f"後見AI支援:{support_type}")
            st.success("保存しました。")
            st.rerun()
        except Exception as e:
            st.error("AI整理に失敗しました。")
            st.exception(e)
    df = fetch_df("SELECT ai_id, created_at, support_type, result_text, model FROM guardian_ai_support WHERE ward_id=%(ward_id)s ORDER BY created_at DESC", {"ward_id": ward_id})
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_guardian_data_check():
    st.subheader("後見データ確認")
    tabs = st.tabs(["被後見人", "カード", "リソース地図", "面談記録", "AI支援"])
    targets = [
        ("guardian_wards", "被後見人"),
        ("guardian_cards", "カード"),
        ("guardian_resource_map", "リソース地図"),
        ("guardian_interview_logs", "面談記録"),
        ("guardian_ai_support", "AI支援"),
    ]
    for tab, (table, label) in zip(tabs, targets):
        with tab:
            df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(f"{label}CSVダウンロード", df.to_csv(index=False).encode("utf-8-sig"), file_name=f"{table}.csv", mime="text/csv")



def render_db_connection_check():
    st.subheader("データベース接続確認")
    st.caption("PostgreSQL接続、主要テーブル、追加テーブル、OpenAI設定、自動バックアップ設定を確認します。")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DATABASE_URL", "設定あり" if has_database_url() else "未設定")
    c2.metric("OpenAI API", "設定あり" if get_openai_api_key() else "未設定")
    c3.metric("AIモデル", get_openai_model())
    c4.metric("自動バックアップ", f"{get_secret_value('AUTO_BACKUP_HOURS', DEFAULT_AUTO_BACKUP_HOURS)}時間")

    st.markdown("---")
    st.markdown("### PostgreSQL疎通テスト")
    try:
        info = fetch_one("SELECT version() AS version, current_database() AS database_name, current_user AS user_name, NOW() AS server_time")
        st.success("PostgreSQLへの接続に成功しています。")
        st.json({
            "database": info.get("database_name", ""),
            "user": info.get("user_name", ""),
            "server_time": str(info.get("server_time", "")),
            "version": str(info.get("version", ""))[:180],
        })
    except Exception as e:
        st.error("PostgreSQLへの接続確認に失敗しました。")
        st.exception(e)
        return

    st.markdown("### 主要テーブル確認")
    check_tables = [
        "clients", "cases", "history", "properties", "cats", "family",
        "ai_summaries", "nyantomo_backup_logs",
        "guardian_wards", "guardian_cards", "guardian_resource_map",
        "guardian_interview_logs", "guardian_ai_support"
    ]
    rows = []
    for table in check_tables:
        try:
            row = fetch_one(f"SELECT COUNT(*) AS cnt FROM {table}")
            rows.append({"テーブル": table, "状態": "OK", "件数": int(row.get("cnt", 0)), "メモ": ""})
        except Exception as e:
            rows.append({"テーブル": table, "状態": "NG", "件数": "", "メモ": str(e)[:120]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("### バックアップ状態")
    try:
        last = fetch_one("SELECT created_at, backup_type, file_name FROM nyantomo_backup_logs ORDER BY created_at DESC LIMIT 1")
        if last:
            st.info(f"最終バックアップ：{last.get('created_at')} / {last.get('backup_type')} / {last.get('file_name')}")
        else:
            st.warning("バックアップログはまだありません。")
    except Exception as e:
        st.warning(f"バックアップログ確認に失敗しました：{e}")

    if st.button("接続確認を再実行"):
        st.rerun()

def render_data_check():
    st.subheader("データ確認")
    data_tables = list(TABLES)
    for extra_table, extra_label in [("consultation_cards", "Ver2.0_カード整理"), ("pending_items", "Ver2.0_保留事項"), ("ai_summaries", "AI要約")]:
        if extra_table not in [t for t, _ in data_tables]:
            data_tables.append((extra_table, extra_label))
    tabs = st.tabs([label for _, label in data_tables])
    for tab, (table, label) in zip(tabs, data_tables):
        with tab:
            try:
                df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button(
                    f"{label}CSVダウンロード",
                    df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{table}.csv",
                    mime="text/csv"
                )
            except Exception as e:
                st.error(f"{label}の読み込みに失敗しました。")
                st.exception(e)


def render_users():
    st.subheader("ログイン設定")
    if not can_admin():
        st.warning("管理者のみ利用できます。")
        return
    users_df = fetch_df("SELECT user_id, created_at, updated_at, login_id, role, display_name, active FROM app_users ORDER BY created_at")
    st.dataframe(users_df, use_container_width=True, hide_index=True)
    with st.form("app_user_create"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        role_new = st.selectbox("権限", [STAFF_ROLE, ADMIN_ROLE, VIEWER_ROLE])
        display_name = st.text_input("表示名")
        ok = st.form_submit_button("追加する")
    if ok:
        if not login_id.strip() or not password.strip():
            st.error("ログインIDとパスワードを入力してください。")
        else:
            user_id = make_id("user")
            execute("""
                INSERT INTO app_users
                (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                VALUES (%(user_id)s, %(created_at)s, %(updated_at)s, %(login_id)s, %(password_hash)s, %(role)s, %(display_name)s, 1)
            """, {
                "user_id": user_id, "created_at": now_text(), "updated_at": now_text(),
                "login_id": login_id.strip(), "password_hash": hash_password(password.strip()),
                "role": role_new, "display_name": display_name.strip() or login_id.strip()
            })
            log_action("create", "app_users", user_id, "ユーザー追加")
            st.success("追加しました。")
            st.rerun()


def render_analysis():
    st.subheader("分析・管理")
    st.markdown("### 状態遷移ログ")
    df = fetch_df("""
        SELECT h.created_at, cl.name AS client_name, c.case_title, h.before_status, h.after_status, h.record, h.internal_memo
        FROM history h
        LEFT JOIN cases c ON h.case_id = c.case_id
        LEFT JOIN clients cl ON h.client_id = cl.client_id
        WHERE h.record_type = '状態変更'
        ORDER BY h.created_at DESC
        LIMIT 100
    """)
    if df.empty:
        st.info("状態遷移ログはありません。")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### 監査ログ")
    audit = fetch_df("SELECT created_at, login_id, action, table_name, record_id, memo FROM audit_logs ORDER BY created_at DESC LIMIT 100")
    st.dataframe(audit, use_container_width=True, hide_index=True)


if not has_database_url():
    show_db_setup_screen()

try:
    init_db(hash_password, make_id, now_text)
    ensure_extension_tables()
except Exception as e:
    st.title(APP_TITLE)
    st.error("PostgreSQLへの接続または初期化に失敗しました。")
    st.exception(e)
    st.stop()

require_login()

try:
    auto_backup_path = maybe_run_auto_backup()
    if auto_backup_path and can_admin():
        st.toast(f"自動バックアップを作成しました：{auto_backup_path.name}")
except Exception as e:
    if can_admin():
        st.warning(f"自動バックアップに失敗しました：{e}")

st.title(APP_TITLE)
st.caption(APP_CAPTION)

role = st.session_state.get("role", STAFF_ROLE)
if role == ADMIN_ROLE:
    available_menus = ADMIN_MENUS
elif role == VIEWER_ROLE:
    available_menus = VIEWER_MENUS
else:
    available_menus = STAFF_MENUS

NYANTOMO_V2_MENUS = [
    "Ver2.0｜カードOS俯瞰",
    "Ver2.0｜カード整理",
    "Ver2.0｜保留事項管理",
]
for m in NYANTOMO_V2_MENUS:
    if m not in available_menus:
        available_menus.append(m)

GUARDIAN_MENUS = [
    "DB接続確認",
    "後見ダッシュボード",
    "後見｜被後見人",
    "後見｜本人希望カード",
    "後見｜家族カード",
    "後見｜医療カード",
    "後見｜介護カード",
    "後見｜財産カード",
    "後見｜住まいカード",
    "後見｜ペットカード",
    "後見｜支援者カード",
    "後見｜判断保留カード",
    "後見｜家庭裁判所対応カード",
    "後見｜リソース地図",
    "後見｜面談記録",
    "後見｜カード整理AI",
    "後見｜AI支援",
    "後見｜データ確認",
]
for m in GUARDIAN_MENUS:
    if m not in available_menus:
        available_menus.append(m)

menu = st.sidebar.radio("メニュー", available_menus)
logout_button()

if menu == "DB接続確認":
    render_db_connection_check()
elif menu == "管理ダッシュボード":
    render_dashboard()
elif menu == "相談者 登録・検索・更新・削除":
    render_clients()
elif menu == "案件 登録・検索・更新・削除":
    render_cases()
elif menu == "相談履歴 登録・確認":
    render_history()
elif menu == "Ver2.0｜カードOS俯瞰":
    render_card_os_overview()
elif menu == "Ver2.0｜カード整理":
    render_consultation_cards()
elif menu == "Ver2.0｜保留事項管理":
    render_pending_items()
elif menu == "空き家カード":
    related_card_page("properties", "property_id", "空き家カード", [
        ("property_name", "物件名", "text"),
        ("address", "住所", "text"),
        ("property_status", "物件状態", "text"),
        ("vacant_status", "空き家状態", "text"),
        ("key_hold", "鍵預かり", "text"),
        ("neighborhood", "近隣状況", "text"),
        ("visit_frequency", "確認頻度", "text"),
        ("memo", "メモ", "area"),
    ])
elif menu == "猫情報カード":
    related_card_page("cats", "cat_id", "猫情報カード", [
        ("cat_name", "猫の名前", "text"),
        ("age", "年齢", "text"),
        ("sex", "性別", "text"),
        ("health_memo", "健康メモ", "area"),
        ("life_status", "生活状況", "area"),
        ("future_plan", "今後の方針", "area"),
        ("memo", "メモ", "area"),
    ])
elif menu == "家族関係メモ":
    related_card_page("family", "family_id", "家族関係メモ", [
        ("name", "氏名", "text"),
        ("relation", "続柄", "text"),
        ("contact_ok", "連絡可否", "text"),
        ("temperature", "温度感", "text"),
        ("memo", "メモ", "area"),
    ])
elif menu == "AI要約メモ":
    render_ai_summary()
elif menu == "LINEメモ":
    render_line_memos()
elif menu == "LINEテンプレート":
    render_line_templates()
elif menu == "添付画像管理":
    related_card_page("photos", "photo_id", "添付画像管理", [
        ("photo_type", "写真種別", "text"),
        ("file_name", "ファイル名", "text"),
        ("storage_note", "保存場所メモ", "area"),
        ("memo", "メモ", "area"),
    ])
elif menu == "分析・管理":
    render_analysis()
elif menu == "バックアップ・出力":
    render_backup()
elif menu == "ログイン設定":
    render_users()
elif menu == "後見ダッシュボード":
    render_guardian_dashboard()
elif menu == "後見｜被後見人":
    render_guardian_wards()
elif menu == "後見｜本人希望カード":
    render_guardian_card("本人希望カード")
elif menu == "後見｜家族カード":
    render_guardian_card("家族カード")
elif menu == "後見｜医療カード":
    render_guardian_card("医療カード")
elif menu == "後見｜介護カード":
    render_guardian_card("介護カード")
elif menu == "後見｜財産カード":
    render_guardian_card("財産カード")
elif menu == "後見｜住まいカード":
    render_guardian_card("住まいカード")
elif menu == "後見｜ペットカード":
    render_guardian_card("ペットカード")
elif menu == "後見｜支援者カード":
    render_guardian_card("支援者カード")
elif menu == "後見｜判断保留カード":
    render_guardian_card("判断保留カード")
elif menu == "後見｜家庭裁判所対応カード":
    render_guardian_card("家庭裁判所対応カード")
elif menu == "後見｜リソース地図":
    render_guardian_resource_map()
elif menu == "後見｜面談記録":
    render_guardian_interviews()
elif menu == "後見｜カード整理AI":
    render_guardian_card_ai()
elif menu == "後見｜AI支援":
    render_guardian_ai_support()
elif menu == "後見｜データ確認":
    render_guardian_data_check()
elif menu == "データ確認":
    render_data_check()