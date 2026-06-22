# app.py
import html
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    APP_TITLE, APP_CAPTION, ADMIN_ROLE, STAFF_ROLE, VIEWER_ROLE,
    ADMIN_MENUS, STAFF_MENUS, VIEWER_MENUS,
    STATUS_OPTIONS, CASE_TYPE_OPTIONS, AGE_OPTIONS, CONTACT_OPTIONS, POSITION_OPTIONS, TABLES
)
from db import has_database_url, init_db, execute, fetch_df, fetch_one
from core.utils import (
    make_id,
    now_jst,
    today_jst,
    now_text,
    today_text,
    normalize_text,
    date_or_none,
    ymd_selectbox_date,
)
from core.auth import (
    hash_password,
    verify_password,
    clear_app_cache,
    can_write,
    can_admin,
    show_db_setup_screen,
    login_screen,
    require_login,
    logout_button,
)
from core.audit import log_action
from ui.styles import apply_dashboard_css
from ui.components import (
    safe_df_display,
    ny_card_status_icon,
    ny_pending_status_icon,
    ny_pick_summary,
    ny_html,
    render_nyantomo_card_tile,
    resource_display,
    resource_symbol,
    resource_text,
)
from services.backup_service import (
    BACKUP_DIR,
    DEFAULT_AUTO_BACKUP_HOURS,
    DEFAULT_BACKUP_KEEP,
    get_secret_value,
    get_backup_tables,
    build_csv_zip_bytes,
    save_backup_file,
    cleanup_old_backups,
    maybe_run_auto_backup,
)
from services.ai_service import (
    get_openai_api_key,
    get_openai_model,
    build_case_ai_source,
    build_ai_prompt,
    call_openai_summary,
    save_ai_summary,
    build_guardian_ai_source,
    build_guardian_ai_prompt,
    build_guardian_card_ai_prompt,
)
from services.report_service import (
    build_client_report_pdf_bytes,
    build_guardian_report_pdf_bytes,
)
from db_schema.extension_schema import ensure_extension_tables
from db_schema.assistant_schema import ensure_assistant_tables

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

DEFAULT_CACHE_TTL_SECONDS = 30
# ============================================================
# にゃんとも相談管理 Ver2.0：カード整理OS 設定
# ============================================================

# Ver2.1：カード整理で使うカード種別は、現時点では3種類に限定します。
# 相談判断用の上位カードではなく、登録済みの基本情報カードへ確実に紐付けるための分類です。
NYANTOMO_CARD_TYPES = [
    "猫情報カード",
    "空き家カード",
    "家族情報",
]

# 旧Verで保存されたカード種別も、表示・紐付け時に新名称へ寄せます。
NYANTOMO_CARD_TYPE_ALIASES = {
    "猫カード": "猫情報カード",
    "住まいカード": "空き家カード",
    "家族カード": "家族情報",
    "家族関係メモ": "家族情報",
}

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


# ============================================================
# Ver3.4：生活制度候補整理 設定
# ------------------------------------------------------------
# 補助金だけでなく、空き家・高齢者・猫・相続の相談で出てくる
# 「確認候補」を横断的に整理します。
# 使える／必要／対象と断定せず、候補・未確認・次回確認として扱います。
# ============================================================

POLICY_DOMAIN_OPTIONS = [
    "空き家",
    "高齢者",
    "猫",
    "相続",
    "横断・その他",
]

POLICY_CATEGORY_OPTIONS = [
    # 空き家
    "空き家改修補助",
    "解体補助",
    "耐震診断・耐震改修補助",
    "住宅セーフティネット関連",
    "固定資産税・特定空家関連",
    # 高齢者
    "介護保険住宅改修",
    "福祉用具",
    "高齢者住宅",
    "地域包括・介護相談",
    # 猫
    "猫の預かり先候補",
    "動物病院",
    "ペット信託",
    "任意後見",
    # 相続
    "遺言",
    "家族信託",
    "相続人調査",
    "遺産分割・相続手続き",
    # その他
    "その他制度・確認候補",
]

POLICY_CATEGORY_DOMAIN_MAP = {
    "空き家改修補助": "空き家",
    "解体補助": "空き家",
    "耐震診断・耐震改修補助": "空き家",
    "住宅セーフティネット関連": "空き家",
    "固定資産税・特定空家関連": "空き家",
    "介護保険住宅改修": "高齢者",
    "福祉用具": "高齢者",
    "高齢者住宅": "高齢者",
    "地域包括・介護相談": "高齢者",
    "猫の預かり先候補": "猫",
    "動物病院": "猫",
    "ペット信託": "猫",
    "任意後見": "猫",
    "遺言": "相続",
    "家族信託": "相続",
    "相続人調査": "相続",
    "遺産分割・相続手続き": "相続",
    "その他制度・確認候補": "横断・その他",
}

POLICY_STATUS_OPTIONS = [
    "候補",
    "次回確認",
    "自治体確認中",
    "関係先確認中",
    "専門職確認中",
    "対象外の可能性",
    "申請準備",
    "保留",
    "終了",
]

POLICY_PRIORITY_OPTIONS = ["低", "中", "高", "要確認"]

POLICY_DISCLAIMER = (
    "※この画面は『使える制度・必要な手続きの断定』ではなく、正式確認のための候補整理です。"
    "制度・補助金は自治体ごとに条件、年度予算、受付期間、対象工事、所有者要件が異なります。"
    "後見・信託・遺言・相続・医療・介護・不動産に関する最終判断は、必ず最新資料・窓口・関係専門職で確認してください。"
)

POLICY_CANDIDATE_TEMPLATES = {
    # 空き家
    "空き家改修補助": {
        "keywords": ["改修", "リフォーム", "修繕", "直したい", "貸したい", "住みたい", "活用"],
        "check_items": "所在地市区町村／空き家期間／所有者／改修目的／工事内容／見積書／市内業者要件／着工前申請か",
        "caution": "着工後申請は対象外となる制度が多いため、工事契約・着工前に確認する。",
        "next_action": "自治体・支援機関・関係専門職で、最新情報と対象要件を確認する。",
    },
    "解体補助": {
        "keywords": ["解体", "取り壊し", "老朽", "危険", "倒れそう", "更地", "壊す", "除却"],
        "check_items": "建物状態／老朽度／近隣への危険／所有者／相続登記状況／見積書／事前調査／固定資産税影響",
        "caution": "解体後に固定資産税や土地利用の影響が出ることがあるため、急いで決めない。",
        "next_action": "解体の前に、補助対象・税影響・相続登記状況を整理する。",
    },
    "耐震診断・耐震改修補助": {
        "keywords": ["耐震", "昭和", "旧耐震", "1981", "1981年", "地震", "倒壊", "古い家"],
        "check_items": "建築年／木造か／過去の耐震診断歴／建築確認資料／所有者／居住予定／自治体の診断制度",
        "caution": "旧耐震の可能性がある場合は、改修や活用判断の前に耐震診断の候補を確認する。",
        "next_action": "建築年と自治体の耐震診断・改修補助の有無を確認する。",
    },
    "住宅セーフティネット関連": {
        "keywords": ["高齢者", "賃貸", "貸す", "住まい", "住宅確保", "セーフティネット", "見守り", "入居"],
        "check_items": "賃貸化の意向／住宅確保要配慮者への提供可能性／登録住宅制度／改修必要性／管理体制",
        "caution": "賃貸化は収益判断・管理責任・入居者支援が絡むため、制度候補として慎重に整理する。",
        "next_action": "登録住宅制度・改修支援・管理体制を確認候補として整理する。",
    },
    "固定資産税・特定空家関連": {
        "keywords": ["固定資産税", "特定空家", "管理不全", "勧告", "指導", "近隣", "苦情", "雑草"],
        "check_items": "自治体からの通知／現地状態／近隣苦情／草木・破損・越境／管理履歴／写真記録",
        "caution": "税務判断や行政処分対応は断定せず、通知文書と自治体窓口確認を優先する。",
        "next_action": "通知文書・現地写真・管理履歴をそろえ、自治体窓口確認の候補にする。",
    },

    # 高齢者
    "介護保険住宅改修": {
        "keywords": ["要介護", "要支援", "ケアマネ", "介護保険", "住宅改修", "手すり", "段差解消"],
        "check_items": "要介護・要支援認定／ケアマネ／住宅改修理由書／対象工事／事前申請／支給限度基準額",
        "caution": "原則として事前申請が必要。行政書士単独で判断せず、ケアマネ・自治体窓口と確認する。",
        "next_action": "ケアマネまたは自治体介護保険窓口へ確認する候補として整理する。",
    },
    "福祉用具": {
        "keywords": ["福祉用具", "歩行器", "車椅子", "ベッド", "手すり", "転倒", "レンタル", "購入"],
        "check_items": "要介護認定／ケアマネ有無／必要な用具／レンタルか購入か／住環境／転倒リスク",
        "caution": "福祉用具の適否は身体状況や介護保険制度が関係するため、ケアマネ等へ確認する。",
        "next_action": "ケアマネ・福祉用具専門相談員への確認候補として整理する。",
    },
    "高齢者住宅": {
        "keywords": ["施設", "入居", "老人ホーム", "サ高住", "高齢者住宅", "一人暮らし", "住み替え", "見守り"],
        "check_items": "本人希望／予算／介護度／医療対応／猫との関係／保証人／空き家になる住まい／見学予定",
        "caution": "入居判断は本人の意思・家族関係・費用・猫の行き先と絡むため、急いで決めない。",
        "next_action": "住み替え候補・猫の行き先・空き家管理の3点を分けて確認する。",
    },
    "地域包括・介護相談": {
        "keywords": ["包括", "地域包括", "介護相談", "認知症", "見守り", "独居", "一人暮らし", "ケアマネ"],
        "check_items": "本人住所地／相談者との関係／本人同意／困りごと／緊急度／既存支援者／医療・介護状況",
        "caution": "支援につなぐ場合も、本人の意思と緊急性を分けて整理する。",
        "next_action": "地域包括支援センター等への相談候補として整理する。",
    },

    # 猫
    "猫の預かり先候補": {
        "keywords": ["猫", "預かり", "保護", "入院", "施設", "世話", "引き取り", "ペットホテル"],
        "check_items": "猫の頭数／年齢／持病／性格／ワクチン／避妊去勢／預かり期間／費用／緊急連絡先",
        "caution": "預かり先は制度ではなく生活支援・民間連携の候補。安易に確定せず、猫の状態と費用を確認する。",
        "next_action": "動物病院・親族・預かり先候補・保護団体等を分けて整理する。",
    },
    "動物病院": {
        "keywords": ["動物病院", "ワクチン", "通院", "持病", "薬", "診察", "去勢", "避妊", "健康"],
        "check_items": "かかりつけ医／診療記録／薬／ワクチン／緊急時対応／預かり可否／連絡先",
        "caution": "医療判断は行わず、記録と連絡先の整理にとどめる。",
        "next_action": "かかりつけ動物病院の情報を猫カードへ整理する。",
    },
    "ペット信託": {
        "keywords": ["ペット信託", "信託", "猫の将来", "お金を残す", "世話人", "受託者", "もしもの時"],
        "check_items": "委託者／受託者候補／世話人候補／信託財産／猫の生活費／監督者／公正証書化の希望",
        "caution": "信託は契約設計が必要。制度説明はできても、最終設計は本人意思・関係者確認を踏まえる。",
        "next_action": "猫の生活費・世話人・受託者候補を分けて確認する。",
    },
    "任意後見": {
        "keywords": ["任意後見", "後見", "認知症", "判断能力", "将来不安", "施設入所", "財産管理", "見守り契約"],
        "check_items": "本人意思／判断能力の状態／任意後見受任者候補／見守り契約／財産管理／猫の世話との関係",
        "caution": "後見の要否は断定せず、本人の意思確認と専門職・公証役場等の確認候補として扱う。",
        "next_action": "任意後見・見守り契約・猫の将来を分けて整理する。",
    },

    # 相続
    "遺言": {
        "keywords": ["遺言", "公正証書", "遺贈", "相続", "財産を残す", "死後", "猫に残す", "遺言執行"],
        "check_items": "本人意思／相続人候補／財産概要／猫に関する希望／遺言執行者／公正証書希望／遺留分配慮",
        "caution": "遺言内容の良し悪しを断定せず、本人意思と財産・相続人の整理を優先する。",
        "next_action": "財産一覧・相続人候補・猫への希望を分けて確認する。",
    },
    "家族信託": {
        "keywords": ["家族信託", "民事信託", "信託", "認知症対策", "財産管理", "親の家", "不動産管理"],
        "check_items": "委託者／受託者候補／信託財産／目的／家族関係／不動産の有無／専門職連携",
        "caution": "家族信託は高度な設計が必要。行政書士単独で完結させず、司法書士・税理士等との連携候補にする。",
        "next_action": "家族関係・財産・目的を整理し、必要に応じ専門職確認候補とする。",
    },
    "相続人調査": {
        "keywords": ["相続人", "戸籍", "相続関係", "兄弟", "子ども", "親族", "誰が相続", "法定相続人"],
        "check_items": "被相続人／死亡日／本籍地情報／戸籍取得範囲／相続人候補／連絡可能性／関係性",
        "caution": "相続人確定には戸籍確認が必要。聞き取りだけで断定しない。",
        "next_action": "戸籍収集・相続関係説明図作成の候補として整理する。",
    },
    "遺産分割・相続手続き": {
        "keywords": ["遺産分割", "協議書", "相続手続き", "預金", "不動産", "名義変更", "相続登記"],
        "check_items": "相続人確定／財産一覧／遺言有無／不動産有無／相続登記状況／紛争性／専門職連携",
        "caution": "紛争性がある場合は弁護士、登記は司法書士、税務は税理士の確認候補とする。",
        "next_action": "相続人・財産・紛争性・専門職連携の必要性を整理する。",
    },
    "その他制度・確認候補": {
        "keywords": ["制度", "補助", "助成", "相談", "窓口", "申請", "支援", "確認"],
        "check_items": "相談テーマ／所在地／本人意思／緊急度／関係者／確認先／期限／必要資料",
        "caution": "制度名が未確定な段階では、無理に制度へ当てはめず、確認候補として置く。",
        "next_action": "制度名を決めつけず、自治体・専門職・関係機関の確認先候補を整理する。",
    },
}

