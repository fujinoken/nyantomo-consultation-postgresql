# app.py
import uuid
import hashlib
import hmac
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
            if kind == "area":
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


def render_backup():
    st.subheader("バックアップ・出力")
    st.caption("現在の主要テーブルをCSV ZIPで出力します。Excel出力は openpyxl が利用できる場合のみ表示します。")

    data = {}
    for table, label in TABLES:
        try:
            data[label] = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
        except Exception as e:
            data[label] = pd.DataFrame([{"error": str(e)}])

    # CSV ZIPバックアップ：openpyxl不要で必ず動く
    csv_zip_buffer = BytesIO()
    with zipfile.ZipFile(csv_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, df in data.items():
            zf.writestr(f"{label}.csv", df.to_csv(index=False).encode("utf-8-sig"))

    st.download_button(
        "全テーブルCSV ZIPダウンロード",
        csv_zip_buffer.getvalue(),
        file_name=f"nyantomo_backup_{today_text()}.zip",
        mime="application/zip"
    )

    st.markdown("---")
    st.markdown("### Excel出力")

    try:
        import openpyxl  # noqa: F401

        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            for label, df in data.items():
                sheet_name = label[:31]
                df.to_excel(writer, index=False, sheet_name=sheet_name)

        st.download_button(
            "全テーブルExcelダウンロード",
            excel_buffer.getvalue(),
            file_name=f"nyantomo_backup_{today_text()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except ModuleNotFoundError:
        st.warning(
            "Streamlit Cloud側に openpyxl が入っていないため、Excel出力は現在使えません。"
            " CSV ZIPバックアップは利用できます。Excel出力を使う場合は requirements.txt に openpyxl を追加してください。"
        )
    except Exception as e:
        st.error("Excel出力でエラーが発生しました。CSV ZIPバックアップをご利用ください。")
        st.exception(e)


def render_data_check():
    st.subheader("データ確認")
    tabs = st.tabs([label for _, label in TABLES])
    for tab, (table, label) in zip(tabs, TABLES):
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
except Exception as e:
    st.title(APP_TITLE)
    st.error("PostgreSQLへの接続または初期化に失敗しました。")
    st.exception(e)
    st.stop()

require_login()

st.title(APP_TITLE)
st.caption(APP_CAPTION)

role = st.session_state.get("role", STAFF_ROLE)
if role == ADMIN_ROLE:
    available_menus = ADMIN_MENUS
elif role == VIEWER_ROLE:
    available_menus = VIEWER_MENUS
else:
    available_menus = STAFF_MENUS

menu = st.sidebar.radio("メニュー", available_menus)
logout_button()

if menu == "管理ダッシュボード":
    render_dashboard()
elif menu == "相談者 登録・検索・更新・削除":
    render_clients()
elif menu == "案件 登録・検索・更新・削除":
    render_cases()
elif menu == "相談履歴 登録・確認":
    render_history()
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
    related_card_page("ai_summaries", "summary_id", "AI要約メモ", [
        ("summary_type", "要約種別", "text"),
        ("source_text", "元メモ", "area"),
        ("summary_text", "要約", "area"),
        ("memo", "備考", "area"),
    ])
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
elif menu == "データ確認":
    render_data_check()
