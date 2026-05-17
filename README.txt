# にゃんとも相談管理システム Ver3.0 PostgreSQL試作版

Ver2.4 SQLite版とは別アプリとして並行テストするためのPostgreSQL版です。

## GitHubにアップロードするファイル

- app.py
- requirements.txt

## Streamlit Cloud設定

Main file path:

```text
app.py
```

## PostgreSQL接続設定

Streamlit Cloudのアプリ管理画面 → Secrets に以下を設定してください。

```toml
[postgres]
url = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```

Supabase / Neon / Railway などのPostgreSQL接続URLを使えます。

## 初期ログイン

- 管理者: admin / admin123
- 職員: staff / staff123

## Ver3.0試作版の主なテーブル

- clients
- cases
- history
- properties
- cats
- family
- photos
- app_users
- audit_logs
- ai_summaries
- line_settings
- line_messages

## 注意

写真ファイル本体はDBに保存せず、Ver3.0試作版ではメタ情報管理を想定しています。
本番化する場合は、Supabase Storage等の外部ストレージ連携が安全です。
