from db import execute


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
    # Ver3.4：生活制度候補整理 追加テーブル
    # ========================================================
    execute("""
        CREATE TABLE IF NOT EXISTS policy_candidates (
            policy_id TEXT PRIMARY KEY,
            case_id TEXT REFERENCES cases(case_id) ON DELETE CASCADE,
            client_id TEXT REFERENCES clients(client_id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            updated_by TEXT,
            category TEXT,
            policy_name TEXT,
            status TEXT,
            priority TEXT,
            municipality TEXT,
            trigger_words TEXT,
            reason TEXT,
            check_items TEXT,
            caution TEXT,
            next_action TEXT,
            official_confirmed INTEGER DEFAULT 0,
            official_url TEXT,
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