# Ver2.1：判断カードと基本情報カードの紐付け
# 猫情報カード・空き家カード・家族関係メモは「基本情報」、
# Ver2.xカードは「悩み・判断・保留」を整理する上位カードとして扱います。
RELATED_BASE_CARD_MAP = {
    "猫情報カード": {
        "table": "cats",
        "id_col": "cat_id",
        "label_sql": "COALESCE(NULLIF(cat_name,''), '猫情報') || COALESCE('｜' || NULLIF(age,''), '') || COALESCE('｜' || NULLIF(sex,''), '')",
        "label": "猫情報カード",
    },
    "空き家カード": {
        "table": "properties",
        "id_col": "property_id",
        "label_sql": "COALESCE(NULLIF(property_name,''), '物件') || COALESCE('｜' || NULLIF(address,''), '')",
        "label": "空き家カード",
    },
    "家族情報": {
        "table": "family",
        "id_col": "family_id",
        "label_sql": "COALESCE(NULLIF(name,''), '家族') || COALESCE('｜' || NULLIF(relation,''), '') || COALESCE('｜' || NULLIF(temperature,''), '')",
        "label": "家族情報",
    },
    # 旧名称互換
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
        "label": "家族情報",
    },
}













def normalize_card_type_name(card_type):
    """旧名称を現在のカード種別名へ寄せる。"""
    card_type = normalize_text(card_type)
    return NYANTOMO_CARD_TYPE_ALIASES.get(card_type, card_type)














