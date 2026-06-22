import calendar
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


APP_TIMEZONE = ZoneInfo("Asia/Tokyo")


def make_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_jst():
    """アプリ内の現在時刻を日本時間（Asia/Tokyo）で返します。"""
    return datetime.now(APP_TIMEZONE)


def today_jst():
    """アプリ内の今日の日付を日本時間（Asia/Tokyo）で返します。"""
    return now_jst().date()


def now_text():
    """DB保存用の現在時刻文字列。Streamlit Cloudでも日本時間で保存します。"""
    return now_jst().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    """DB保存用の今日の日付文字列。Streamlit Cloudでも日本時間で保存します。"""
    return today_jst().strftime("%Y-%m-%d")


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


def ymd_selectbox_date(label, default=None, start_year=1900, end_year=None, key_prefix="ymd"):
    """
    生年月日など、古い年月日を入力しやすくするための年月日分割入力。
    Streamlit の date_input は年移動がしにくいため、後見対象者の生年月日はこの方式を使います。
    戻り値は datetime.date または None。
    """
    end_year = end_year or today_jst().year
    default_date = date_or_none(default)

    year_options = ["未選択"] + list(range(end_year, start_year - 1, -1))
    if default_date and start_year <= default_date.year <= end_year:
        year_index = year_options.index(default_date.year)
    else:
        year_index = 0

    y_col, m_col, d_col = st.columns(3)
    with y_col:
        year = st.selectbox(f"{label}（年）", year_options, index=year_index, key=f"{key_prefix}_year")

    if year == "未選択":
        with m_col:
            st.selectbox(f"{label}（月）", ["未選択"], key=f"{key_prefix}_month_disabled")
        with d_col:
            st.selectbox(f"{label}（日）", ["未選択"], key=f"{key_prefix}_day_disabled")
        return None

    month_options = list(range(1, 13))
    month_index = (default_date.month - 1) if default_date and default_date.year == year else 0
    with m_col:
        month = st.selectbox(f"{label}（月）", month_options, index=month_index, key=f"{key_prefix}_month")

    max_day = calendar.monthrange(int(year), int(month))[1]
    day_options = list(range(1, max_day + 1))
    day_index = (default_date.day - 1) if default_date and default_date.year == year and default_date.month == month and default_date.day <= max_day else 0
    with d_col:
        day = st.selectbox(f"{label}（日）", day_options, index=day_index, key=f"{key_prefix}_day")

    return date(int(year), int(month), int(day))
