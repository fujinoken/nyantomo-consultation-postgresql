import os
import uuid
import hashlib
import hmac
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

# ============================================================
# にゃんとも相談管理システム Ver3.1.0 DB層整理版
# ------------------------------------------------------------
# DB層整理版：PostgreSQL接続を明示的に開閉し、安定稼働を優先
#
# 主な対象：
# - 相談者
# - 案件
# - 相談履歴
# - 空き家カード
# - 猫情報
# - 家族関係
# - AI要約
# - LINEメモ
# - ログイン管理
#
# PostgreSQL接続：
# Streamlit secrets に以下を設定してください。
#
# [postgres]
# url = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
#
# または環境変数 DATABASE_URL でも可。
# ============================================================

st.set_page_config(
    page_title="にゃんとも相談管理 Ver3.1.0 DB層整理版",
    page_icon="🐾",
    layout="wide"
)

APP_VERSION = "3.1.0 DB層整理版"

ADMIN_MENUS = [
    "管理ダッシュボード",
    "相談者 登録・検索・更新・削除",
    "案件 登録・検索・更新・削除",
    "相談履歴 登録・確認",
    "空き家カード",
    "猫情報カード",
    "家族関係メモ",
    "AI要約メモ",
    "LINEメモ",
    "ログイン設定",
    "データ確認",
]

STAFF_MENUS = [
    "管理ダッシュボード",
    "相談者 登録・検索・更新・削除",
    "案件 登録・検索・更新・削除",
    "相談履歴 登録・確認",
    "空き家カード",
    "猫情報カード",
    "家族関係メモ",
]


STATUS_OPTIONS = [
    "未対応",
    "初回相談前",
    "初回相談済",
    "情報整理中",
    "保留中",
    "対応中",
    "継続相談",
    "専門家紹介",
    "終了",
]

CASE_TYPE_OPTIONS = [
    "初回相談",
    "空き家管理",
    "猫と住まい",
    "高齢期の住まい",
    "家族相談",
    "その他",
]

AGE_OPTIONS = ["未選択", "40代", "50代", "60代", "70代", "80代以上"]
CONTACT_OPTIONS = ["未選択", "LINE", "メール", "電話", "対面", "その他"]
POSITION_OPTIONS = ["未選択", "本人", "家族", "親族", "空き家所有者", "支援者", "その他"]


# ============================================================
# PostgreSQL接続
# ============================================================

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
    """PostgreSQL接続を取得する。呼び出し側で必ず close する。"""
    url = get_database_url()
    if not url:
        raise RuntimeError("PostgreSQL接続URLが設定されていません。")
    return psycopg2.connect(url)


def execute(sql, params=None):
    """INSERT / UPDATE / DELETE / DDL 用。接続と cursor を必ず閉じる。"""
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
    """SELECT結果を DataFrame で返す。pandas用に接続を明示的に閉じる。"""
    conn = None
    try:
        conn = get_conn()
        return pd.read_sql_query(sql, conn, params=params or {})
    finally:
        if conn:
            conn.close()


def fetch_one(sql, params=None):
    """SELECT結果を1行だけ dict で返す。"""
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


# ============================================================
# 共通関数
# ============================================================

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


def normalize_text(v):
    if v is None:
        return ""
    return str(v).strip()


