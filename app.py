# ============================================================
# にゃんとも相談管理システム Ver3.2.0 モジュール安定版
# app.py
# 必要ファイル：app.py / db.py / config.py
# ============================================================

import io
import zipfile
from datetime import date

import pandas as pd
import streamlit as st

from config import (
    APP_TITLE, APP_VERSION, APP_CAPTION,
    STATUS_OPTIONS, CASE_TYPE_OPTIONS, AGE_OPTIONS, CONTACT_OPTIONS, POSITION_OPTIONS,
    ROLE_ADMIN, ROLE_STAFF, ROLE_VIEWER,
    ADMIN_MENUS, STAFF_MENUS, VIEWER_MENUS, TABLES,
)
from db import (
    has_database_url, init_db, execute, fetch_df, fetch_one,
    make_id, now_text, today_text, hash_password, verify_password, log_action,
)

st.set_page_config(page_title=f"{APP_TITLE} {APP_VERSION}", page_icon="🐾", layout="wide")


def clean(v):
    if v is None:
        return ""
    if pd.isna(v):
        return ""
    return str(v)


def show_db_setup_screen():
    st.title(f"🐾 {APP_TITLE} {APP_VERSION}")
    st.error("PostgreSQL接続URLがまだ設定されていません。")
    st.markdown('''
### Streamlit Cloud の Secrets に設定してください

```toml
[postgres]
url = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```
''')
    st.stop()