@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_clients():
    return fetch_df("""
        SELECT client_id, created_at, updated_at, name, age_group, area, contact_method, position, note
        FROM clients
        ORDER BY created_at DESC NULLS LAST
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
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


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
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


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
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


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_counts():
    return fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM clients) AS clients_count,
            (SELECT COUNT(*) FROM cases) AS cases_count,
            (SELECT COUNT(*) FROM cases WHERE COALESCE(status,'') <> '終了') AS open_cases_count,
            (SELECT COUNT(*) FROM cases
                WHERE COALESCE(status,'') <> '終了'
                AND next_check_date IS NOT NULL
                AND next_check_date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date + INTERVAL '7 days')) AS need_check_count
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_need_check():
    return fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.next_check_date, c.next_check
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND c.next_check_date IS NOT NULL
          AND c.next_check_date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date + INTERVAL '7 days')
        ORDER BY c.next_check_date ASC, c.updated_at DESC
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_hearing():
    return fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.hearing_missing, c.next_hearing_items
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND NULLIF(TRIM(COALESCE(c.hearing_missing,'')), '') IS NOT NULL
        ORDER BY c.updated_at DESC
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_do_not():
    return fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.status, c.do_not_do_now, c.not_decide
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND NULLIF(TRIM(COALESCE(c.do_not_do_now,'')), '') IS NOT NULL
        ORDER BY c.updated_at DESC
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_recent_cases():
    return fetch_df("""
        SELECT cl.name AS client_name, c.case_title, c.case_type, c.status, c.consult_date, c.updated_at
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC LIMIT 20
    """)


@st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_dashboard_status_counts():
    return fetch_df("""
        SELECT COALESCE(status, '未設定') AS status, COUNT(*) AS 件数
        FROM cases GROUP BY COALESCE(status, '未設定') ORDER BY 件数 DESC
    """)


def case_to_client(case_id):
    row = fetch_one("SELECT client_id FROM cases WHERE case_id = %(case_id)s", {"case_id": case_id})
    return row["client_id"] if row else ""








def render_dashboard():
    apply_dashboard_css()

    st.subheader("ダッシュボード")

    counts = get_dashboard_counts()

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

    need_check = get_dashboard_need_check()
    hearing = get_dashboard_hearing()
    do_not = get_dashboard_do_not()

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
        recent = get_dashboard_recent_cases()
        safe_df_display(
            recent,
            "案件がありません。",
            ["client_name", "case_title", "case_type", "status", "consult_date", "updated_at"],
            height=260
        )

    with bottom_right:
        st.markdown('<div class="ny-section-title">状態別件数</div>', unsafe_allow_html=True)
        status_df = get_dashboard_status_counts()
        safe_df_display(status_df, "案件がありません。", ["status", "件数"], height=210)

        st.markdown('<div class="ny-section-title">要確認案件</div>', unsafe_allow_html=True)
        safe_df_display(
            need_check,
            "要確認案件はありません。",
            ["client_name", "case_title", "status", "next_check_date", "next_check"],
            height=180
        )

    st.markdown('<div class="ny-footer">© にゃんとも相談管理 Ver3.4 生活制度候補整理対応｜安定・安全・効率的な相談業務をサポートします 🐾</div>', unsafe_allow_html=True)



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
            clear_app_cache()
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
            clear_app_cache()
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM clients WHERE client_id=%(client_id)s", {"client_id": selected})
                log_action("delete", "clients", selected, "相談者削除")
                st.success("相談者を削除しました。")
                clear_app_cache()
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
            consult_date = st.date_input("相談日", today_jst())
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
                clear_app_cache()
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
            clear_app_cache()
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM cases WHERE case_id=%(case_id)s", {"case_id": selected})
                log_action("delete", "cases", selected, "案件削除")
                st.success("案件を削除しました。")
                clear_app_cache()
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
        clear_app_cache()
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
            clear_app_cache()
            st.rerun()
        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute(f"DELETE FROM {table_name} WHERE {id_col}=%(id)s", {"id": selected})
                log_action("delete", table_name, selected, f"{title}削除")
                st.success("削除しました。")
                clear_app_cache()
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
        record_date = st.date_input("記録日", today_jst())
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
            clear_app_cache()
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
        clear_app_cache()
        st.rerun()

    df = fetch_df("SELECT * FROM line_templates ORDER BY updated_at DESC NULLS LAST, created_at DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty and can_write():
        selected = st.selectbox("削除するテンプレートID", df["template_id"].tolist())
        if st.button("選択テンプレートを削除"):
            execute("DELETE FROM line_templates WHERE template_id=%(id)s", {"id": selected})
            log_action("delete", "line_templates", selected, "LINEテンプレート削除")
            st.success("削除しました。")
            clear_app_cache()
            st.rerun()



# ============================================================
# 自動バックアップ
# ============================================================















# ============================================================
# AI要約連携
# ============================================================












# ============================================================
# 相談者向けA4レポートPDF出力
# ============================================================












# ============================================================
# 後見整理レポートPDF出力 Ver3.1
# ============================================================




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
    card_type = normalize_card_type_name(card_type)
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
    st.caption("登録済みの基本情報カード（猫情報カード・空き家カード・家族情報）へ、気になることや次回確認事項を紐付けて整理します。")

    case_id, client_id = get_case_selector("consultation_cards_case")
    if not case_id:
        return

    st.markdown("### カード登録")
    st.info("カード種別を選ぶと、同じ案件に登録済みの基本情報カードだけを選べます。表示されない場合は、先に左メニューの『猫情報カード』『空き家カード』『家族関係メモ』で登録してください。")

    # Streamlit の form 内では selectbox の変更だけでは再描画されないため、
    # カード種別と紐付け先は form の外に出しています。
    # これにより「カード種別を選んでも登録済みカードが選べない」問題を解消します。
    c1, c2 = st.columns(2)
    with c1:
        card_type = st.selectbox("カード種別", NYANTOMO_CARD_TYPES, key="consultation_card_create_type")
    with c2:
        card_status = st.selectbox("状態", NYANTOMO_CARD_STATUS_OPTIONS, key="consultation_card_create_status")

    related_mapping, related_labels, related_table, base_label = get_related_base_options(card_type, case_id)
    related_select = st.selectbox(
        f"紐付ける登録済みカード（{base_label}）",
        related_labels,
        key="consultation_card_create_related"
    )
    if related_labels == ["紐付けなし"]:
        st.warning(f"この案件には、まだ紐付け可能な『{base_label}』が登録されていません。")

    with st.form("consultation_card_create"):
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
            clear_app_cache()
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

    if df is not None and not df.empty:
        df["card_type"] = df["card_type"].apply(normalize_card_type_name)

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

        edit_current_type = normalize_card_type_name(row.get("card_type", ""))
        if edit_current_type not in NYANTOMO_CARD_TYPES:
            edit_current_type = NYANTOMO_CARD_TYPES[0]

        e1, e2 = st.columns(2)
        with e1:
            new_card_type = st.selectbox(
                "カード種別",
                NYANTOMO_CARD_TYPES,
                index=NYANTOMO_CARD_TYPES.index(edit_current_type),
                key="consultation_card_edit_type"
            )
        with e2:
            new_card_status = st.selectbox(
                "状態",
                NYANTOMO_CARD_STATUS_OPTIONS,
                index=NYANTOMO_CARD_STATUS_OPTIONS.index(row["card_status"]) if row["card_status"] in NYANTOMO_CARD_STATUS_OPTIONS else 0,
                key="consultation_card_edit_status"
            )

        edit_mapping, edit_labels, edit_related_table, edit_base_label = get_related_base_options(new_card_type, case_id)
        edit_default_label = find_related_label(edit_labels, edit_mapping, row.get("related_id", ""))
        new_related_select = st.selectbox(
            f"紐付ける登録済みカード（{edit_base_label}）",
            edit_labels,
            index=edit_labels.index(edit_default_label) if edit_default_label in edit_labels else 0,
            key="consultation_card_edit_related"
        )
        if edit_labels == ["紐付けなし"]:
            st.warning(f"この案件には、まだ紐付け可能な『{edit_base_label}』が登録されていません。")

        with st.form("consultation_card_edit"):
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
            clear_app_cache()
            st.rerun()

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM consultation_cards WHERE card_id=%(card_id)s", {"card_id": selected})
                log_action("delete", "consultation_cards", selected, "Ver2.1カード削除")
                st.success("カードを削除しました。")
                clear_app_cache()
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
            clear_app_cache()
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
            clear_app_cache()
            st.rerun()

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
            else:
                execute("DELETE FROM pending_items WHERE pending_id=%(pending_id)s", {"pending_id": selected})
                log_action("delete", "pending_items", selected, "Ver2.0保留事項削除")
                st.success("保留事項を削除しました。")
                clear_app_cache()
                st.rerun()












def render_card_os_overview():
    st.subheader("Ver2.4｜カードOS俯瞰")
    st.caption("件数表ではなく、相談者の前に並んでいるカードを1枚ずつ見える化します。相談の入口で『いま何が机の上にあるか』を確認する画面です。")

    st.markdown("""
    <style>
    .ny-os-card {
        background: #ffffff;
        border: 1px solid #e8edf5;
        border-radius: 18px;
        padding: 17px 18px;
        margin-bottom: 12px;
        box-shadow: 0 7px 18px rgba(30, 41, 59, 0.06);
        min-height: 118px;
    }
    .ny-os-title {
        font-weight: 900;
        color: #172033;
        font-size: 1.08rem;
        margin-bottom: 7px;
    }
    .ny-os-icon {
        font-size: 1.22rem;
        margin-right: 4px;
    }
    .ny-os-headline {
        font-size: 1.05rem;
        font-weight: 800;
        color: #334155;
        line-height: 1.45;
        margin-bottom: 8px;
    }
    .ny-os-status {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        color: #475569;
        font-size: 0.86rem;
        font-weight: 800;
        margin-bottom: 8px;
    }
    .ny-os-detail {
        color: #64748b;
        font-size: 0.9rem;
        line-height: 1.5;
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
    .ny-os-divider {
        border: none;
        border-top: 1px dashed #d7dee8;
        margin: 14px 0 14px;
    }
    .ny-os-mini {
        color: #64748b;
        font-size: 0.88rem;
        line-height: 1.5;
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
    🐾 この画面は、相談者の悩みを“件数”ではなく“1枚ずつのカード”として眺めるための画面です。<br>
    🟥 気になる　🟧 家族・専門家・次回確認待ち　🟨 検討・保留　🟩 整理済 の目安で確認します。
    </div>
    """, unsafe_allow_html=True)

    def card_sort_key(row):
        status = normalize_text(row.get("card_status", ""))
        order = {"気になる": 1, "検討中": 2, "保留": 3, "整理済": 4}
        return order.get(status, 9)

    st.markdown("### いま机の上に並んでいるカード")
    if card_df.empty:
        st.info("カードはまだ登録されていません。『Ver2.0｜カード整理』から登録してください。")
    else:
        # グループ別の件数表ではなく、優先度順に1枚ずつ縦に並べる
        sorted_rows = sorted([row for _, row in card_df.iterrows()], key=card_sort_key)
        for idx, row in enumerate(sorted_rows):
            icon = ny_card_status_icon(row.get("card_status", ""))
            title = normalize_text(row.get("card_type", "")).replace("カード", "") or "カード"
            headline = ny_pick_summary(row.get("concern", ""), row.get("current_state", ""), row.get("client_words", ""), max_len=48)
            detail_parts = []
            related_label = normalize_text(row.get("related_label", ""))
            client_words = normalize_text(row.get("client_words", ""))
            unknown = normalize_text(row.get("unknown_items", ""))
            next_check = normalize_text(row.get("next_check_items", ""))
            related_people = normalize_text(row.get("related_people_places", ""))
            if related_label:
                detail_parts.append(f"基本情報：{related_label}")
            if client_words:
                detail_parts.append(f"相談者の言葉：{ny_pick_summary(client_words, max_len=44)}")
            if unknown:
                detail_parts.append(f"未確認：{ny_pick_summary(unknown, max_len=44)}")
            if next_check:
                detail_parts.append(f"次回確認：{ny_pick_summary(next_check, max_len=44)}")
            if related_people:
                detail_parts.append(f"関係者・場所：{ny_pick_summary(related_people, max_len=44)}")
            detail = "<br>".join([html.escape(x) for x in detail_parts])
            footer = f"更新：{normalize_text(row.get('updated_at', ''))}"
            render_nyantomo_card_tile(icon, title, headline, row.get("card_status", ""), "", footer)
            if detail:
                st.markdown(f"<div class='ny-os-mini'>{detail}</div>", unsafe_allow_html=True)
            if idx != len(sorted_rows) - 1:
                st.markdown("<hr class='ny-os-divider'>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 保留事項カード")
    if pending_df.empty:
        st.info("保留事項はまだ登録されていません。『Ver2.0｜保留事項管理』から登録してください。")
    else:
        for idx, (_, row) in enumerate(pending_df.iterrows()):
            icon = ny_pending_status_icon(row.get("status", ""))
            headline = ny_pick_summary(row.get("theme", ""), row.get("reason", ""), max_len=48)
            detail_parts = []
            if normalize_text(row.get("reason", "")):
                detail_parts.append(f"理由：{ny_pick_summary(row.get('reason', ''), max_len=44)}")
            if normalize_text(row.get("next_check_date", "")):
                detail_parts.append(f"次回確認日：{normalize_text(row.get('next_check_date', ''))}")
            if normalize_text(row.get("related_people", "")):
                detail_parts.append(f"関係者：{ny_pick_summary(row.get('related_people', ''), max_len=44)}")
            if normalize_text(row.get("caution", "")):
                detail_parts.append(f"注意：{ny_pick_summary(row.get('caution', ''), max_len=44)}")
            detail = "<br>".join([html.escape(x) for x in detail_parts])
            footer = f"更新：{normalize_text(row.get('updated_at', ''))}"
            render_nyantomo_card_tile(icon, "保留事項", headline, row.get("status", ""), "", footer)
            if detail:
                st.markdown(f"<div class='ny-os-mini'>{detail}</div>", unsafe_allow_html=True)
            if idx != len(pending_df) - 1:
                st.markdown("<hr class='ny-os-divider'>", unsafe_allow_html=True)

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
    st.markdown("### 最近のカード整理AI")
    if summary_df.empty:
        st.info("カード整理AIはまだ保存されていません。")
    else:
        for _, row in summary_df.iterrows():
            with st.expander(f"{row.get('created_at', '')}｜{row.get('summary_type', '')}", expanded=False):
                st.write(row.get("summary_text", ""))


# ============================================================
# Ver3.4：生活制度候補整理
# ============================================================

def build_policy_section_text(case_id):
    """
    生活制度候補整理だけを、AIに渡しやすいテキストへ変換します。
    build_case_ai_source() 側の取得結果が古く見える場合でも、
    ここで policy_candidates を直接読み直して、登録済み候補を確実に反映します。
    """
    try:
        df = fetch_df("""
            SELECT category, policy_name, status, priority, municipality, trigger_words,
                   reason, check_items, caution, next_action, official_confirmed, official_url, memo,
                   created_at, updated_at
            FROM policy_candidates
            WHERE case_id=%(case_id)s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
        """, {"case_id": case_id})
    except Exception as e:
        return f"\n■ Ver3.4生活制度候補整理\n取得エラー:{e}"

    lines = ["\n■ Ver3.4生活制度候補整理"]
    if df is None or df.empty:
        lines.append("未登録")
        return "\n".join(lines)

    for _, r in df.iterrows():
        parts = []
        for col in [
            "category", "policy_name", "status", "priority", "municipality", "trigger_words",
            "reason", "check_items", "caution", "next_action", "official_confirmed", "official_url", "memo"
        ]:
            value = normalize_text(r.get(col, ""))
            if value:
                parts.append(f"{col}:{value}")
        if parts:
            lines.append("- " + "／".join(parts))
    return "\n".join(lines)


def replace_policy_section(source_text, policy_section):
    """
    build_case_ai_source()内の『Ver3.4生活制度候補整理』欄を、
    最新のpolicy_candidates取得結果で差し替えます。
    """
    import re
    source_text = normalize_text(source_text)
    pattern = r"\n■ Ver3\.4生活制度候補整理\n.*?(?=\n■ |\Z)"
    if re.search(pattern, source_text, flags=re.S):
        return re.sub(pattern, policy_section, source_text, flags=re.S)
    return (source_text + policy_section).strip()


def build_policy_source_text(case_id):
    """制度候補整理用に、案件情報と登録済み生活制度候補を必ず反映してまとめる。"""
    # Ver3.4.1修正：AIへ渡す元データは毎回DBから直接読み直します。
    # 登録直後に「未登録」と表示される原因を避けるため、
    # build_case_ai_source() の内容に残る古い制度候補欄を、最新のpolicy_candidatesで必ず差し替えます。
    base_text = build_case_ai_source(case_id)
    latest_policy_section = build_policy_section_text(case_id)
    return replace_policy_section(base_text, latest_policy_section)


def refresh_policy_source(case_id):
    """Streamlit画面上で使う生活制度候補整理の元データを最新化する。"""
    try:
        clear_app_cache()
    except Exception:
        pass
    return build_policy_source_text(case_id)


def verify_policy_saved(policy_id):
    """候補登録後、DBに保存されたか確認する。"""
    row = fetch_one(
        "SELECT policy_id FROM policy_candidates WHERE policy_id=%(policy_id)s",
        {"policy_id": policy_id}
    )
    return bool(row)


def suggest_policy_candidates_from_text(source_text):
    """キーワードから制度候補を仮抽出する。断定ではなく候補整理。"""
    text = normalize_text(source_text).lower()
    suggestions = []
    for category, spec in POLICY_CANDIDATE_TEMPLATES.items():
        hits = []
        for kw in spec.get("keywords", []):
            if kw.lower() in text:
                hits.append(kw)
        if hits:
            suggestions.append({
                "category": category,
                "policy_name": category,
                "status": "候補",
                "priority": "中",
                "trigger_words": "、".join(hits[:8]),
                "reason": f"相談内容に「{ '、'.join(hits[:5]) }」などの語があり、{POLICY_CATEGORY_DOMAIN_MAP.get(category, '横断')}領域の確認候補として整理できます。",
                "check_items": spec.get("check_items", ""),
                "caution": spec.get("caution", "") + "\n" + POLICY_DISCLAIMER,
                "next_action": spec.get("next_action", "自治体・支援機関・関係専門職で、最新情報と対象要件を確認する。"),
            })
    return suggestions


def build_policy_ai_prompt(source_text, extra_instruction=""):
    return f"""
あなたは『にゃんとも 住まいと猫の相談室』の内部用「生活制度候補整理AI」です。
相談記録から、空き家・高齢者・猫・相続に関係する制度・支援先・専門職連携の「確認候補」を整理してください。

最重要ルール：
- 「使えます」「もらえます」「必要です」「対象です」と断定しない
- 法律判断、税務判断、不動産判断、医療・介護判断をしない
- 自治体・制度・専門職の領域ごとに確認先が異なる前提で書く
- 相談者を急がせない
- 申請・契約・売却・入所・後見開始を勧めるのではなく、確認候補と次回確認事項を並べる
- 事実、未確認、候補、注意点を分ける
- 本人の意思、猫の生活、家族関係、住まいの状態を分断せずに整理する

候補カテゴリ：
【空き家】
- 空き家改修補助
- 解体補助
- 耐震診断・耐震改修補助
- 住宅セーフティネット関連
- 固定資産税・特定空家関連

【高齢者】
- 介護保険住宅改修
- 福祉用具
- 高齢者住宅
- 地域包括・介護相談

【猫】
- 猫の預かり先候補
- 動物病院
- ペット信託
- 任意後見

【相続】
- 遺言
- 家族信託
- 相続人調査
- 遺産分割・相続手続き

出力形式：
## 1. 生活制度候補の全体像
- 現時点で候補になりそうな制度・支援先・専門職連携を短く整理

## 2. 候補カード
候補ごとに以下の形で整理してください。
- 領域：空き家／高齢者／猫／相続／横断
- 候補名：
- 候補度：高／中／低／要確認
- なぜ候補になるか：
- まだ確認が必要なこと：
- 注意点：
- 次の一手：

## 3. 今すぐ決めなくてよいこと
- 売却、解体、入所、後見、信託、遺言内容、猫の預け先など、急がせない方がよい項目

## 4. 次回確認チェックリスト
- 3〜10個に絞る

## 5. 確認先候補
- 自治体窓口、地域包括、ケアマネ、動物病院、預かり先候補、宅建士、司法書士、税理士、弁護士、公証役場など
- 必要と断定せず「確認先候補」とする

## 6. にゃんともとして関われる範囲
- 相談整理、記録、保留管理、空き家見守り、関係者整理、次回確認など
- 交渉・登記・税務・医療判断・強い不動産判断はしない

## 7. 内部メモ用の短い要約
3〜5行でまとめる

追加指示：{extra_instruction}

相談記録：
---
{source_text}
""".strip()

def save_policy_candidate(case_id, client_id, values):
    policy_id = make_id("policy")
    execute("""
        INSERT INTO policy_candidates
        (policy_id, case_id, client_id, created_at, updated_at, updated_by,
         category, policy_name, status, priority, municipality, trigger_words, reason,
         check_items, caution, next_action, official_confirmed, official_url, memo)
        VALUES
        (%(policy_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(updated_at)s, %(updated_by)s,
         %(category)s, %(policy_name)s, %(status)s, %(priority)s, %(municipality)s, %(trigger_words)s, %(reason)s,
         %(check_items)s, %(caution)s, %(next_action)s, %(official_confirmed)s, %(official_url)s, %(memo)s)
    """, {
        "policy_id": policy_id,
        "case_id": case_id,
        "client_id": client_id,
        "created_at": now_text(),
        "updated_at": now_text(),
        "updated_by": st.session_state.get("login_id", ""),
        **values,
    })
    log_action("create", "policy_candidates", policy_id, "制度候補登録")
    # Ver3.4.1修正：登録後すぐに一覧・AI元データへ反映させるためキャッシュをクリアします。
    clear_app_cache()
    return policy_id


def render_policy_candidates():
    st.subheader("生活制度候補整理")
    st.caption("空き家・高齢者・猫・相続に関係する制度・支援先・専門職連携候補を、断定せず『確認候補』として整理します。")
    st.warning(POLICY_DISCLAIMER)

    case_map, case_labels = get_case_options()
    if not case_labels:
        st.warning("先に相談者・案件を登録してください。")
        return

    selected_label = st.selectbox("対象案件", case_labels, key="policy_case_select")
    case_id = case_map[selected_label]
    client_id = case_to_client(case_id)
    # Ver3.4.1修正：元データは表示箇所ごとに最新化します。
    source_text = refresh_policy_source(case_id)

    cols = st.columns(4)
    with cols[0]:
        total = fetch_one("SELECT COUNT(*) AS count FROM policy_candidates WHERE case_id=%(case_id)s", {"case_id": case_id})
        st.metric("制度候補", int(total.get("count", 0)) if total else 0)
    with cols[1]:
        pending = fetch_one("SELECT COUNT(*) AS count FROM policy_candidates WHERE case_id=%(case_id)s AND COALESCE(status,'') IN ('候補','次回確認','自治体確認中')", {"case_id": case_id})
        st.metric("確認中", int(pending.get("count", 0)) if pending else 0)
    with cols[2]:
        official = fetch_one("SELECT COUNT(*) AS count FROM policy_candidates WHERE case_id=%(case_id)s AND COALESCE(official_confirmed,0)=1", {"case_id": case_id})
        st.metric("公式確認済", int(official.get("count", 0)) if official else 0)
    with cols[3]:
        st.metric("AIキー", "設定あり" if get_openai_api_key() else "未設定")

    tab1, tab2, tab3 = st.tabs(["候補を登録", "AI生活制度候補整理", "一覧・更新"])

    with tab1:
        st.markdown("### 手動登録")
        with st.form("policy_create"):
            category = st.selectbox("制度カテゴリ", POLICY_CATEGORY_OPTIONS)
            policy_name = st.text_input("制度・支援・手続き候補名", value=category)
            status = st.selectbox("状態", POLICY_STATUS_OPTIONS)
            priority = st.selectbox("確認優先度", POLICY_PRIORITY_OPTIONS, index=1)
            municipality = st.text_input("自治体・支援先・専門職確認先", placeholder="例：綾瀬市、神奈川県、介護保険担当課")
            trigger_words = st.text_input("候補になった言葉", placeholder="例：解体、老朽、固定資産税")
            reason = st.text_area("候補になる理由")
            check_items = st.text_area("次回確認事項", value=POLICY_CANDIDATE_TEMPLATES.get(category, {}).get("check_items", ""))
            caution = st.text_area("注意点", value=(POLICY_CANDIDATE_TEMPLATES.get(category, {}).get("caution", "") + "\n" + POLICY_DISCLAIMER).strip())
            next_action = st.text_area("次の一手", value="自治体・支援機関・関係専門職で、最新情報と対象要件を確認する。")
            official_confirmed = st.checkbox("公式要綱・自治体窓口で確認済み")
            official_url = st.text_input("公式URL・参照先メモ")
            memo = st.text_area("内部メモ")
            ok = st.form_submit_button("生活制度候補を登録", disabled=not can_write())
        if ok:
            policy_id = save_policy_candidate(case_id, client_id, {
                "category": category,
                "policy_name": policy_name or category,
                "status": status,
                "priority": priority,
                "municipality": municipality,
                "trigger_words": trigger_words,
                "reason": reason,
                "check_items": check_items,
                "caution": caution,
                "next_action": next_action,
                "official_confirmed": 1 if official_confirmed else 0,
                "official_url": official_url,
                "memo": memo,
            })
            if verify_policy_saved(policy_id):
                st.success("生活制度候補を登録しました。一覧・AI元データへ反映しました。")
                clear_app_cache()
                st.rerun()
            else:
                st.error("登録処理後の確認で保存が確認できませんでした。")

        st.markdown("### キーワードから候補を仮抽出")
        with st.expander("抽出元データを確認", expanded=False):
            st.text_area("抽出元データ", source_text, height=260)
        suggestions = suggest_policy_candidates_from_text(source_text)
        if not suggestions:
            st.info("現時点では、キーワードから自動抽出できる制度候補はありません。手動登録またはAI整理を使ってください。")
        else:
            st.write("以下はキーワードによる仮候補です。必要なものだけ登録してください。")
            for i, sug in enumerate(suggestions):
                with st.expander(f"候補：{sug['category']}｜きっかけ：{sug['trigger_words']}", expanded=False):
                    st.write(sug["reason"])
                    st.text_area("確認事項", sug["check_items"], key=f"sug_check_{i}", height=90)
                    st.text_area("注意点", sug["caution"], key=f"sug_caution_{i}", height=110)
                    if st.button("この候補を登録", key=f"save_sug_{i}", disabled=not can_write()):
                        values = {
                            "category": sug["category"],
                            "policy_name": sug["policy_name"],
                            "status": sug["status"],
                            "priority": sug["priority"],
                            "municipality": "",
                            "trigger_words": sug["trigger_words"],
                            "reason": sug["reason"],
                            "check_items": sug["check_items"],
                            "caution": sug["caution"],
                            "next_action": sug["next_action"],
                            "official_confirmed": 0,
                            "official_url": "",
                            "memo": "キーワード仮抽出から登録",
                        }
                        policy_id = save_policy_candidate(case_id, client_id, values)
                        if verify_policy_saved(policy_id):
                            st.success("候補を登録しました。一覧・AI元データへ反映しました。")
                            clear_app_cache()
                            st.rerun()
                        else:
                            st.error("登録処理後の確認で保存が確認できませんでした。")

    with tab2:
        st.markdown("### AIで制度候補を整理")
        st.info("AIは候補を並べるだけです。最新要綱や受付状況の確認は、必ず自治体・公式資料で行ってください。")
        # Ver3.4.1修正：AIタブを開いた時点で再取得し、登録済み候補が未登録表示にならないようにします。
        source_text = refresh_policy_source(case_id)
        extra_instruction = st.text_area("追加指示", placeholder="例：今回は空き家解体補助と耐震補助の可能性を中心に整理。", key="policy_ai_extra")
        with st.expander("AIに渡す元データ", expanded=False):
            st.text_area("元データ", source_text, height=300, key="policy_ai_source")
        if st.button("生活制度候補整理AIを作成して保存", disabled=not can_write()):
            if not source_text.strip():
                st.error("整理対象のデータがありません。")
            else:
                try:
                    with st.spinner("生活制度候補整理AIを作成しています..."):
                        prompt = build_policy_ai_prompt(source_text, extra_instruction)
                        summary_text, model = call_openai_summary(prompt)
                        save_ai_summary(case_id, client_id, "カード整理AI｜生活制度候補整理", source_text, summary_text, extra_instruction, model)
                    st.success("生活制度候補整理AIを保存しました。AI要約メモにも表示されます。")
                    clear_app_cache()
                    st.rerun()
                except Exception as e:
                    st.error("生活制度候補整理AIの作成に失敗しました。")
                    st.exception(e)

        df_ai = fetch_df("""
            SELECT summary_id, created_at, summary_type, summary_text, memo
            FROM ai_summaries
            WHERE case_id=%(case_id)s AND summary_type='カード整理AI｜生活制度候補整理'
            ORDER BY created_at DESC
        """, {"case_id": case_id})
        if df_ai.empty:
            st.info("保存済みの生活制度候補整理AIはありません。")
        else:
            for _, row in df_ai.iterrows():
                with st.expander(f"{row.get('created_at','')}｜生活制度候補整理AI", expanded=False):
                    st.markdown(row.get("summary_text", ""))

    with tab3:
        st.markdown("### 登録済み生活制度候補")
        df = fetch_df("""
            SELECT policy_id, created_at, updated_at, category, policy_name, status, priority,
                   municipality, trigger_words, reason, check_items, caution, next_action,
                   official_confirmed, official_url, memo
            FROM policy_candidates
            WHERE case_id=%(case_id)s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
        """, {"case_id": case_id})
        if df.empty:
            st.info("登録済みの制度候補はありません。")
            return
        st.dataframe(df, use_container_width=True, hide_index=True)

        if can_write():
            selected = st.selectbox("更新・削除する制度候補", df["policy_id"].tolist())
            row = df[df["policy_id"] == selected].iloc[0]
            with st.form("policy_edit"):
                category = st.selectbox("制度カテゴリ", POLICY_CATEGORY_OPTIONS, index=POLICY_CATEGORY_OPTIONS.index(row["category"]) if row["category"] in POLICY_CATEGORY_OPTIONS else 0)
                policy_name = st.text_input("制度・支援・手続き候補名", normalize_text(row["policy_name"]))
                status = st.selectbox("状態", POLICY_STATUS_OPTIONS, index=POLICY_STATUS_OPTIONS.index(row["status"]) if row["status"] in POLICY_STATUS_OPTIONS else 0)
                priority = st.selectbox("確認優先度", POLICY_PRIORITY_OPTIONS, index=POLICY_PRIORITY_OPTIONS.index(row["priority"]) if row["priority"] in POLICY_PRIORITY_OPTIONS else 1)
                municipality = st.text_input("自治体・支援先・専門職確認先", normalize_text(row["municipality"]))
                trigger_words = st.text_input("候補になった言葉", normalize_text(row["trigger_words"]))
                reason = st.text_area("候補になる理由", normalize_text(row["reason"]))
                check_items = st.text_area("次回確認事項", normalize_text(row["check_items"]))
                caution = st.text_area("注意点", normalize_text(row["caution"]))
                next_action = st.text_area("次の一手", normalize_text(row["next_action"]))
                official_confirmed = st.checkbox("公式要綱・自治体窓口で確認済み", value=bool(row.get("official_confirmed", 0)))
                official_url = st.text_input("公式URL・参照先メモ", normalize_text(row["official_url"]))
                memo = st.text_area("内部メモ", normalize_text(row["memo"]))
                delete_confirm = st.checkbox("この生活制度候補を削除することを確認しました。")
                delete_text = st.text_input("削除する場合は DELETE と入力", key="policy_delete_text")
                c1, c2 = st.columns(2)
                update = c1.form_submit_button("更新する")
                delete = c2.form_submit_button("削除する")
            if update:
                execute("""
                    UPDATE policy_candidates SET
                        updated_at=%(updated_at)s, updated_by=%(updated_by)s, category=%(category)s,
                        policy_name=%(policy_name)s, status=%(status)s, priority=%(priority)s,
                        municipality=%(municipality)s, trigger_words=%(trigger_words)s, reason=%(reason)s,
                        check_items=%(check_items)s, caution=%(caution)s, next_action=%(next_action)s,
                        official_confirmed=%(official_confirmed)s, official_url=%(official_url)s, memo=%(memo)s
                    WHERE policy_id=%(policy_id)s
                """, {
                    "updated_at": now_text(),
                    "updated_by": st.session_state.get("login_id", ""),
                    "category": category,
                    "policy_name": policy_name,
                    "status": status,
                    "priority": priority,
                    "municipality": municipality,
                    "trigger_words": trigger_words,
                    "reason": reason,
                    "check_items": check_items,
                    "caution": caution,
                    "next_action": next_action,
                    "official_confirmed": 1 if official_confirmed else 0,
                    "official_url": official_url,
                    "memo": memo,
                    "policy_id": selected,
                })
                log_action("update", "policy_candidates", selected, "制度候補更新")
                st.success("生活生活制度候補を更新しました。")
                clear_app_cache()
                st.rerun()
            if delete:
                if not delete_confirm or delete_text != "DELETE":
                    st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
                else:
                    execute("DELETE FROM policy_candidates WHERE policy_id=%(policy_id)s", {"policy_id": selected})
                    log_action("delete", "policy_candidates", selected, "制度候補削除")
                    st.success("生活生活制度候補を削除しました。")
                    clear_app_cache()
                    st.rerun()

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
            "カード整理AI｜生活制度候補整理",
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
                clear_app_cache()
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

                st.markdown("#### 相談者向けA4レポート")
                try:
                    pdf_bytes = build_client_report_pdf_bytes(case_id, row)
                    safe_client = normalize_text(selected_label).split("｜")[0] if selected_label else "client"
                    safe_name = "nyantomo_report_" + safe_client.replace("/", "_").replace("\\", "_") + "_" + normalize_text(row.get("summary_id", "summary")) + ".pdf"
                    st.download_button(
                        "A4一枚PDFをダウンロード",
                        data=pdf_bytes,
                        file_name=safe_name,
                        mime="application/pdf",
                        key=f"client_report_pdf_{row.get('summary_id', '')}",
                    )
                except Exception as e:
                    st.warning(f"PDFを作成できませんでした：{e}")

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
                clear_app_cache()
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
                clear_app_cache()
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
            (SELECT COUNT(*) FROM guardian_wards WHERE next_check_date IS NOT NULL AND next_check_date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date + INTERVAL '7 days')) AS need_check_count
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
            birth_date = ymd_selectbox_date("生年月日", default=None, start_year=1900, key_prefix="guardian_birth_create")
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
            clear_app_cache()
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
            new_birth_date = ymd_selectbox_date("生年月日", default=row.get("birth_date", None), start_year=1900, key_prefix="guardian_birth_edit")
            new_start_date = st.date_input("担当開始日", date_or_none(row.get("start_date", None)))
            new_status = st.selectbox("状態", GUARDIAN_STATUS_OPTIONS, index=GUARDIAN_STATUS_OPTIONS.index(row["status"]) if row["status"] in GUARDIAN_STATUS_OPTIONS else 0)
            new_emergency = st.selectbox("緊急度", EMERGENCY_OPTIONS, index=EMERGENCY_OPTIONS.index(row["emergency_level"]) if row["emergency_level"] in EMERGENCY_OPTIONS else 0)
            new_next = st.date_input("次回確認日", date_or_none(row["next_check_date"]))
            new_memo = st.text_area("備考", normalize_text(row["memo"]))
            update = st.form_submit_button("更新する")
        if update:
            execute("""
                UPDATE guardian_wards
                SET updated_at=%(updated_at)s, birth_date=%(birth_date)s, start_date=%(start_date)s, status=%(status)s, emergency_level=%(emergency_level)s, next_check_date=%(next_check_date)s, memo=%(memo)s
                WHERE ward_id=%(ward_id)s
            """, {"updated_at": now_text(), "birth_date": new_birth_date, "start_date": new_start_date, "status": new_status, "emergency_level": new_emergency, "next_check_date": new_next, "memo": new_memo, "ward_id": selected})
            log_action("update", "guardian_wards", selected, "被後見人更新")
            st.success("更新しました。")
            clear_app_cache()
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
        clear_app_cache()
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
        clear_app_cache()
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
        interview_date = st.date_input("日時", today_jst())
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
        clear_app_cache()
        st.rerun()
    df = fetch_df("SELECT * FROM guardian_interview_logs WHERE ward_id=%(ward_id)s ORDER BY interview_date DESC NULLS LAST, created_at DESC", {"ward_id": ward_id})
    st.dataframe(df, use_container_width=True, hide_index=True)










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
                clear_app_cache()
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

                st.markdown("#### 後見整理レポートPDF")
                try:
                    pdf_bytes = build_guardian_report_pdf_bytes(ward_id, r)
                    safe_ward = normalize_text(selected_label).split("｜")[0] if selected_label else "ward"
                    safe_name = "nyantomo_guardian_report_" + safe_ward.replace("/", "_").replace("\\", "_") + "_" + normalize_text(r.get("ai_id", "summary")) + ".pdf"
                    st.download_button(
                        "後見整理A4一枚PDFをダウンロード",
                        data=pdf_bytes,
                        file_name=safe_name,
                        mime="application/pdf",
                        key=f"guardian_report_pdf_{r.get('ai_id', '')}",
                    )
                except Exception as e:
                    st.warning(f"PDFを作成できませんでした：{e}")

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
                    clear_app_cache()
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
            clear_app_cache()
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
        clear_app_cache()
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
            clear_app_cache()
            st.rerun()



# ============================================================
# Ver3.5：にゃんともアシスタント（常駐AI秘書）
# ------------------------------------------------------------
# 役割：相談履歴検索／過去案件検索／次回確認事項抽出／制度候補整理／
#       HP・note下書き／面談メモ作成
# 原則：AIは判断者ではなく「書庫番・整理係」。結論を急がせず、
#       事実・未確定・保留・次回確認を分けて整理します。
# ============================================================

ASSISTANT_MODE_OPTIONS = [
    "案件確認",
    "案件横断検索",
    "次回確認事項抽出",
    "次回確認ダッシュボード",
    "制度候補整理",
    "制度候補推薦",
    "面談メモ作成",
    "HP記事下書き",
    "note記事下書き",
    "note自動生成",
    "自由相談",
]




def save_assistant_log(case_id, client_id, mode, user_question, source_text, answer_text, model="", memo=""):
    try:
        log_id = make_id("assist")
        execute("""
            INSERT INTO assistant_logs
            (assistant_log_id, created_at, updated_at, created_by, case_id, client_id, mode, user_question, source_text, answer_text, model, memo)
            VALUES (%(assistant_log_id)s, %(created_at)s, %(updated_at)s, %(created_by)s, %(case_id)s, %(client_id)s, %(mode)s, %(user_question)s, %(source_text)s, %(answer_text)s, %(model)s, %(memo)s)
        """, {
            "assistant_log_id": log_id,
            "created_at": now_text(),
            "updated_at": now_text(),
            "created_by": st.session_state.get("login_id", ""),
            "case_id": case_id or None,
            "client_id": client_id or None,
            "mode": mode,
            "user_question": user_question,
            "source_text": source_text,
            "answer_text": answer_text,
            "model": model,
            "memo": memo,
        })
        log_action("create", "assistant_logs", log_id, f"にゃんともアシスタント：{mode}")
        return log_id
    except Exception:
        return ""


def _assistant_df_lines(title, df, cols, limit=8):
    lines = [f"\n■ {title}"]
    if df is None or df.empty:
        lines.append("未登録")
        return "\n".join(lines)
    for _, r in df.head(limit).iterrows():
        parts = []
        for col in cols:
            if col in r and normalize_text(r[col]):
                parts.append(f"{col}:{normalize_text(r[col])}")
        if parts:
            lines.append("- " + "／".join(parts))
    return "\n".join(lines)


def get_assistant_case_options():
    mapping, labels = get_case_options()
    return mapping, ["指定しない（全体から検索）"] + labels


def search_assistant_related_cases(query, limit=8):
    """質問文から近い案件を横断検索する。PostgreSQL ILIKE前提。"""
    q = normalize_text(query)
    if not q:
        return fetch_df("""
            SELECT c.case_id, c.client_id, cl.name AS client_name, c.case_title, c.case_type, c.status,
                   c.current_state, c.worries, c.not_decide, c.next_check, c.next_check_date, c.updated_at
            FROM cases c JOIN clients cl ON c.client_id = cl.client_id
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
            LIMIT %(limit)s
        """, {"limit": limit})
    pattern = f"%{q}%"
    return fetch_df("""
        SELECT DISTINCT c.case_id, c.client_id, cl.name AS client_name, c.case_title, c.case_type, c.status,
               c.current_state, c.worries, c.not_decide, c.next_check, c.next_check_date, c.updated_at
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        LEFT JOIN history h ON h.case_id = c.case_id
        LEFT JOIN consultation_cards cc ON cc.case_id = c.case_id
        LEFT JOIN pending_items p ON p.case_id = c.case_id
        LEFT JOIN policy_candidates pc ON pc.case_id = c.case_id
        WHERE cl.name ILIKE %(pattern)s
           OR c.case_title ILIKE %(pattern)s
           OR c.case_type ILIKE %(pattern)s
           OR c.status ILIKE %(pattern)s
           OR c.current_state ILIKE %(pattern)s
           OR c.house_state ILIKE %(pattern)s
           OR c.cat_relation ILIKE %(pattern)s
           OR c.family_gap ILIKE %(pattern)s
           OR c.worries ILIKE %(pattern)s
           OR c.not_decide ILIKE %(pattern)s
           OR c.next_check ILIKE %(pattern)s
           OR h.record ILIKE %(pattern)s
           OR h.next_action ILIKE %(pattern)s
           OR cc.concern ILIKE %(pattern)s
           OR cc.client_words ILIKE %(pattern)s
           OR p.theme ILIKE %(pattern)s
           OR p.reason ILIKE %(pattern)s
           OR pc.category ILIKE %(pattern)s
           OR pc.policy_name ILIKE %(pattern)s
        ORDER BY c.updated_at DESC NULLS LAST
        LIMIT %(limit)s
    """, {"pattern": pattern, "limit": limit})




def _assistant_expand_query_terms(query):
    """にゃんとも用の横断検索語を少し広げる。"""
    q = normalize_text(query)
    terms = []
    if q:
        terms.append(q)
    expansion_map = {
        "猫": ["猫", "ペット", "預かり", "引き取り", "動物病院", "ペット信託", "世話"],
        "猫の将来": ["猫", "ペット信託", "預かり", "引き取り", "世話人", "動物病院", "もしもの時"],
        "空き家": ["空き家", "実家", "住まい", "見守り", "管理", "売却", "賃貸"],
        "後見": ["後見", "任意後見", "見守り契約", "判断能力", "認知症"],
        "相続": ["相続", "遺言", "遺産分割", "戸籍", "相続人"],
        "制度": ["制度", "補助", "助成", "申請", "包括", "介護保険", "住宅改修"],
        "次回": ["次回", "確認", "未確認", "ヒアリング", "要確認"],
    }
    for key, values in expansion_map.items():
        if key in q:
            terms.extend(values)
    # 重複を残さない
    seen = set()
    result = []
    for t in terms:
        t = normalize_text(t)
        if t and t not in seen:
            result.append(t)
            seen.add(t)
    return result or [""]


def search_assistant_cases_by_terms(query, limit=30):
    """
    A. 案件横断検索
    質問語を少し広げて、案件・履歴・カード・保留・制度候補を横断検索する。
    """
    terms = _assistant_expand_query_terms(query)
    if not terms or terms == [""]:
        return search_assistant_related_cases("", limit=limit)

    where_parts = []
    params = {"limit": limit}
    search_cols = [
        "cl.name", "cl.area", "cl.note",
        "c.case_title", "c.case_type", "c.status", "c.current_state", "c.house_state",
        "c.cat_relation", "c.family_gap", "c.pressure", "c.worries", "c.not_decide",
        "c.next_check", "c.next_hearing_items", "c.hearing_missing", "c.do_not_do_now",
        "h.record", "h.next_action", "h.internal_memo",
        "cc.card_type", "cc.concern", "cc.client_words", "cc.current_state", "cc.unknown_items", "cc.next_check_items",
        "p.theme", "p.reason", "p.caution", "p.memo",
        "pc.category", "pc.policy_name", "pc.reason", "pc.check_items", "pc.next_action",
        "cat.cat_name", "cat.health_memo", "cat.life_status", "cat.future_plan",
        "prop.property_name", "prop.address", "prop.property_status", "prop.vacant_status",
        "fam.name", "fam.relation", "fam.temperature", "fam.memo"
    ]
    for i, term in enumerate(terms[:8]):
        key = f"p{i}"
        params[key] = f"%{term}%"
        where_parts.append("(" + " OR ".join([f"{col} ILIKE %({key})s" for col in search_cols]) + ")")

    sql = f"""
        SELECT DISTINCT c.case_id, c.client_id, cl.name AS client_name, c.case_title, c.case_type, c.status,
               c.current_state, c.cat_relation, c.house_state, c.family_gap, c.worries,
               c.not_decide, c.next_check, c.next_check_date, c.updated_at, c.created_at
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        LEFT JOIN history h ON h.case_id = c.case_id
        LEFT JOIN consultation_cards cc ON cc.case_id = c.case_id
        LEFT JOIN pending_items p ON p.case_id = c.case_id
        LEFT JOIN policy_candidates pc ON pc.case_id = c.case_id
        LEFT JOIN cats cat ON cat.case_id = c.case_id
        LEFT JOIN properties prop ON prop.case_id = c.case_id
        LEFT JOIN family fam ON fam.case_id = c.case_id
        WHERE {" OR ".join(where_parts)}
        ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
        LIMIT %(limit)s
    """
    return fetch_df(sql, params)


def get_assistant_due_cases(days=7):
    """
    B. 次回確認ダッシュボード
    期限超過・指定日数以内・ヒアリング漏れ・今やらない方がいいことをまとめて取得する。
    """
    return fetch_df("""
        SELECT cl.name AS client_name, c.case_id, c.client_id, c.case_title, c.case_type, c.status,
               c.next_check_date, c.next_check, c.next_hearing_items, c.hearing_missing,
               c.do_not_do_now, c.not_decide, c.updated_at,
               CASE
                 WHEN c.next_check_date IS NULL THEN '日付未設定'
                 WHEN c.next_check_date < ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date) THEN '期限超過'
                 WHEN c.next_check_date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date + (%(days)s || ' days')::interval) THEN '近日確認'
                 ELSE '今後確認'
               END AS check_status
        FROM cases c
        JOIN clients cl ON c.client_id = cl.client_id
        WHERE COALESCE(c.status,'') <> '終了'
          AND (
              c.next_check_date IS NOT NULL
              OR NULLIF(TRIM(COALESCE(c.hearing_missing,'')), '') IS NOT NULL
              OR NULLIF(TRIM(COALESCE(c.next_hearing_items,'')), '') IS NOT NULL
              OR NULLIF(TRIM(COALESCE(c.do_not_do_now,'')), '') IS NOT NULL
          )
        ORDER BY
          CASE
            WHEN c.next_check_date IS NULL THEN 3
            WHEN c.next_check_date < ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date) THEN 0
            WHEN c.next_check_date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date + (%(days)s || ' days')::interval) THEN 1
            ELSE 2
          END,
          c.next_check_date ASC NULLS LAST,
          c.updated_at DESC
        LIMIT 100
    """, {"days": int(days)})


def recommend_policy_candidates_from_text(text_value, max_items=12):
    """
    C. 制度候補推薦
    既存のPOLICY_CANDIDATE_TEMPLATESを使い、案件記録から制度・支援候補を出す。
    """
    text_value = normalize_text(text_value)
    rows = []
    for category, tpl in POLICY_CANDIDATE_TEMPLATES.items():
        hit_words = [k for k in tpl.get("keywords", []) if k and k in text_value]
        if hit_words:
            rows.append({
                "領域": POLICY_CATEGORY_DOMAIN_MAP.get(category, "横断・その他"),
                "候補": category,
                "反応語": "、".join(hit_words[:8]),
                "確認事項": tpl.get("check_items", ""),
                "注意点": tpl.get("caution", ""),
                "次の一手": tpl.get("next_action", ""),
            })
    return rows[:max_items]


def build_policy_recommendation_text(source_text):
    rows = recommend_policy_candidates_from_text(source_text)
    if not rows:
        return "記録上、強く反応する制度候補はまだ見つかりません。所在地・本人意思・猫・住まい・家族関係を先に整理してください。"
    blocks = []
    for r in rows:
        blocks.append(f"""### {r['候補']}（{r['領域']}）