def show_db_setup_screen():
    st.title("🐾 にゃんとも相談管理 Ver3.1.0 DB層整理版")
    st.error("PostgreSQL接続URLがまだ設定されていません。")

    st.markdown("""
### Streamlit Cloud の設定方法

アプリ管理画面の **Secrets** に以下を設定してください。

```toml
[postgres]
url = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```

Supabase / Neon / Railway などの PostgreSQL 接続URLを使えます。

設定後、アプリを再起動してください。
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


# ============================================================
# DB初期化
# ============================================================

def init_db():
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
            CREATE TABLE IF NOT EXISTS line_settings (
                setting_id TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                setting_name TEXT,
                setting_value TEXT,
                memo TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS line_messages (
                message_id TEXT PRIMARY KEY,
                case_id TEXT REFERENCES cases(case_id) ON DELETE SET NULL,
                client_id TEXT REFERENCES clients(client_id) ON DELETE SET NULL,
                created_at TIMESTAMP,
                created_by TEXT,
                to_target TEXT,
                message_text TEXT,
                send_status TEXT,
                response_memo TEXT
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

        cur.execute("CREATE INDEX IF NOT EXISTS idx_cases_client_id ON cases(client_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cases_next_check_date ON cases(next_check_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_history_case_id ON history(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_properties_case_id ON properties(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cats_case_id ON cats(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_family_case_id ON family(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_summaries_case_id ON ai_summaries(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_line_messages_case_id ON line_messages(case_id)")

        # PostgreSQL安定化のため、起動時の ALTER TABLE は実行しません。
        # DB構造変更は Neon などのSQL Editorで一度だけ行います。

        cur.execute("SELECT COUNT(*) FROM app_users")
        count = cur.fetchone()[0]
        if count == 0:
            cur.execute("""
                INSERT INTO app_users
                (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """, (
                make_id("user"),
                now_text(),
                now_text(),
                "admin",
                hash_password("admin123"),
                "管理者",
                "管理者"
            ))

            cur.execute("""
                INSERT INTO app_users
                (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """, (
                make_id("user"),
                now_text(),
                now_text(),
                "staff",
                hash_password("staff123"),
                "職員",
                "職員"
            ))

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

# ============================================================
# ログイン
# ============================================================

def login_screen():
    st.title("🐾 にゃんとも相談管理 Ver3.1.0 DB層整理版")
    st.subheader("ログイン")

    with st.form("login_form"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")

    if ok:
        user = fetch_one("""
            SELECT user_id, login_id, password_hash, role, display_name, active
            FROM app_users
            WHERE login_id = %(login_id)s
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


# ============================================================
# データ取得
# ============================================================

def get_clients():
    return fetch_df("""
        SELECT client_id, created_at, updated_at, name, age_group, area, contact_method, position, note
        FROM clients
        ORDER BY created_at DESC NULLS LAST
    """)


def get_cases():
    return fetch_df("""
        SELECT
            c.case_id,
            c.client_id,
            cl.name AS client_name,
            c.created_at,
            c.updated_at,
            c.consult_date,
            c.case_title,
            c.case_type,
            c.status,
            c.current_state,
            c.house_state,
            c.cat_relation,
            c.family_gap,
            c.pressure,
            c.worries,
            c.not_decide,
            c.first_check,
            c.free_memo,
            c.internal_memo,
            c.next_check,
            c.next_hearing_items,
            c.hearing_missing,
            c.do_not_do_now,
            c.next_check_date,
            c.closed_date,
            c.close_reason,
            c.final_memo,
            c.reopen_possibility
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


# ============================================================
# 初期設定
# ============================================================

if not has_database_url():
    show_db_setup_screen()

try:
    init_db()
except Exception as e:
    st.title("🐾 にゃんとも相談管理 Ver3.1.0 DB層整理版")
    st.error("PostgreSQLへの接続または初期化に失敗しました。")
    st.exception(e)
    st.stop()

require_login()

st.title("🐾 にゃんとも相談管理 Ver3.1.0 DB層整理版")
st.caption("PostgreSQLリレーショナルDB版／DB接続層整理・安定稼働用")

role = st.session_state.get("role", "職員")
available_menus = ADMIN_MENUS if role == "管理者" else STAFF_MENUS
menu = st.sidebar.radio("メニュー", available_menus)
logout_button()


# ============================================================
# 関連カード共通
# ============================================================

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
            if kind == "text":
                values[key] = st.text_input(label)
            elif kind == "area":
                values[key] = st.text_area(label)
            elif kind == "date":
                values[key] = st.date_input(label, date.today())
        ok = st.form_submit_button("登録する")

    if ok:
        new_id = make_id(id_col.replace("_id", ""))
        cols = [id_col, "case_id", "client_id", "created_at", "updated_at"] + [x[0] for x in fields]
        params = {id_col: new_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "updated_at": now_text(), **values}
        sql = f"""
            INSERT INTO {table_name}
            ({", ".join(cols)})
            VALUES
            ({", ".join([f"%({c})s" for c in cols])})
        """
        execute(sql, params)
        log_action("create", table_name, new_id, f"{title}登録")
        st.success("登録しました。")
        st.rerun()

    st.markdown("---")
    st.markdown("### 一覧")
    df = fetch_df(f"SELECT * FROM {table_name} WHERE case_id=%(case_id)s ORDER BY created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        selected = st.selectbox("削除するID", df[id_col].tolist(), key=f"{table_name}_delete_select")
        delete_confirm = st.checkbox("削除することを確認しました。", key=f"{table_name}_delete_confirm")
        delete_text = st.text_input("削除する場合は DELETE と入力", key=f"{table_name}_delete_text")
        if st.button("削除する", key=f"{table_name}_delete_button"):
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute(f"DELETE FROM {table_name} WHERE {id_col}=%(id)s", {"id": selected})
                log_action("delete", table_name, selected, f"{title}削除")
                st.success("削除しました。")
                st.rerun()



# ============================================================
# 管理ダッシュボード
# ============================================================

if menu == "管理ダッシュボード":
    st.subheader("管理ダッシュボード")

    clients = get_clients()
    cases = get_cases()

    today_dt = date.today()
    check_limit_dt = today_dt + timedelta(days=7)

    if not cases.empty:
        active_mask = ~cases["status"].isin(["終了"])
        open_cases = cases[active_mask]

        next_dates = pd.to_datetime(cases["next_check_date"], errors="coerce").dt.date
        need_check = cases[
            active_mask &
            next_dates.notna() &
            (next_dates <= check_limit_dt)
        ].copy()

        hearing_missing_cases = cases[
            active_mask &
            cases["hearing_missing"].fillna("").astype(str).str.strip().ne("")
        ].copy()

        do_not_do_now_cases = cases[
            active_mask &
            cases["do_not_do_now"].fillna("").astype(str).str.strip().ne("")
        ].copy()
    else:
        open_cases = pd.DataFrame()
        need_check = pd.DataFrame()
        hearing_missing_cases = pd.DataFrame()
        do_not_do_now_cases = pd.DataFrame()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("相談者数", len(clients))
    col2.metric("案件数", len(cases))
    col3.metric("進行中案件", len(open_cases))
    col4.metric("要確認案件", len(need_check))

    st.markdown("---")

    st.markdown("### 要確認案件")
    st.caption("次回確認日が今日から7日以内、または期限超過している進行中案件です。")
    if need_check.empty:
        st.info("要確認案件はありません。")
    else:
        cols = ["client_name", "case_title", "status", "next_check_date", "next_check"]
        st.dataframe(need_check[cols], use_container_width=True)

    st.markdown("---")

    left_mid, right_mid = st.columns(2)

    with left_mid:
        st.markdown("### ヒアリング漏れがある案件")
        st.caption("案件管理の『ヒアリング漏れ警告』に入力がある案件です。")
        if hearing_missing_cases.empty:
            st.success("ヒアリング漏れが登録されている案件はありません。")
        else:
            cols = ["client_name", "case_title", "status", "hearing_missing", "next_hearing_items"]
            st.warning("確認が必要なヒアリング項目があります。")
            st.dataframe(hearing_missing_cases[cols], use_container_width=True)

    with right_mid:
        st.markdown("### 今やらない方がいいことが登録されている案件")
        st.caption("案件管理の『今やらない方がいいこと』に入力がある案件です。")
        if do_not_do_now_cases.empty:
            st.info("今やらない方がいいことが登録されている案件はありません。")
        else:
            cols = ["client_name", "case_title", "status", "do_not_do_now", "not_decide"]
            st.warning("急がせないための注意事項があります。")
            st.dataframe(do_not_do_now_cases[cols], use_container_width=True)

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.markdown("### 次回確認が近い案件")
        if need_check.empty:
            st.info("期限が近い案件はありません。")
        else:
            st.dataframe(need_check[["client_name", "case_title", "status", "next_check_date", "next_check"]], use_container_width=True)

    with right:
        st.markdown("### 状態別件数")
        if cases.empty:
            st.info("案件がありません。")
        else:
            status_df = cases.groupby("status").size().reset_index(name="件数")
            st.dataframe(status_df, use_container_width=True)

    st.markdown("---")
    st.markdown("### 最近の案件")
    if cases.empty:
        st.info("案件がありません。")
    else:
        st.dataframe(cases[["client_name", "case_title", "case_type", "status", "consult_date", "updated_at"]].head(20), use_container_width=True)


# ============================================================
# 相談者 CRUD
# ============================================================

elif menu == "相談者 登録・検索・更新・削除":
    st.subheader("相談者 登録・検索・更新・削除")

    st.markdown("### 登録")
    with st.form("client_create"):
        name = st.text_input("お名前")
        age_group = st.selectbox("年代", AGE_OPTIONS)
        area = st.text_input("地域")
        contact_method = st.selectbox("連絡方法", CONTACT_OPTIONS)
        position = st.selectbox("立場", POSITION_OPTIONS)
        note = st.text_area("備考")
        ok = st.form_submit_button("登録する")

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
                "client_id": client_id,
                "created_at": now_text(),
                "updated_at": now_text(),
                "name": name.strip(),
                "age_group": age_group,
                "area": area,
                "contact_method": contact_method,
                "position": position,
                "note": note,
            })
            log_action("create", "clients", client_id, "相談者登録")
            st.success("相談者を登録しました。")
            st.rerun()

    st.markdown("---")
    st.markdown("### 検索・更新・削除")
    keyword = st.text_input("検索語（名前・地域・備考）", key="client_search")
    clients = get_clients()

    filtered = clients.copy()
    if keyword and not filtered.empty:
        filtered = filtered[
            filtered["name"].astype(str).str.contains(keyword, na=False) |
            filtered["area"].astype(str).str.contains(keyword, na=False) |
            filtered["note"].astype(str).str.contains(keyword, na=False)
        ]

    st.dataframe(filtered, use_container_width=True)

    if not filtered.empty:
        selected = st.selectbox("更新・削除する相談者", filtered["client_id"].tolist())
        row = clients[clients["client_id"] == selected].iloc[0]

        with st.form("client_edit"):
            new_name = st.text_input("お名前", str(row["name"]))
            new_age = st.selectbox("年代", AGE_OPTIONS, index=AGE_OPTIONS.index(row["age_group"]) if row["age_group"] in AGE_OPTIONS else 0)
            new_area = st.text_input("地域", str(row["area"]))
            new_contact = st.selectbox("連絡方法", CONTACT_OPTIONS, index=CONTACT_OPTIONS.index(row["contact_method"]) if row["contact_method"] in CONTACT_OPTIONS else 0)
            new_position = st.selectbox("立場", POSITION_OPTIONS, index=POSITION_OPTIONS.index(row["position"]) if row["position"] in POSITION_OPTIONS else 0)
            new_note = st.text_area("備考", str(row["note"]))

            st.markdown("#### 削除する場合の確認")
            delete_confirm = st.checkbox("この相談者を削除することを確認しました。関連する案件も削除されます。")
            delete_text = st.text_input("削除する場合は DELETE と入力")

            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            if not new_name.strip():
                st.error("お名前は空欄にできません。")
            else:
                execute("""
                    UPDATE clients
                    SET updated_at=%(updated_at)s, name=%(name)s, age_group=%(age_group)s, area=%(area)s,
                        contact_method=%(contact_method)s, position=%(position)s, note=%(note)s
                    WHERE client_id=%(client_id)s
                """, {
                    "updated_at": now_text(),
                    "name": new_name.strip(),
                    "age_group": new_age,
                    "area": new_area,
                    "contact_method": new_contact,
                    "position": new_position,
                    "note": new_note,
                    "client_id": selected,
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


# ============================================================
# 案件 CRUD
# ============================================================

elif menu == "案件 登録・検索・更新・削除":
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
            ok = st.form_submit_button("登録する")

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
                    "case_id": case_id,
                    "client_id": client_id,
                    "created_at": now_text(),
                    "updated_at": now_text(),
                    "consult_date": consult_date,
                    "case_title": case_title.strip(),
                    "case_type": case_type,
                    "status": status,
                    "current_state": current_state,
                    "house_state": house_state,
                    "cat_relation": cat_relation,
                    "family_gap": family_gap,
                    "pressure": pressure,
                    "worries": worries,
                    "not_decide": not_decide,
                    "first_check": first_check,
                    "free_memo": free_memo,
                    "internal_memo": internal_memo,
                    "next_check": next_check,
                    "next_hearing_items": next_hearing_items,
                    "hearing_missing": hearing_missing,
                    "do_not_do_now": do_not_do_now,
                    "next_check_date": next_check_date,
                })

                log_action("create", "cases", case_id, "案件登録")
                st.success("案件を登録しました。")
                st.rerun()

    st.markdown("---")
    st.markdown("### 検索・更新・削除")
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
    st.dataframe(filtered[show_cols] if not filtered.empty else filtered, use_container_width=True)

    if not filtered.empty:
        selected = st.selectbox("更新・削除する案件", filtered["case_id"].tolist())
        row = cases[cases["case_id"] == selected].iloc[0]

        with st.form("case_edit"):
            new_title = st.text_input("案件名", str(row["case_title"]))
            new_type = st.selectbox("案件種別", CASE_TYPE_OPTIONS, index=CASE_TYPE_OPTIONS.index(row["case_type"]) if row["case_type"] in CASE_TYPE_OPTIONS else 0)
            new_status = st.selectbox("状態", STATUS_OPTIONS, index=STATUS_OPTIONS.index(row["status"]) if row["status"] in STATUS_OPTIONS else 0)
            new_current_state = st.text_area("現在の状態", str(row["current_state"]))
            new_house_state = st.text_area("住まい・空き家の状態", str(row["house_state"]))
            new_cat_relation = st.text_area("猫との関係", str(row["cat_relation"]))
            new_family_gap = st.text_area("家族間の温度差", str(row["family_gap"]))
            new_pressure = st.text_area("急がされ感", str(row["pressure"]))
            new_worries = st.text_area("心配ごと", str(row["worries"]))
            new_not_decide = st.text_area("今は決めないこと", str(row["not_decide"]))
            new_internal_memo = st.text_area("内部メモ", str(row["internal_memo"]))
            new_next_check = st.text_area("次回確認", str(row["next_check"]))
            new_next_hearing_items = st.text_area("次回ヒアリング項目", str(row.get("next_hearing_items", "")))
            new_hearing_missing = st.text_area("ヒアリング漏れ警告", str(row.get("hearing_missing", "")))
            new_do_not_do_now = st.text_area("今やらない方がいいこと", str(row.get("do_not_do_now", "")))
            new_next_check_date = st.date_input("次回確認日", pd.to_datetime(row["next_check_date"]).date() if pd.notna(row["next_check_date"]) and str(row["next_check_date"]) else None)
            new_final_memo = st.text_area("終了・最終メモ", str(row["final_memo"]))

            st.markdown("#### 削除する場合の確認")
            delete_confirm = st.checkbox("この案件を削除することを確認しました。関連データも削除されます。")
            delete_text = st.text_input("削除する場合は DELETE と入力", key="case_delete_text")

            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            before_status = row["status"]

            execute("""
                UPDATE cases
                SET updated_at=%(updated_at)s, case_title=%(case_title)s, case_type=%(case_type)s, status=%(status)s,
                    current_state=%(current_state)s, house_state=%(house_state)s, cat_relation=%(cat_relation)s,
                    family_gap=%(family_gap)s, pressure=%(pressure)s, worries=%(worries)s, not_decide=%(not_decide)s,
                    internal_memo=%(internal_memo)s, next_check=%(next_check)s,
                    next_hearing_items=%(next_hearing_items)s,
                    hearing_missing=%(hearing_missing)s,
                    do_not_do_now=%(do_not_do_now)s,
                    next_check_date=%(next_check_date)s,
                    final_memo=%(final_memo)s
                WHERE case_id=%(case_id)s
            """, {
                "updated_at": now_text(),
                "case_title": new_title,
                "case_type": new_type,
                "status": new_status,
                "current_state": new_current_state,
                "house_state": new_house_state,
                "cat_relation": new_cat_relation,
                "family_gap": new_family_gap,
                "pressure": new_pressure,
                "worries": new_worries,
                "not_decide": new_not_decide,
                "internal_memo": new_internal_memo,
                "next_check": new_next_check,
                "next_hearing_items": new_next_hearing_items,
                "hearing_missing": new_hearing_missing,
                "do_not_do_now": new_do_not_do_now,
                "next_check_date": new_next_check_date,
                "final_memo": new_final_memo,
                "case_id": selected,
            })

            if before_status != new_status:
                history_id = make_id("hist")
                execute("""
                    INSERT INTO history
                    (history_id, case_id, client_id, created_at, record_date, record_type, before_status, after_status, record, next_action, internal_memo)
                    VALUES
                    (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(before_status)s, %(after_status)s, %(record)s, %(next_action)s, %(internal_memo)s)
                """, {
                    "history_id": history_id,
                    "case_id": selected,
                    "client_id": row["client_id"],
                    "created_at": now_text(),
                    "record_date": today_text(),
                    "record_type": "状態変更",
                    "before_status": before_status,
                    "after_status": new_status,
                    "record": f"状態を {before_status} から {new_status} に変更",
                    "next_action": new_next_check,
                    "internal_memo": "案件更新時に自動記録",
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


# ============================================================
# 相談履歴
# ============================================================

elif menu == "相談履歴 登録・確認":
    st.subheader("相談履歴 登録・確認")

    case_map, case_labels = get_case_options()

    if not case_labels:
        st.warning("先に案件を登録してください。")
    else:
        selected_label = st.selectbox("対象案件", case_labels)
        case_id = case_map[selected_label]
        client_id = case_to_client(case_id)

        st.markdown("### 履歴登録")
        with st.form("history_create"):
            record_date = st.date_input("記録日", date.today())
            record_type = st.selectbox("記録種別", ["相談", "電話", "LINE", "訪問", "状態変更", "内部メモ", "その他"])
            record = st.text_area("記録内容")
            next_action = st.text_area("次の対応")
            internal_memo = st.text_area("内部メモ")
            ok = st.form_submit_button("登録する")

        if ok:
            if not record.strip():
                st.error("記録内容を入力してください。")
            else:
                history_id = make_id("hist")
                execute("""
                    INSERT INTO history
                    (history_id, case_id, client_id, created_at, record_date, record_type, record, next_action, internal_memo)
                    VALUES
                    (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(record)s, %(next_action)s, %(internal_memo)s)
                """, {
                    "history_id": history_id,
                    "case_id": case_id,
                    "client_id": client_id,
                    "created_at": now_text(),
                    "record_date": record_date,
                    "record_type": record_type,
                    "record": record,
                    "next_action": next_action,
                    "internal_memo": internal_memo,
                })
                execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
                log_action("create", "history", history_id, "相談履歴登録")
                st.success("相談履歴を登録しました。")
                st.rerun()

        st.markdown("---")
        st.markdown("### 履歴一覧")
        df = fetch_df("""
            SELECT history_id, record_date, record_type, before_status, after_status, record, next_action, internal_memo, created_at
            FROM history
            WHERE case_id=%(case_id)s
            ORDER BY record_date DESC, created_at DESC
        """, {"case_id": case_id})
        st.dataframe(df, use_container_width=True)



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
    st.subheader("LINEメモ")

    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
    else:
        selected_label = st.selectbox("対象案件", case_labels)
        case_id = case_map[selected_label]
        client_id = case_to_client(case_id)

        with st.form("line_message_create"):
            to_target = st.text_input("送信先・対象")
            message_text = st.text_area("送信文")
            send_status = st.selectbox("状態", ["下書き", "送信済", "返信あり", "保留"])
            response_memo = st.text_area("返信・反応メモ")
            ok = st.form_submit_button("登録する")

        if ok:
            message_id = make_id("line")
            execute("""
                INSERT INTO line_messages
                (message_id, case_id, client_id, created_at, created_by, to_target, message_text, send_status, response_memo)
                VALUES
                (%(message_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(created_by)s, %(to_target)s, %(message_text)s, %(send_status)s, %(response_memo)s)
            """, {
                "message_id": message_id,
                "case_id": case_id,
                "client_id": client_id,
                "created_at": now_text(),
                "created_by": st.session_state.get("login_id", ""),
                "to_target": to_target,
                "message_text": message_text,
                "send_status": send_status,
                "response_memo": response_memo,
            })
            log_action("create", "line_messages", message_id, "LINEメモ登録")
            st.success("LINEメモを登録しました。")
            st.rerun()

        df = fetch_df("""
            SELECT message_id, created_at, created_by, to_target, message_text, send_status, response_memo
            FROM line_messages
            WHERE case_id=%(case_id)s
            ORDER BY created_at DESC
        """, {"case_id": case_id})
        st.dataframe(df, use_container_width=True)


# ============================================================
# ログイン設定
# ============================================================

elif menu == "ログイン設定":
    st.subheader("ログイン設定")

    users_df = fetch_df("""
        SELECT user_id, created_at, updated_at, login_id, role, display_name, active
        FROM app_users
        ORDER BY created_at
    """)
    st.dataframe(users_df, use_container_width=True)

    st.markdown("### 新規アカウント追加")
    with st.form("app_user_create"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        role_new = st.selectbox("権限", ["職員", "管理者"])
        display_name = st.text_input("表示名")
        ok = st.form_submit_button("追加する")

    if ok:
        if not login_id.strip() or not password.strip():
            st.error("ログインIDとパスワードを入力してください。")
        else:
            try:
                user_id = make_id("user")
                execute("""
                    INSERT INTO app_users
                    (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
                    VALUES
                    (%(user_id)s, %(created_at)s, %(updated_at)s, %(login_id)s, %(password_hash)s, %(role)s, %(display_name)s, 1)
                """, {
                    "user_id": user_id,
                    "created_at": now_text(),
                    "updated_at": now_text(),
                    "login_id": login_id.strip(),
                    "password_hash": hash_password(password.strip()),
                    "role": role_new,
                    "display_name": display_name.strip() or login_id.strip(),
                })
                log_action("create", "app_users", user_id, "ユーザー追加")
                st.success("アカウントを追加しました。")
                st.rerun()
            except Exception as e:
                st.error(f"登録できませんでした：{e}")

    st.markdown("### パスワード・権限変更")
    if not users_df.empty:
        selected = st.selectbox("変更するユーザーID", users_df["user_id"].tolist())
        row = users_df[users_df["user_id"] == selected].iloc[0]

        with st.form("app_user_edit"):
            st.text_input("ログインID", str(row["login_id"]), disabled=True)
            new_password = st.text_input("新しいパスワード（空欄なら変更なし）", type="password")
            new_role = st.selectbox("権限", ["職員", "管理者"], index=0 if row["role"] == "職員" else 1)
            new_display = st.text_input("表示名", str(row["display_name"]))
            new_active = st.checkbox("有効", value=bool(row["active"]))
            update = st.form_submit_button("更新する")

        if update:
            if new_password.strip():
                execute("""
                    UPDATE app_users
                    SET updated_at=%(updated_at)s, password_hash=%(password_hash)s, role=%(role)s, display_name=%(display_name)s, active=%(active)s
                    WHERE user_id=%(user_id)s
                """, {
                    "updated_at": now_text(),
                    "password_hash": hash_password(new_password.strip()),
                    "role": new_role,
                    "display_name": new_display,
                    "active": 1 if new_active else 0,
                    "user_id": selected,
                })
            else:
                execute("""
                    UPDATE app_users
                    SET updated_at=%(updated_at)s, role=%(role)s, display_name=%(display_name)s, active=%(active)s
                    WHERE user_id=%(user_id)s
                """, {
                    "updated_at": now_text(),
                    "role": new_role,
                    "display_name": new_display,
                    "active": 1 if new_active else 0,
                    "user_id": selected,
                })

            log_action("update", "app_users", selected, "ユーザー更新")
            st.success("アカウントを更新しました。")
            st.rerun()


# ============================================================
# データ確認
# ============================================================

elif menu == "データ確認":
    st.subheader("データ確認")

    tabs = st.tabs([
        "相談者",
        "案件",
        "履歴",
        "空き家",
        "猫",
        "家族",
        "AI要約",
        "LINE",
        "監査ログ",
    ])

    tables = [
        ("clients", "相談者"),
        ("cases", "案件"),
        ("history", "履歴"),
        ("properties", "空き家"),
        ("cats", "猫"),
        ("family", "家族"),
        ("ai_summaries", "AI要約"),
        ("line_messages", "LINE"),
        ("audit_logs", "監査ログ"),
    ]

    for tab, (table, label) in zip(tabs, tables):
        with tab:
            df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
            st.dataframe(df, use_container_width=True)
            st.download_button(
                f"{label}CSVダウンロード",
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{table}.csv",
                mime="text/csv"
            )