def login_screen():
    st.title(f"🐾 {APP_TITLE} {APP_VERSION}")
    st.subheader("ログイン")

    with st.form("login_form"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")

    if ok:
        user = fetch_one(
            """
            SELECT user_id, login_id, password_hash, role, display_name, active
            FROM app_users
            WHERE login_id = %(login_id)s
            """,
            {"login_id": login_id},
        )
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

    st.info("初期設定：管理者 admin / admin123　職員 staff / staff123　閲覧者 viewer / viewer123")


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


def can_write():
    return st.session_state.get("role") in [ROLE_ADMIN, ROLE_STAFF]


def can_admin():
    return st.session_state.get("role") == ROLE_ADMIN


def deny_if_readonly():
    if not can_write():
        st.warning("閲覧者権限では登録・更新・削除はできません。")
        return True
    return False


def get_available_menus():
    role = st.session_state.get("role", ROLE_VIEWER)
    if role == ROLE_ADMIN:
        return ADMIN_MENUS
    if role == ROLE_STAFF:
        return STAFF_MENUS
    return VIEWER_MENUS


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


def get_client_options():
    df = get_clients()
    labels, mapping = [], {}
    for _, r in df.iterrows():
        label = f"{r['name']}｜{clean(r['area'])}｜{r['client_id']}"
        labels.append(label)
        mapping[label] = r["client_id"]
    return mapping, labels


def get_case_options():
    df = get_cases()
    labels, mapping = [], {}
    for _, r in df.iterrows():
        label = f"{r['client_name']}｜{r['case_title']}｜{r['status']}｜{r['case_id']}"
        labels.append(label)
        mapping[label] = r["case_id"]
    return mapping, labels


def case_to_client(case_id):
    row = fetch_one("SELECT client_id FROM cases WHERE case_id=%(case_id)s", {"case_id": case_id})
    return row["client_id"] if row else ""


def download_zip_all_tables():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for table, label in TABLES:
            try:
                df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
                zf.writestr(f"{table}_{label}.csv", df.to_csv(index=False).encode("utf-8-sig"))
            except Exception as e:
                zf.writestr(f"ERROR_{table}.txt", str(e))
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def excel_all_tables():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for table, label in TABLES:
            try:
                df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
                sheet_name = label[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            except Exception as e:
                pd.DataFrame({"error": [str(e)]}).to_excel(writer, sheet_name=table[:31], index=False)
    buffer.seek(0)
    return buffer.getvalue()


def render_dashboard():
    st.subheader("管理ダッシュボード")

    clients_count = fetch_one("SELECT COUNT(*) AS cnt FROM clients")["cnt"]
    cases_count = fetch_one("SELECT COUNT(*) AS cnt FROM cases")["cnt"]
    open_count = fetch_one("SELECT COUNT(*) AS cnt FROM cases WHERE COALESCE(status,'') <> '終了'")["cnt"]
    need_count = fetch_one("""
        SELECT COUNT(*) AS cnt
        FROM cases
        WHERE COALESCE(status,'') <> '終了'
          AND next_check_date IS NOT NULL
          AND next_check_date <= CURRENT_DATE + INTERVAL '7 days'
    """)["cnt"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("相談者数", int(clients_count))
    c2.metric("案件数", int(cases_count))
    c3.metric("進行中案件", int(open_count))
    c4.metric("要確認案件", int(need_count))

    st.markdown("---")
    st.markdown("### 要確認案件")
    need_df = fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.next_check_date, c.next_check
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND c.next_check_date IS NOT NULL
          AND c.next_check_date <= CURRENT_DATE + INTERVAL '7 days'
        ORDER BY c.next_check_date ASC
    """)
    if need_df.empty:
        st.info("要確認案件はありません。")
    else:
        st.dataframe(need_df, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown("### ヒアリング漏れがある案件")
        df = fetch_df("""
            SELECT cl.name AS client_name, c.case_title, c.status, c.hearing_missing, c.next_hearing_items
            FROM cases c
            JOIN clients cl ON c.client_id = cl.client_id
            WHERE COALESCE(c.status,'') <> '終了'
              AND NULLIF(TRIM(COALESCE(c.hearing_missing,'')), '') IS NOT NULL
            ORDER BY c.updated_at DESC NULLS LAST
        """)
        if df.empty:
            st.success("ヒアリング漏れが登録されている案件はありません。")
        else:
            st.warning("確認が必要なヒアリング項目があります。")
            st.dataframe(df, use_container_width=True, hide_index=True)
    with right:
        st.markdown("### 今やらない方がいいこと")
        df = fetch_df("""
            SELECT cl.name AS client_name, c.case_title, c.status, c.do_not_do_now, c.not_decide
            FROM cases c
            JOIN clients cl ON c.client_id = cl.client_id
            WHERE COALESCE(c.status,'') <> '終了'
              AND NULLIF(TRIM(COALESCE(c.do_not_do_now,'')), '') IS NOT NULL
            ORDER BY c.updated_at DESC NULLS LAST
        """)
        if df.empty:
            st.info("今やらない方がいいことが登録されている案件はありません。")
        else:
            st.warning("急がせないための注意事項があります。")
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    left2, right2 = st.columns(2)
    with left2:
        st.markdown("### 状態別件数")
        df = fetch_df("SELECT COALESCE(status,'未設定') AS status, COUNT(*) AS 件数 FROM cases GROUP BY COALESCE(status,'未設定') ORDER BY 件数 DESC")
        st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("案件がありません。")
    with right2:
        st.markdown("### 最近の案件")
        df = fetch_df("""
            SELECT cl.name AS client_name, c.case_title, c.case_type, c.status, c.consult_date, c.updated_at
            FROM cases c JOIN clients cl ON c.client_id = cl.client_id
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
            LIMIT 20
        """)
        st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("案件がありません。")


def render_clients():
    st.subheader("相談者 登録・検索・更新・削除")
    if deny_if_readonly():
        st.dataframe(get_clients(), use_container_width=True, hide_index=True)
        return

    with st.expander("相談者を登録", expanded=True):
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
                """, {"client_id": client_id, "created_at": now_text(), "updated_at": now_text(), "name": name.strip(), "age_group": age_group, "area": area, "contact_method": contact_method, "position": position, "note": note})
                log_action("create", "clients", client_id, "相談者登録")
                st.success("相談者を登録しました。")
                st.rerun()

    st.markdown("### 検索・更新・削除")
    keyword = st.text_input("検索語（名前・地域・備考）", key="client_search")
    df = get_clients()
    if keyword and not df.empty:
        mask = df.apply(lambda row: keyword in " ".join([clean(x) for x in row.values]), axis=1)
        df = df[mask]
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        selected = st.selectbox("更新・削除する相談者", df["client_id"].tolist())
        row = df[df["client_id"] == selected].iloc[0]
        with st.form("client_edit"):
            new_name = st.text_input("お名前", clean(row["name"]))
            new_age = st.selectbox("年代", AGE_OPTIONS, index=AGE_OPTIONS.index(row["age_group"]) if row["age_group"] in AGE_OPTIONS else 0)
            new_area = st.text_input("地域", clean(row["area"]))
            new_contact = st.selectbox("連絡方法", CONTACT_OPTIONS, index=CONTACT_OPTIONS.index(row["contact_method"]) if row["contact_method"] in CONTACT_OPTIONS else 0)
            new_position = st.selectbox("立場", POSITION_OPTIONS, index=POSITION_OPTIONS.index(row["position"]) if row["position"] in POSITION_OPTIONS else 0)
            new_note = st.text_area("備考", clean(row["note"]))
            delete_confirm = st.checkbox("削除することを確認しました。関連する案件も削除されます。")
            delete_text = st.text_input("削除する場合は DELETE と入力")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")
        if update:
            execute("""
                UPDATE clients SET updated_at=%(updated_at)s, name=%(name)s, age_group=%(age_group)s,
                area=%(area)s, contact_method=%(contact_method)s, position=%(position)s, note=%(note)s
                WHERE client_id=%(client_id)s
            """, {"updated_at": now_text(), "name": new_name.strip(), "age_group": new_age, "area": new_area, "contact_method": new_contact, "position": new_position, "note": new_note, "client_id": selected})
            log_action("update", "clients", selected, "相談者更新")
            st.success("更新しました。")
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM clients WHERE client_id=%(client_id)s", {"client_id": selected})
                log_action("delete", "clients", selected, "相談者削除")
                st.success("削除しました。")
                st.rerun()


def render_cases():
    st.subheader("案件 登録・検索・更新・削除")
    if deny_if_readonly():
        st.dataframe(get_cases(), use_container_width=True, hide_index=True)
        return

    client_map, client_labels = get_client_options()
    with st.expander("案件を登録", expanded=True):
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
                    """, locals() | {"created_at": now_text(), "updated_at": now_text()})
                    log_action("create", "cases", case_id, "案件登録")
                    st.success("案件を登録しました。")
                    st.rerun()

    st.markdown("### 検索・更新・削除")
    keyword = st.text_input("検索語（相談者・案件名・状態・メモ）", key="case_search")
    df = get_cases()
    if keyword and not df.empty:
        mask = df.apply(lambda row: keyword in " ".join([clean(x) for x in row.values]), axis=1)
        df = df[mask]
    show_cols = ["case_id", "client_name", "case_title", "case_type", "status", "consult_date", "next_check_date", "updated_at"]
    st.dataframe(df[show_cols] if not df.empty else df, use_container_width=True, hide_index=True)

    if not df.empty:
        selected = st.selectbox("更新・削除する案件", df["case_id"].tolist())
        row = get_cases()[get_cases()["case_id"] == selected].iloc[0]
        with st.form("case_edit"):
            new_title = st.text_input("案件名", clean(row["case_title"]))
            new_type = st.selectbox("案件種別", CASE_TYPE_OPTIONS, index=CASE_TYPE_OPTIONS.index(row["case_type"]) if row["case_type"] in CASE_TYPE_OPTIONS else 0)
            new_status = st.selectbox("状態", STATUS_OPTIONS, index=STATUS_OPTIONS.index(row["status"]) if row["status"] in STATUS_OPTIONS else 0)
            new_current_state = st.text_area("現在の状態", clean(row["current_state"]))
            new_house_state = st.text_area("住まい・空き家の状態", clean(row["house_state"]))
            new_cat_relation = st.text_area("猫との関係", clean(row["cat_relation"]))
            new_family_gap = st.text_area("家族間の温度差", clean(row["family_gap"]))
            new_pressure = st.text_area("急がされ感", clean(row["pressure"]))
            new_worries = st.text_area("心配ごと", clean(row["worries"]))
            new_not_decide = st.text_area("今は決めないこと", clean(row["not_decide"]))
            new_internal_memo = st.text_area("内部メモ", clean(row["internal_memo"]))
            new_next_check = st.text_area("次回確認", clean(row["next_check"]))
            new_next_hearing_items = st.text_area("次回ヒアリング項目", clean(row["next_hearing_items"]))
            new_hearing_missing = st.text_area("ヒアリング漏れ警告", clean(row["hearing_missing"]))
            new_do_not_do_now = st.text_area("今やらない方がいいこと", clean(row["do_not_do_now"]))
            current_next_date = pd.to_datetime(row["next_check_date"]).date() if pd.notna(row["next_check_date"]) else None
            new_next_check_date = st.date_input("次回確認日", value=current_next_date)
            new_final_memo = st.text_area("終了・最終メモ", clean(row["final_memo"]))
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
                hearing_missing=%(hearing_missing)s, do_not_do_now=%(do_not_do_now)s, next_check_date=%(next_check_date)s,
                final_memo=%(final_memo)s WHERE case_id=%(case_id)s
            """, {"updated_at": now_text(), "case_title": new_title, "case_type": new_type, "status": new_status,
                  "current_state": new_current_state, "house_state": new_house_state, "cat_relation": new_cat_relation,
                  "family_gap": new_family_gap, "pressure": new_pressure, "worries": new_worries, "not_decide": new_not_decide,
                  "internal_memo": new_internal_memo, "next_check": new_next_check, "next_hearing_items": new_next_hearing_items,
                  "hearing_missing": new_hearing_missing, "do_not_do_now": new_do_not_do_now, "next_check_date": new_next_check_date,
                  "final_memo": new_final_memo, "case_id": selected})
            if before_status != new_status:
                history_id = make_id("hist")
                execute("""
                    INSERT INTO history
                    (history_id, case_id, client_id, created_at, record_date, record_type, before_status, after_status, record, next_action, internal_memo)
                    VALUES (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, '状態変更', %(before_status)s, %(after_status)s, %(record)s, %(next_action)s, %(internal_memo)s)
                """, {"history_id": history_id, "case_id": selected, "client_id": row["client_id"], "created_at": now_text(), "record_date": today_text(), "before_status": before_status, "after_status": new_status, "record": f"状態を {before_status} から {new_status} に変更", "next_action": new_next_check, "internal_memo": "案件更新時に自動記録"})
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

    if can_write():
        with st.expander("登録", expanded=True):
            with st.form(f"{table_name}_create"):
                values = {}
                for key, label, kind in fields:
                    values[key] = st.text_area(label) if kind == "area" else st.text_input(label)
                ok = st.form_submit_button("登録する")
            if ok:
                new_id = make_id(id_col.replace("_id", ""))
                cols = [id_col, "case_id", "client_id", "created_at", "updated_at"] + [x[0] for x in fields]
                params = {id_col: new_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "updated_at": now_text(), **values}
                execute(f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({', '.join([f'%({c})s' for c in cols])})", params)
                log_action("create", table_name, new_id, f"{title}登録")
                st.success("登録しました。")
                st.rerun()

    df = fetch_df(f"SELECT * FROM {table_name} WHERE case_id=%(case_id)s ORDER BY created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)

    if can_write() and not df.empty:
        selected = st.selectbox("更新・削除するID", df[id_col].tolist(), key=f"{table_name}_select")
        row = df[df[id_col] == selected].iloc[0]
        with st.form(f"{table_name}_edit"):
            values = {}
            for key, label, kind in fields:
                values[key] = st.text_area(label, clean(row[key])) if kind == "area" else st.text_input(label, clean(row[key]))
            delete_confirm = st.checkbox("削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力", key=f"{table_name}_delete_text")
            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")
        if update:
            set_clause = ", ".join([f"{k}=%({k})s" for k, _, _ in fields]) + ", updated_at=%(updated_at)s"
            values["updated_at"] = now_text()
            values["id"] = selected
            execute(f"UPDATE {table_name} SET {set_clause} WHERE {id_col}=%(id)s", values)
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
    if can_write():
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
                    INSERT INTO history (history_id, case_id, client_id, created_at, record_date, record_type, record, next_action, internal_memo)
                    VALUES (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(record)s, %(next_action)s, %(internal_memo)s)
                """, {"history_id": history_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "record_date": record_date, "record_type": record_type, "record": record, "next_action": next_action, "internal_memo": internal_memo})
                execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
                log_action("create", "history", history_id, "相談履歴登録")
                st.success("相談履歴を登録しました。")
                st.rerun()
    df = fetch_df("SELECT * FROM history WHERE case_id=%(case_id)s ORDER BY record_date DESC, created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_line_messages():
    st.subheader("LINEメモ")
    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
        return
    selected_label = st.selectbox("対象案件", case_labels)
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)

    templates = fetch_df("SELECT template_name, template_text FROM line_templates WHERE active=1 ORDER BY category, template_name")
    template_text = ""
    if not templates.empty:
        t_label = st.selectbox("テンプレート呼び出し", ["使用しない"] + templates["template_name"].tolist())
        if t_label != "使用しない":
            template_text = templates[templates["template_name"] == t_label]["template_text"].iloc[0]

    if can_write():
        with st.form("line_message_create"):
            to_target = st.text_input("送信先・対象")
            message_text = st.text_area("送信文", value=template_text)
            send_status = st.selectbox("状態", ["下書き", "送信済", "返信あり", "保留"])
            response_memo = st.text_area("返信・反応メモ")
            ok = st.form_submit_button("登録する")
        if ok:
            message_id = make_id("line")
            execute("""
                INSERT INTO line_messages
                (message_id, case_id, client_id, created_at, updated_at, created_by, to_target, message_text, send_status, response_memo)
                VALUES (%(message_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(created_by)s, %(to_target)s, %(message_text)s, %(send_status)s, %(response_memo)s)
            """, {"message_id": message_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "updated_at": now_text(), "created_by": st.session_state.get("login_id", ""), "to_target": to_target, "message_text": message_text, "send_status": send_status, "response_memo": response_memo})
            log_action("create", "line_messages", message_id, "LINEメモ登録")
            st.success("LINEメモを登録しました。")
            st.rerun()
    df = fetch_df("SELECT * FROM line_messages WHERE case_id=%(case_id)s ORDER BY created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_line_templates():
    st.subheader("LINEテンプレート")
    if can_write():
        with st.form("line_template_create"):
            template_name = st.text_input("テンプレート名")
            category = st.text_input("カテゴリ")
            template_text = st.text_area("本文")
            memo = st.text_area("メモ")
            ok = st.form_submit_button("登録する")
        if ok:
            if not template_name.strip():
                st.error("テンプレート名を入力してください。")
            else:
                template_id = make_id("tmpl")
                execute("""
                    INSERT INTO line_templates (template_id, created_at, updated_at, template_name, category, template_text, active, memo)
                    VALUES (%(template_id)s, %(created_at)s, %(updated_at)s, %(template_name)s, %(category)s, %(template_text)s, 1, %(memo)s)
                """, {"template_id": template_id, "created_at": now_text(), "updated_at": now_text(), "template_name": template_name, "category": category, "template_text": template_text, "memo": memo})
                log_action("create", "line_templates", template_id, "LINEテンプレート登録")
                st.success("登録しました。")
                st.rerun()
    df = fetch_df("SELECT * FROM line_templates ORDER BY category, template_name")
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_attachments():
    st.subheader("添付画像管理")
    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に案件を登録してください。")
        return
    selected_label = st.selectbox("対象案件", case_labels)
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)
    if can_write():
        uploaded = st.file_uploader("画像・PDF等を登録", type=None)
        memo = st.text_area("添付メモ")
        if st.button("添付ファイルを登録") and uploaded is not None:
            data = uploaded.getvalue()
            attachment_id = make_id("att")
            execute("""
                INSERT INTO attachments (attachment_id, case_id, client_id, created_at, file_name, mime_type, file_size, file_data, memo)
                VALUES (%(attachment_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(file_name)s, %(mime_type)s, %(file_size)s, %(file_data)s, %(memo)s)
            """, {"attachment_id": attachment_id, "case_id": case_id, "client_id": client_id, "created_at": now_text(), "file_name": uploaded.name, "mime_type": uploaded.type, "file_size": len(data), "file_data": data, "memo": memo})
            log_action("create", "attachments", attachment_id, "添付ファイル登録")
            st.success("登録しました。")
            st.rerun()
    df = fetch_df("SELECT attachment_id, created_at, file_name, mime_type, file_size, memo FROM attachments WHERE case_id=%(case_id)s ORDER BY created_at DESC", {"case_id": case_id})
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty:
        selected = st.selectbox("ダウンロードする添付ID", df["attachment_id"].tolist())
        row = fetch_one("SELECT file_name, mime_type, file_data FROM attachments WHERE attachment_id=%(id)s", {"id": selected})
        if row:
            st.download_button("添付ファイルをダウンロード", bytes(row["file_data"]), file_name=row["file_name"], mime=row["mime_type"] or "application/octet-stream")


def render_backup():
    st.subheader("バックアップ・出力")
    st.caption("全テーブルをCSV ZIPまたはExcelで出力します。")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("全テーブルZIPバックアップ", download_zip_all_tables(), file_name=f"nyantomo_backup_{today_text()}.zip", mime="application/zip")
    with col2:
        st.download_button("全テーブルExcel出力", excel_all_tables(), file_name=f"nyantomo_export_{today_text()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_users():
    st.subheader("ログイン設定")
    if not can_admin():
        st.warning("管理者のみ利用できます。")
        return
    df = fetch_df("SELECT user_id, created_at, updated_at, login_id, role, display_name, active FROM app_users ORDER BY created_at")
    st.dataframe(df, use_container_width=True, hide_index=True)
    with st.form("user_create"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        role = st.selectbox("権限", [ROLE_VIEWER, ROLE_STAFF, ROLE_ADMIN])
        display_name = st.text_input("表示名")
        ok = st.form_submit_button("追加する")
    if ok:
        user_id = make_id("user")
        execute("""
            INSERT INTO app_users (user_id, created_at, updated_at, login_id, password_hash, role, display_name, active)
            VALUES (%(user_id)s, %(created_at)s, %(updated_at)s, %(login_id)s, %(password_hash)s, %(role)s, %(display_name)s, 1)
        """, {"user_id": user_id, "created_at": now_text(), "updated_at": now_text(), "login_id": login_id, "password_hash": hash_password(password), "role": role, "display_name": display_name or login_id})
        log_action("create", "app_users", user_id, "ユーザー追加")
        st.success("追加しました。")
        st.rerun()


def render_data_check():
    st.subheader("データ確認")
    tabs = st.tabs([label for _, label in TABLES])
    for tab, (table, label) in zip(tabs, TABLES):
        with tab:
            df = fetch_df(f"SELECT * FROM {table} ORDER BY 1")
            if table == "attachments" and "file_data" in df.columns:
                df = df.drop(columns=["file_data"])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(f"{label}CSVダウンロード", df.to_csv(index=False).encode("utf-8-sig"), file_name=f"{table}.csv", mime="text/csv", key=f"csv_{table}")


if not has_database_url():
    show_db_setup_screen()

try:
    init_db()
except Exception as e:
    st.title(f"🐾 {APP_TITLE} {APP_VERSION}")
    st.error("PostgreSQLへの接続または初期化に失敗しました。")
    st.exception(e)
    st.stop()

require_login()

st.title(f"🐾 {APP_TITLE} {APP_VERSION}")
st.caption(APP_CAPTION)

menu = st.sidebar.radio("メニュー", get_available_menus())
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
    related_card_page("properties", "property_id", "空き家カード", [("property_name", "物件名", "text"), ("address", "住所", "text"), ("property_status", "物件状態", "text"), ("vacant_status", "空き家状態", "text"), ("key_hold", "鍵預かり", "text"), ("neighborhood", "近隣状況", "text"), ("visit_frequency", "確認頻度", "text"), ("memo", "メモ", "area")])
elif menu == "猫情報カード":
    related_card_page("cats", "cat_id", "猫情報カード", [("cat_name", "猫の名前", "text"), ("age", "年齢", "text"), ("sex", "性別", "text"), ("health_memo", "健康メモ", "area"), ("life_status", "生活状況", "area"), ("future_plan", "今後の方針", "area"), ("memo", "メモ", "area")])
elif menu == "家族関係メモ":
    related_card_page("family", "family_id", "家族関係メモ", [("name", "氏名", "text"), ("relation", "続柄", "text"), ("contact_ok", "連絡可否", "text"), ("temperature", "温度感", "text"), ("memo", "メモ", "area")])
elif menu == "AI要約メモ":
    related_card_page("ai_summaries", "summary_id", "AI要約メモ", [("summary_type", "要約種別", "text"), ("source_text", "元メモ", "area"), ("summary_text", "要約", "area"), ("memo", "備考", "area")])
elif menu == "LINEメモ":
    render_line_messages()
elif menu == "LINEテンプレート":
    render_line_templates()
elif menu == "添付画像管理":
    render_attachments()
elif menu == "バックアップ・出力":
    render_backup()
elif menu == "ログイン設定":
    render_users()
elif menu == "データ確認":
    render_data_check()