- 反応語：{r['反応語']}
- 確認事項：{r['確認事項']}
- 注意点：{r['注意点']}
- 次の一手：{r['次の一手']}""")
    return "\n\n".join(blocks)


def anonymize_for_note(text_value):
    """D. note自動生成用の簡易匿名化。相談者名やIDを直接出さない。"""
    t = normalize_text(text_value)
    # ID系・電話番号・メールっぽい文字列を削る
    t = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "（メール省略）", t)
    t = re.sub(r"\b0\d{1,4}[-ー]?\d{1,4}[-ー]?\d{3,4}\b", "（電話番号省略）", t)
    t = re.sub(r"(client|case|hist|cat|property|family|card|pending|policy)_[0-9a-fA-F]{6,}", "（ID省略）", t)
    # よく出るラベルは一般化
    t = re.sub(r"client_name[:：][^\n／]+", "client_name:ある相談者", t)
    t = re.sub(r"case_title[:：][^\n／]+", "case_title:ある相談", t)
    return t


def build_note_draft_from_case(source_text, user_question=""):
    """案件整理→匿名化→note下書き。にゃんとも文体寄りのローカル生成。"""
    safe_source = anonymize_for_note(source_text)
    visible, pending, unknown, nexts, cautions = _assistant_common_sections(safe_source)
    seed = "\n".join(visible[:5] + pending[:3] + unknown[:3])
    return f"""# note下書き｜解決を急がないために、まず置いておく

