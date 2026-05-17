
import pandas as pd

def fetch_df(sql, params=None):
    if "status" in sql:
        return pd.DataFrame([{"status":"初回相談前","件数":2}])
    return pd.DataFrame([{
        "client_name":"西はぐ",
        "case_title":"西様 自分の相続問題",
        "case_type":"空き家管理",
        "status":"初回相談前",
        "consult_date":"2026-05-17",
        "updated_at":"2026-05-17 09:00"
    }])
