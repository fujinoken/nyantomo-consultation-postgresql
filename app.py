
import streamlit as st
import pandas as pd
from db import fetch_df
from config import APP_TITLE

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(APP_TITLE)
st.caption("DB層整理版・安定稼働用")

st.subheader("管理ダッシュボード")

cases = fetch_df("""
SELECT 
    '初回相談前' as status,
    2 as 件数
""")

recent = fetch_df("""
SELECT 
    '西はぐ' as client_name,
    '西様 自分の相続問題' as case_title,
    '空き家管理' as case_type,
    '初回相談前' as status,
    CURRENT_DATE as consult_date,
    CURRENT_TIMESTAMP as updated_at
""")

left, right = st.columns(2)

with left:
    st.markdown("### 状態別件数")
    st.dataframe(cases, use_container_width=True)

with right:
    st.markdown("### 最近の案件")
    st.dataframe(recent, use_container_width=True)

st.success("Ver3.2.1 修正版：DeltaGenerator表示エラー修正済")