夕方の部屋に、猫の気配だけが静かに残っていることがあります。

誰かの入院。
実家の空き家。
相続のこと。
これからの住まい。
そして、家で待っている猫のこと。

ひとつずつなら考えられることも、同時に重なると、急に大きな問題に見えてしまいます。

今回の相談でも、最初から何かを決めるというより、まずは目の前にある不安を並べるところから始まりました。

## まず見えていたこと

{_assistant_bullets(visible[:6], "住まい・猫・家族・これからの暮らしが重なっていました。")}

## すぐに決めなくてもよいこと

{_assistant_bullets(pending[:5], "売る、貸す、預ける、制度を使う。そうした結論は、情報がそろうまで保留できます。")}

## まだ確認しておきたいこと

{_assistant_bullets(unknown[:5] + nexts[:3], "猫のこと、家族の希望、住まいの状態などを、次回以降に分けて確認します。")}

大切なのは、急がないことと、何もしないことを分けることです。

保留は、放置ではありません。

大切だからこそ、すぐに結論を出さず、記録し、確認し、必要なときに動ける形にしておく。

にゃんともが守りたいのは、猫と暮らす人の判断の時間です。

問題そのものをすぐに消すことはできなくても、考えるための座布団をひとつ置くことはできます。

解決を、急がなくていい。

