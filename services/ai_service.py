import os

import streamlit as st

from db import execute, fetch_df, fetch_one
from core.audit import log_action
from core.utils import make_id, normalize_text, now_text
from services.backup_service import get_secret_value


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


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
        ("policy_candidates", "Ver3.4生活制度候補整理", ["category", "policy_name", "status", "priority", "municipality", "trigger_words", "reason", "check_items", "caution", "next_action", "official_confirmed", "official_url", "memo"]),
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

## 6. 生活制度候補整理
空き家・高齢者・猫・相続に関する確認候補がある場合だけ書いてください。
候補が薄い場合は「現時点では制度候補は未確定」と書いてください。
- 領域：空き家／高齢者／猫／相続／横断
- 候補名：空き家改修補助／解体補助／耐震補助／住宅セーフティネット／介護保険住宅改修／福祉用具／高齢者住宅／猫の預かり先／動物病院／ペット信託／任意後見／遺言／家族信託／相続人調査など
- なぜ候補になるか：
- まだ確認が必要なこと：所在地、建築年、空き家期間、所有者、要介護認定、猫の状態、本人意思、相続人候補、財産概要、関係者など
- 注意点：制度・手続き・専門職領域が異なるため断定しない
- 次の一手：自治体要綱確認、地域包括・ケアマネ確認、動物病院確認、専門職確認など

## 7. 専門家につなぐ可能性
- 弁護士、司法書士、税理士、宅建士、ケアマネ、包括、動物病院、自治体窓口など
- ただし「必要」と断定せず「可能性」として整理する

## 8. にゃんともとして関われる範囲
- 相談整理、記録、空き家見守り、関係者整理、次回確認など
- 断定や交渉ではなく、整理・保留・伴走の範囲で書く

## 9. にゃんともでは扱わない方がよい範囲
- 紛争、税務判断、登記、医療判断、強い不動産判断など
- 必要に応じて他専門職へつなぐ可能性として書く

## 10. 内部メモ用の短い要約
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