まずは、今ある不安を一緒に並べるところからで大丈夫です。

---
※この下書きは内部記録をもとに匿名化・一般化したものです。公開前に、個人が特定される地域名・家族構成・猫の固有名詞などが残っていないか確認してください。
""".strip()


def build_cross_case_search_answer(query, df):
    if df is None or df.empty:
        return f"""## 案件横断検索結果
「{query}」に近い案件は見つかりませんでした。

## 次に試す検索語
- 猫
- ペット信託
- 預かり
- 空き家
- 後見
- 相続
- 次回確認
"""
    lines = [f"## 案件横断検索結果：「{query}」", ""]
    for _, r in df.head(20).iterrows():
        lines.append(f"""### {normalize_text(r.get('client_name',''))}｜{normalize_text(r.get('case_title',''))}
- 状態：{normalize_text(r.get('status',''))}
- 種別：{normalize_text(r.get('case_type',''))}
- 猫：{normalize_text(r.get('cat_relation','')) or '記録なし'}
- 住まい：{normalize_text(r.get('house_state','')) or '記録なし'}
- 心配ごと：{normalize_text(r.get('worries','')) or '記録なし'}
- 保留：{normalize_text(r.get('not_decide','')) or '記録なし'}
- 次回確認：{normalize_text(r.get('next_check','')) or '記録なし'}（{normalize_text(r.get('next_check_date','')) or '日付未設定'}）
""")
    return "\n".join(lines).strip()


def build_due_dashboard_answer(df, days=7):
    if df is None or df.empty:
        return f"""## 次回確認ダッシュボード
今後{days}日以内の要確認案件、またはヒアリング漏れがある案件は見つかりませんでした。"""
    lines = [f"## 次回確認ダッシュボード｜今後{days}日以内＋未確認あり", ""]
    for _, r in df.head(30).iterrows():
        lines.append(f"""### {normalize_text(r.get('check_status',''))}｜{normalize_text(r.get('client_name',''))}｜{normalize_text(r.get('case_title',''))}
- 状態：{normalize_text(r.get('status',''))}
- 次回確認日：{normalize_text(r.get('next_check_date','')) or '未設定'}
- 次回確認：{normalize_text(r.get('next_check','')) or '記録なし'}
- ヒアリング漏れ：{normalize_text(r.get('hearing_missing','')) or '記録なし'}
- 今やらない方がいいこと：{normalize_text(r.get('do_not_do_now','')) or '記録なし'}
""")
    return "\n".join(lines).strip()



def build_nyantomo_assistant_source(user_question, selected_case_id=""):
    """選択案件または検索結果から、AIに渡す内部コンテキストを作る。"""
    selected_case_id = normalize_text(selected_case_id)
    lines = []
    if selected_case_id:
        lines.append("# 選択案件の詳細")
        lines.append(build_case_ai_source(selected_case_id))
        return "\n".join([x for x in lines if x]).strip()

    related = search_assistant_related_cases(user_question, limit=8)
    lines.append("# 横断検索で見つかった関連案件")
    lines.append(_assistant_df_lines(
        "関連案件一覧",
        related,
        ["client_name", "case_title", "case_type", "status", "current_state", "worries", "not_decide", "next_check", "next_check_date", "updated_at"],
        limit=8,
    ))

    if related is not None and not related.empty:
        for _, r in related.head(3).iterrows():
            cid = normalize_text(r.get("case_id", ""))
            if cid:
                lines.append("\n---")
                lines.append(build_case_ai_source(cid))
    else:
        lines.append("\n該当案件は見つかりませんでした。直近案件を確認してください。")
        recent = search_assistant_related_cases("", limit=5)
        lines.append(_assistant_df_lines(
            "直近案件",
            recent,
            ["client_name", "case_title", "case_type", "status", "next_check", "next_check_date", "updated_at"],
            limit=5,
        ))
    return "\n".join([x for x in lines if x]).strip()


def build_nyantomo_assistant_prompt(mode, user_question, source_text):
    return f"""
あなたは『にゃんとも 住まいと猫の相談室』の常駐AI秘書「にゃんともアシスタント」です。
役割は、答えを急がせることではなく、相談記録・案件・カード・履歴を探し、
事実／未確定／保留／次回確認を分けて、健一さんが次に確認しやすい形に整えることです。

厳守ルール：
- 法律判断、医療判断、税務判断、不動産判断はしない
- 売却すべき、後見すべき、信託すべきなどの結論を出さない
- 相談者本人の判断を奪わない
- 記録にないことは「未確認」と書く
- 急がせる表現を避ける
- にゃんともは「猫と暮らす人の判断の時間を守る」立場で整理する
- 出力は内部用。相談者に渡す場合は、別途やわらかく整える必要がある

今回のモード：{mode}
健一さんの質問：{user_question}

モード別の出力方針：
- 案件確認：現在状態、保留点、未確認点、次回確認、注意点を短く整理
- 案件横断検索：条件に合う案件を一覧化し、状態・猫・住まい・保留・次回確認を比較する
- 次回確認事項抽出：次回聞くことを3〜7個に絞り、優先順に整理
- 次回確認ダッシュボード：期限超過・近日確認・日付未設定を分け、確認優先順位を出す
- 制度候補整理：断定せず、確認候補・確認先・未確認条件・注意点に分ける
- 制度候補推薦：案件記録から任意後見・ペット信託・住宅改修等の確認候補を推薦する。ただし必要性は断定しない
- 面談メモ作成：面談前に見るA4メモ風に、テーマ・聞くこと・急がないことを整理
- HP記事下書き：個人情報を出さず、一般化した1000字程度のHP向け本文にする
- note記事下書き：にゃんとも文体で、情景から入り、専門知識は生活に溶かす
- note自動生成：案件整理を匿名化・一般化し、公開前チェック付きのnote下書きを作る
- 自由相談：質問意図に沿って、記録ベースで整理する

出力形式：
## 1. まず見えていること
## 2. 保留してよいこと
## 3. 未確認のこと
## 4. 次回確認
## 5. にゃんともとしての関わり方
## 6. 注意点

以下が参照できる内部記録です。
---
{source_text}
""".strip()



def _assistant_pick_lines(source_text, keywords, max_lines=8):
    """内部記録からキーワードに合う行を抜き出す。AIなしでも実用的に動くための簡易抽出。"""
    source_text = normalize_text(source_text)
    picked = []
    seen = set()
    for raw in source_text.splitlines():
        line = normalize_text(raw)
        if not line or len(line) < 2:
            continue
        if any(k in line for k in keywords):
            key = line[:180]
            if key not in seen:
                picked.append(line)
                seen.add(key)
        if len(picked) >= max_lines:
            break
    return picked


def _assistant_bullets(lines, empty_text="記録上は明確な記載がありません。"):
    if not lines:
        return f"- {empty_text}"
    return "\n".join([f"- {x}" for x in lines])


def _assistant_detect_policy_candidates(text_value, max_items=6):
    """POLICY_CANDIDATE_TEMPLATESから候補を抽出。断定ではなく確認候補として返す。"""
    text_value = normalize_text(text_value)
    found = []
    for category, tpl in POLICY_CANDIDATE_TEMPLATES.items():
        kws = tpl.get("keywords", [])
        hit_words = [k for k in kws if k and k in text_value]
        if hit_words:
            found.append((category, hit_words, tpl))
    return found[:max_items]


def _assistant_common_sections(source_text):
    visible = _assistant_pick_lines(
        source_text,
        ["client_name", "case_title", "status", "現在", "状態", "相談", "案件", "心配", "猫", "住まい", "家族", "保留", "次回", "未確認"],
        max_lines=12,
    )
    pending = _assistant_pick_lines(
        source_text,
        ["not_decide", "今は決めない", "保留", "pending", "判断保留", "急がない"],
        max_lines=8,
    )
    unknown = _assistant_pick_lines(
        source_text,
        ["未確認", "ヒアリング漏れ", "next_hearing", "unknown", "確認事項", "要確認", "聞く"],
        max_lines=8,
    )
    nexts = _assistant_pick_lines(
        source_text,
        ["next_check", "次回", "次の対応", "next_action", "確認日"],
        max_lines=8,
    )
    cautions = _assistant_pick_lines(
        source_text,
        ["注意", "caution", "do_not", "今やらない", "専門職", "弁護士", "司法書士", "税理士", "医療", "登記"],
        max_lines=8,
    )
    return visible, pending, unknown, nexts, cautions


def build_local_assistant_answer(mode, user_question, source_text):
    """
    OpenAI APIキー未設定時でも、メニューごとの機能が実際に動くようにするローカル整理。
    生成AIではなく、DB内の相談記録・カード・保留・制度候補の抽出と定型整形を行います。
    """
    mode = normalize_text(mode)
    user_question = normalize_text(user_question)
    source_text = normalize_text(source_text)
    visible, pending, unknown, nexts, cautions = _assistant_common_sections(source_text)
    policy_hits = _assistant_detect_policy_candidates(user_question + "\n" + source_text)

    if mode == "案件横断検索":
        df = search_assistant_cases_by_terms(user_question, limit=30)
        return build_cross_case_search_answer(user_question, df)

    if mode == "次回確認ダッシュボード":
        days = 7
        m = re.search(r"(\d+)\s*日", user_question)
        if m:
            try:
                days = max(1, min(60, int(m.group(1))))
            except Exception:
                days = 7
        df = get_assistant_due_cases(days=days)
        return build_due_dashboard_answer(df, days=days)

    if mode == "制度候補推薦":
        return f"""## 1. 制度・支援の推薦候補
{build_policy_recommendation_text(source_text)}

## 2. 推薦の扱い
- ここで出るものは「確認候補」です。
- 必要性・利用可否・申請可否は断定しません。
- 本人意思、所在地、年度条件、専門職確認を分けて進めます。

## 3. 次回確認
{_assistant_bullets(unknown + nexts, "所在地・本人意思・猫の状態・住まいの状態を次回確認候補にしてください。")}

## 4. 注意点
{POLICY_DISCLAIMER}
""".strip()

    if mode == "note自動生成":
        return build_note_draft_from_case(source_text, user_question)

    if mode == "次回確認事項抽出":
        return f"""## 1. 次回確認の候補
{_assistant_bullets(nexts + unknown, "次回確認として明確に書かれた項目はまだ少ないです。")}

## 2. 優先して聞くとよいこと
- 相談者本人が、今いちばん気になっていること
- 猫・住まい・家族・お金のうち、どれが先に不安になっているか
- 今すぐ決めたいことではなく、今は決めなくてよいこと
- 連絡してよい家族・支援者・専門職の範囲
- 次回までに確認できそうな資料や写真

## 3. 保留してよいこと
{_assistant_bullets(pending, "結論を急ぐ必要がある記録は見当たりません。")}

## 4. 注意点
{_assistant_bullets(cautions, "断定せず、必要に応じて専門職・自治体確認に分けてください。")}

---
### 参照した内部記録の抜粋
{source_text[:6000]}
""".strip()

    if mode == "制度候補整理":
        if policy_hits:
            blocks = []
            for category, hit_words, tpl in policy_hits:
                domain = POLICY_CATEGORY_DOMAIN_MAP.get(category, "横断・その他")
                blocks.append(f"""### {category}（{domain}）
- 反応した言葉：{", ".join(hit_words)}
- 確認すること：{tpl.get("check_items", "")}
- 注意点：{tpl.get("caution", "")}
- 次の一手：{tpl.get("next_action", "")}""")
            candidate_text = "\n\n".join(blocks)
        else:
            candidate_text = "- 記録上、強く反応する制度候補はまだ見つかりません。まず所在地・本人意思・猫・住まい・家族関係を整理してください。"
        return f"""## 1. 制度・支援の確認候補
{candidate_text}

## 2. まだ断定しないこと
- 制度が使えるかどうか
- 申請対象になるかどうか
- 後見・信託・遺言・売却・賃貸などの必要性
- 補助金や支援制度の最新条件

## 3. 次回確認
{_assistant_bullets(unknown + nexts, "所在地・所有者・本人意思・緊急度を次回確認候補にしてください。")}

## 4. にゃんともとしての関わり方
制度を結論として出すのではなく、相談者が急がず考えられるように「確認候補」として横に置きます。

## 5. 注意点
{POLICY_DISCLAIMER}

---
### 参照した内部記録の抜粋
{source_text[:6000]}
""".strip()

    if mode == "面談メモ作成":
        return f"""# 面談前メモ

## 1. 今日の主テーマ
{_assistant_bullets(visible[:5], "テーマは未確定です。冒頭で相談者の言葉をそのまま確認してください。")}

## 2. 先に安心してもらう一言
- 今日は結論を出す場ではなく、今ある不安を一緒に並べる時間です。
- 決めることより、まだ決めなくてよいことを見つけることも大切です。

## 3. 聞くこと
{_assistant_bullets(unknown + nexts, "猫・住まい・家族・お金・支援者を順番に確認してください。")}

## 4. 急がないこと
{_assistant_bullets(pending, "売却・賃貸・後見・信託などの結論は、情報が揃うまで保留できます。")}

## 5. 面談後に残す記録
- 相談者の言葉
- 未確認事項
- 保留してよいこと
- 次回確認日
- 必要なら制度候補

## 6. 注意点
{_assistant_bullets(cautions, "越境判断を避け、必要時は専門職確認に分けます。")}
""".strip()

    if mode == "HP記事下書き":
        return f"""# HP記事下書き

## 解決を、急がなくていい。

住まいのこと、猫のこと、これからの暮らしのこと。

一度に考えようとすると、何から手をつけてよいのか分からなくなることがあります。実家や空き家のこと、高齢になってからの住まい、猫の世話、家族との温度差。どれも大切だからこそ、すぐに答えを出せないのは自然なことです。

にゃんとも 住まいと猫の相談室では、まず状況を一緒に整理します。

売る、貸す、預ける、制度を使う。そうした選択肢を急いで決める前に、今見えていること、まだ分からないこと、しばらく保留してよいことを分けていきます。

大切なのは、何もしないことではありません。

急がずに置いておくために、記録し、確認し、必要なときに動ける形にしておくことです。

猫と暮らす人の判断の時間を守るために、にゃんともは、固い現実に少しだけクッションを置く相談室でありたいと思っています。

まずは、今気になっていることを一緒に並べるところから始めませんか。

---
※この下書きは個人情報を含まない一般記事として整えています。公開前に地域名・料金・導線を必要に応じて追記してください。
""".strip()

    if mode == "note記事下書き":
        return f"""# note記事下書き

夕方になると、猫はいつもの場所で待っています。

玄関の音、台所の気配、いつもの声。
人の暮らしの中に、猫の時間は静かに重なっています。

けれど、親の入院、実家の空き家、相続、施設入所。
そうした出来事が急に近づいてくると、猫のことも、住まいのことも、家族のことも、一度に考えなければならないように感じます。

でも本当は、すぐに全部を決めなくてもいいのだと思います。

大切なのは、放置することではなく、今は決めなくてよいことを分けておくこと。
分からないことを、分からないまま安全に置いておくこと。
そして、必要なときに確認できるように、言葉にして残しておくこと。

にゃんともが大切にしたいのは、猫と暮らす人の判断の時間です。

売るか、貸すか。
預けるか、引き取るか。
制度を使うか、まだ使わないか。

その答えの前に、その人の心が追いつく時間が必要なことがあります。

解決を、急がなくていい。

そう言える場所がひとつあるだけで、暮らしの中の猫も、人も、少しだけ息がしやすくなるのかもしれません。

---
開業準備中の小さな相談室として、猫と暮らす人のこれからを、少しずつ整えています。
""".strip()

    if mode == "自由相談":
        return f"""## 1. 質問への整理
「{user_question}」について、内部記録から確認できる範囲で整理します。

## 2. まず見えていること
{_assistant_bullets(visible, "関連しそうな記録は多くありません。検索語や対象案件を変えると見つかる可能性があります。")}

## 3. 保留してよいこと
{_assistant_bullets(pending)}

## 4. 未確認のこと
{_assistant_bullets(unknown)}

## 5. 次回確認
{_assistant_bullets(nexts)}

## 6. 注意点
{_assistant_bullets(cautions)}
""".strip()

    # 案件確認（デフォルト）
    return f"""## 1. まず見えていること
{_assistant_bullets(visible, "関連する案件記録はまだ十分に見つかっていません。")}

## 2. 保留してよいこと
{_assistant_bullets(pending, "記録上、明確な保留事項はまだ少ないです。")}

## 3. 未確認のこと
{_assistant_bullets(unknown, "未確認事項はまだ整理されていません。")}

## 4. 次回確認
{_assistant_bullets(nexts, "次回確認日は未設定、または記録上見つかりません。")}

## 5. にゃんともとしての関わり方
- まず相談者の言葉をそのまま残す
- 猫・住まい・家族・お金・制度をカードに分ける
- 決めることより、決めなくてよいことを見つける
- 必要な時だけ制度・専門職・地域資源につなぐ

## 6. 注意点
{_assistant_bullets(cautions, "法律・医療・税務・登記・強い不動産判断は断定せず、確認候補として扱ってください。")}

---
### 参照した内部記録の抜粋
{source_text[:6000]}
""".strip()


def save_assistant_answer_to_history(case_id, mode, answer_text):
    """アシスタント整理結果を相談履歴へ保存する。"""
    if not case_id:
        return False, "対象案件が指定されていません。"
    client_id = case_to_client(case_id)
    history_id = make_id("hist")
    execute("""
        INSERT INTO history
        (history_id, case_id, client_id, created_at, record_date, record_type, record, next_action, internal_memo)
        VALUES (%(history_id)s, %(case_id)s, %(client_id)s, %(created_at)s, %(record_date)s, %(record_type)s, %(record)s, %(next_action)s, %(internal_memo)s)
    """, {
        "history_id": history_id,
        "case_id": case_id,
        "client_id": client_id,
        "created_at": now_text(),
        "record_date": today_text(),
        "record_type": "内部メモ",
        "record": f"にゃんともアシスタント整理結果（{mode}）",
        "next_action": "",
        "internal_memo": answer_text,
    })
    execute("UPDATE cases SET updated_at=%(updated_at)s WHERE case_id=%(case_id)s", {"updated_at": now_text(), "case_id": case_id})
    log_action("create", "history", history_id, f"アシスタント結果を相談履歴へ保存：{mode}")
    clear_app_cache()
    return True, "相談履歴に保存しました。"


def render_nyantomo_assistant():
    st.subheader("🐾 にゃんともアシスタント｜常駐AI秘書")
    st.caption("相談履歴・過去案件・カード・保留事項・制度候補を横断して、判断を急がせずに整理します。")

    try:
        ensure_assistant_tables()
    except Exception as e:
        st.warning(f"アシスタント用テーブルの確認に失敗しました：{e}")

    c1, c2, c3 = st.columns(3)
    c1.metric("OpenAI API", "設定あり" if get_openai_api_key() else "未設定")
    c2.metric("AIモデル", get_openai_model())
    try:
        log_count = fetch_one("SELECT COUNT(*) AS count FROM assistant_logs")
        c3.metric("アシスタント履歴", int(log_count.get("count", 0)) if log_count else 0)
    except Exception:
        c3.metric("アシスタント履歴", "未確認")

    st.markdown("---")
    st.markdown("### アシスタントに聞く")

    case_map, case_labels = get_assistant_case_options()
    mode = st.selectbox("モード", ASSISTANT_MODE_OPTIONS)
    selected_label = st.selectbox("対象案件", case_labels)
    selected_case_id = "" if selected_label == "指定しない（全体から検索）" else case_map.get(selected_label, "")
    st.session_state["nyantomo_assistant_selected_case_id"] = selected_case_id

    default_questions = {
        "案件確認": "この案件の現在地と次回確認事項を整理して" if selected_case_id else "Aさんの案件どうだっけ？",
        "案件横断検索": "猫の将来相談だけ見せて",
        "次回確認事項抽出": "この案件の次回確認事項を優先順に整理して",
        "次回確認ダッシュボード": "今後7日以内に確認が必要な案件を出して",
        "制度候補整理": "この案件で確認候補になる制度を整理して",
        "制度候補推薦": "この案件ならどんな制度候補がありそう？",
        "面談メモ作成": "次回面談前に見るメモを作成して",
        "HP記事下書き": "この相談を一般化してHP記事下書きを作って",
        "note記事下書き": "この相談をにゃんとも文体でnote記事下書きにして",
        "note自動生成": "この案件を匿名化してnote下書きを作って",
        "自由相談": "記録をもとに整理して",
    }
    user_question = st.text_area("質問・指示", value=default_questions.get(mode, "記録をもとに整理して"), height=100)

    if mode == "案件横断検索":
        st.info("入力したテーマに近い案件を、案件・履歴・カード・保留・制度候補から横断検索します。例：猫の将来相談、空き家管理、任意後見、相続など。")
    elif mode == "次回確認ダッシュボード":
        st.info("期限超過・近日確認・ヒアリング漏れ・今やらない方がいいことを横断して表示します。")
    elif mode == "制度候補推薦":
        st.info("案件記録に含まれる言葉から制度候補を推薦します。必要性や利用可否は断定しません。")
    elif mode == "note自動生成":
        st.info("案件整理を匿名化・一般化してnote下書きにします。公開前に固有名詞・地域・家族構成が残っていないか確認してください。")

    col_a, col_b = st.columns([1, 1])
    run_ai = col_a.button("にゃんともアシスタントで整理する", type="primary")
    show_source = col_b.checkbox("参照した内部記録も表示する", value=False)

    if run_ai:
        if not normalize_text(user_question):
            st.error("質問・指示を入力してください。")
            return
        with st.spinner("相談記録を探して、にゃんともアシスタントが整理しています..."):
            if mode == "案件横断検索":
                cross_df = search_assistant_cases_by_terms(user_question, limit=30)
                source_text = build_cross_case_search_answer(user_question, cross_df)
                st.session_state["nyantomo_assistant_last_table"] = cross_df
            elif mode == "次回確認ダッシュボード":
                days = 7
                m = re.search(r"(\d+)\s*日", user_question)
                if m:
                    try:
                        days = max(1, min(60, int(m.group(1))))
                    except Exception:
                        days = 7
                due_df = get_assistant_due_cases(days=days)
                source_text = build_due_dashboard_answer(due_df, days=days)
                st.session_state["nyantomo_assistant_last_table"] = due_df
            else:
                source_text = build_nyantomo_assistant_source(user_question, selected_case_id)
                st.session_state["nyantomo_assistant_last_table"] = pd.DataFrame()
            client_id = case_to_client(selected_case_id) if selected_case_id else ""
            if get_openai_api_key():
                prompt = build_nyantomo_assistant_prompt(mode, user_question, source_text)
                try:
                    answer_text, model = call_openai_summary(prompt)
                except Exception as e:
                    st.error("AI整理に失敗しました。APIキー・モデル名・requirements.txt の openai を確認してください。")
                    st.exception(e)
                    return
            else:
                answer_text = build_local_assistant_answer(mode, user_question, source_text)
                model = "local-fallback"

            save_assistant_log(selected_case_id, client_id, mode, user_question, source_text, answer_text, model)
            st.session_state["nyantomo_assistant_last_answer"] = answer_text
            st.session_state["nyantomo_assistant_last_source"] = source_text
            st.session_state["nyantomo_assistant_last_mode"] = mode
            st.session_state["nyantomo_assistant_last_case_id"] = selected_case_id
            clear_app_cache()

    if st.session_state.get("nyantomo_assistant_last_answer"):
        st.markdown("### 整理結果")
        last_table = st.session_state.get("nyantomo_assistant_last_table")
        if isinstance(last_table, pd.DataFrame) and not last_table.empty:
            st.markdown("#### 抽出一覧")
            st.dataframe(last_table, use_container_width=True, hide_index=True)
        st.markdown(st.session_state["nyantomo_assistant_last_answer"])
        st.download_button(
            "整理結果をMarkdownでダウンロード",
            st.session_state["nyantomo_assistant_last_answer"].encode("utf-8-sig"),
            file_name=f"nyantomo_assistant_{today_text()}.md",
            mime="text/markdown",
        )
        last_case_id = st.session_state.get("nyantomo_assistant_last_case_id", "")
        if last_case_id and can_write():
            if st.button("この整理結果を相談履歴に保存する"):
                ok, msg = save_assistant_answer_to_history(
                    last_case_id,
                    st.session_state.get("nyantomo_assistant_last_mode", ""),
                    st.session_state.get("nyantomo_assistant_last_answer", ""),
                )
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
        if show_source:
            st.markdown("### 参照した内部記録")
            st.text_area("内部記録", st.session_state.get("nyantomo_assistant_last_source", ""), height=360)

    st.markdown("---")
    st.markdown("### アシスタント履歴")
    try:
        logs = fetch_df("""
            SELECT al.created_at, al.mode, cl.name AS client_name, c.case_title, al.user_question, al.answer_text, al.model
            FROM assistant_logs al
            LEFT JOIN cases c ON al.case_id = c.case_id
            LEFT JOIN clients cl ON al.client_id = cl.client_id
            ORDER BY al.created_at DESC
            LIMIT 30
        """)
        if logs.empty:
            st.info("まだアシスタント履歴はありません。")
        else:
            st.dataframe(
                logs[["created_at", "mode", "client_name", "case_title", "user_question", "model"]],
                use_container_width=True,
                hide_index=True,
            )
            with st.expander("直近の回答本文を確認"):
                selected_idx = st.selectbox("表示する履歴", list(range(len(logs))), format_func=lambda i: f"{logs.iloc[i]['created_at']}｜{logs.iloc[i]['mode']}｜{logs.iloc[i]['user_question']}")
                st.markdown(normalize_text(logs.iloc[selected_idx]["answer_text"]))
    except Exception as e:
        st.warning(f"アシスタント履歴の読み込みに失敗しました：{e}")

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
    ensure_assistant_tables()
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
    "Ver3.4｜生活制度候補整理",
]
for m in NYANTOMO_V2_MENUS:
    if m not in available_menus:
        available_menus.append(m)

ASSISTANT_MENUS = ["にゃんともアシスタント"]
for m in ASSISTANT_MENUS:
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

if menu == "にゃんともアシスタント":
    render_nyantomo_assistant()
elif menu == "DB接続確認":
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
elif menu == "Ver3.4｜生活制度候補整理":
    render_policy_candidates()
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
