import re
from io import BytesIO

from db import fetch_one
from core.utils import normalize_text, today_text


def _strip_markdown_for_report(text):
    """PDF出力用にMarkdown記号を控えめに除去する。"""
    value = normalize_text(text)
    for mark in ["**", "__", "###", "##", "#", "`"]:
        value = value.replace(mark, "")
    value = value.replace("・", "- ")
    return value.strip()


def _extract_markdown_section(text, start_keywords, stop_pattern=r"\n\s*#{1,3}\s*\d+\."):
    """AI整理結果から指定見出しの本文を取り出す。"""
    import re
    raw = normalize_text(text)
    for kw in start_keywords:
        m = re.search(rf"(?ms)^\s*#{{0,3}}\s*\d+\.\s*{re.escape(kw)}\s*\n(.*?)(?={stop_pattern}|\Z)", raw)
        if m:
            return _strip_markdown_for_report(m.group(1))
    return ""


def _shorten_report_lines(text, max_lines=6, max_chars=260):
    """A4一枚に収めるため、長すぎる本文を要点行に圧縮する。"""
    cleaned = _strip_markdown_for_report(text)
    if not cleaned:
        return "- 未整理"
    lines = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "・", "○", "●", "*")):
            line = line.lstrip("-・○●* ")
        if line:
            lines.append("- " + line)
    if not lines:
        lines = ["- " + cleaned.replace("\n", " ")]
    joined = "\n".join(lines[:max_lines])
    if len(joined) > max_chars:
        joined = joined[:max_chars].rstrip() + "…"
    return joined


def _build_report_one_liner(theme, organize, next_check, not_decide, pending):
    """Ver2.6：相談者向けPDF上部に出す「今回のひとこと」を作る。"""
    theme_lines = _shorten_report_lines(theme, max_lines=3, max_chars=180).splitlines()
    org_lines = _shorten_report_lines(organize or next_check, max_lines=3, max_chars=180).splitlines()
    nd_lines = _shorten_report_lines(not_decide or pending, max_lines=3, max_chars=180).splitlines()

    def clean_first(lines):
        for line in lines:
            value = normalize_text(line).lstrip("-・○●*□ ")
            if value and value != "未整理":
                return value
        return ""

    main_theme = clean_first(theme_lines)
    action_theme = clean_first(org_lines)
    hold_theme = clean_first(nd_lines)

    if action_theme and main_theme and action_theme != main_theme:
        return f"今は「{main_theme}」を急いで決めるより、「{action_theme}」を少し整理する段階に見えます。"
    if main_theme and hold_theme:
        return f"今は「{main_theme}」について、結論を急がず「{hold_theme}」として置いておける部分があります。"
    if main_theme:
        return f"今は「{main_theme}」について、急いで結論を出すより、見えていることを一緒に整理する段階です。"
    return "今は急いで結論を出すより、見えていることを一緒に整理する段階です。"


def build_client_report_pdf_bytes(case_id, summary_row):
    """カード整理AIの結果から、相談者向けA4一枚PDFを生成する。Ver2.8対応：上段ひとこと・中段4枠・下段注意書き。"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
    except Exception as e:
        raise RuntimeError("PDF出力には reportlab が必要です。requirements.txt に reportlab を追加してください。") from e

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    case = fetch_one("""
        SELECT c.case_title, c.consult_date, c.status, cl.name AS client_name, cl.area
        FROM cases c JOIN clients cl ON c.client_id = cl.client_id
        WHERE c.case_id=%(case_id)s
    """, {"case_id": case_id}) or {}

    summary_text = normalize_text(summary_row.get("summary_text", ""))
    theme = _extract_markdown_section(summary_text, ["今回見えているテーマ", "今回見えていること"])
    not_decide = _extract_markdown_section(summary_text, ["今すぐ決めなくてよいこと", "今決めなくてよいこと"])
    organize = _extract_markdown_section(summary_text, ["少し整理した方がよいこと"])
    next_check = _extract_markdown_section(summary_text, ["次回確認"])
    pending = _extract_markdown_section(summary_text, ["保留していること", "保留事項", "今は保留すること"])

    if not theme:
        theme = summary_text[:220]
    homework = ""
    if organize:
        homework += organize
    if next_check:
        homework += ("\n" if homework else "") + next_check
    if not homework:
        homework = "- 次回の相談で一緒に確認します。"
    if not pending:
        pending = not_decide or "- 今回は、無理に結論を出さず次回も確認します。"

    one_liner = _build_report_one_liner(theme, organize, next_check, not_decide, pending)

    title = "にゃんとも相談整理レポート"
    subtitle = "急いで結論を出すためではなく、いま見えていることを一緒に眺めるためのメモです。"

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 16 * mm
    y = height - 17 * mm

    def wrap_text(value, font_name="HeiseiMin-W3", font_size=10, max_width=165*mm):
        text_value = normalize_text(value)
        result = []
        for paragraph in text_value.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                result.append("")
                continue
            current = ""
            for ch in paragraph:
                test = current + ch
                if c.stringWidth(test, font_name, font_size) <= max_width:
                    current = test
                else:
                    if current:
                        result.append(current)
                    current = ch
            if current:
                result.append(current)
        return result

    def draw_wrapped(x, y0, body, font_name="HeiseiMin-W3", font_size=9, max_width=160*mm, max_lines=5, line_gap=4.6*mm):
        c.setFont(font_name, font_size)
        lines = wrap_text(body, font_name, font_size, max_width)
        used = 0
        for line in lines[:max_lines]:
            c.drawString(x, y0, line)
            y0 -= line_gap
            used += 1
        return y0, used

    def draw_text_block(heading, body, max_lines=5):
        nonlocal y
        c.setFont("HeiseiKakuGo-W5", 11.5)
        c.drawString(margin_x, y, heading)
        y -= 5.8 * mm
        lines = wrap_text(_shorten_report_lines(body, max_lines=max_lines, max_chars=260), "HeiseiMin-W3", 9.2, width - margin_x*2)
        c.setFont("HeiseiMin-W3", 9.2)
        for line in lines[:max_lines]:
            c.drawString(margin_x + 3*mm, y, line)
            y -= 4.8 * mm
        y -= 2.3 * mm

    def draw_one_liner_box():
        nonlocal y
        box_h = 21 * mm
        c.setLineWidth(0.5)
        c.roundRect(margin_x, y-box_h, width - margin_x*2, box_h, 3.5*mm, stroke=1, fill=0)
        c.setFont("HeiseiKakuGo-W5", 10.5)
        c.drawString(margin_x + 4*mm, y - 6*mm, "今回のひとこと")
        draw_wrapped(
            margin_x + 4*mm,
            y - 12.5*mm,
            one_liner,
            "HeiseiMin-W3",
            9.3,
            width - margin_x*2 - 8*mm,
            max_lines=2,
            line_gap=4.3*mm,
        )
        y -= box_h + 7*mm

    def draw_four_frame_checklist():
        nonlocal y
        c.setFont("HeiseiKakuGo-W5", 11.5)
        c.drawString(margin_x, y, "4つの整理枠")
        y -= 6 * mm

        col_gap = 5 * mm
        row_gap = 5 * mm
        box_w = (width - margin_x*2 - col_gap) / 2
        box_h = 43 * mm
        left_x = margin_x
        right_x = margin_x + box_w + col_gap

        frames = [
            ("□ 今回見えていること", theme, left_x, y),
            ("□ 今決めなくてよいこと", not_decide or "- 次回も一緒に確認します。", right_x, y),
            ("□ 次回までの宿題", homework, left_x, y - box_h - row_gap),
            ("□ 保留していること", pending, right_x, y - box_h - row_gap),
        ]

        for heading, body, x, top_y in frames:
            c.roundRect(x, top_y - box_h, box_w, box_h, 3*mm, stroke=1, fill=0)
            c.setFont("HeiseiKakuGo-W5", 9.2)
            c.drawString(x + 3*mm, top_y - 5.2*mm, heading)
            compact = _shorten_report_lines(body, max_lines=5, max_chars=190)
            draw_wrapped(
                x + 3*mm,
                top_y - 11*mm,
                compact,
                "HeiseiMin-W3",
                8.0,
                box_w - 6*mm,
                max_lines=6,
                line_gap=3.9*mm,
            )
        y -= (box_h * 2 + row_gap + 7*mm)

    # header
    c.setFont("HeiseiKakuGo-W5", 17)
    c.drawString(margin_x, y, title)
    y -= 7 * mm
    c.setFont("HeiseiMin-W3", 8.7)
    c.drawString(margin_x, y, subtitle)
    y -= 7 * mm

    # meta box
    c.setLineWidth(0.5)
    c.roundRect(margin_x, y-18*mm, width - margin_x*2, 16*mm, 4*mm, stroke=1, fill=0)
    c.setFont("HeiseiMin-W3", 8.8)
    c.drawString(margin_x + 4*mm, y - 5.5*mm, f"相談者：{normalize_text(case.get('client_name', '')) or '未設定'}")
    c.drawString(margin_x + 4*mm, y - 11.5*mm, f"案件：{normalize_text(case.get('case_title', '')) or '未設定'}")
    c.drawString(width/2, y - 5.5*mm, f"作成日：{today_text()}")
    c.drawString(width/2, y - 11.5*mm, f"整理種別：{normalize_text(summary_row.get('summary_type', 'カード整理AI'))}")
    y -= 24 * mm

    draw_one_liner_box()

    # Ver2.8：重複を避けるため、本文の1〜3表示は行わず、4つの整理枠だけを主役にする
    draw_four_frame_checklist()

    # footer note
    y = max(y, 28*mm)
    c.setLineWidth(0.4)
    note_h = 17 * mm
    c.roundRect(margin_x, y-note_h, width - margin_x*2, note_h, 3*mm, stroke=1, fill=0)
    c.setFont("HeiseiMin-W3", 7.8)
    footer_lines = [
        "※このレポートは、相談内容を整理するためのメモです。",
        "法律・税務・医療・不動産の判断を示すものではありません。",
    ]
    fy = y - 6*mm
    for line in footer_lines:
        c.drawString(margin_x + 4*mm, fy, line)
        fy -= 4.2*mm
    c.drawString(margin_x, 13*mm, "にゃんとも 住まいと猫の相談室")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _build_guardian_report_one_liner(theme, organize, next_check, not_decide, pending):
    """後見整理PDF上部に出す「今回のひとこと」を作る。"""
    theme_lines = _shorten_report_lines(theme, max_lines=3, max_chars=180).splitlines()
    org_lines = _shorten_report_lines(organize or next_check, max_lines=3, max_chars=180).splitlines()
    nd_lines = _shorten_report_lines(not_decide or pending, max_lines=3, max_chars=180).splitlines()

    def clean_first(lines):
        for line in lines:
            value = normalize_text(line).lstrip("-・○●*□ ")
            if value and value != "未整理":
                return value
        return ""

    main_theme = clean_first(theme_lines)
    action_theme = clean_first(org_lines)
    hold_theme = clean_first(nd_lines)

    if action_theme and main_theme and action_theme != main_theme:
        return f"今は「{main_theme}」を急いで決めるより、「{action_theme}」を少し整理する段階に見えます。"
    if main_theme and hold_theme:
        return f"今は「{main_theme}」について、結論を急がず「{hold_theme}」として置いておける部分があります。"
    if main_theme:
        return f"今は「{main_theme}」について、急いで結論を出すより、確認できていることを整理する段階です。"
    return "今は急いで結論を出すより、本人の生活・希望・支援関係を整理する段階です。"


def build_guardian_report_pdf_bytes(ward_id, ai_row):
    """後見カード整理AIの結果から、後見整理A4一枚PDFを生成する。"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
    except Exception as e:
        raise RuntimeError("PDF出力には reportlab が必要です。requirements.txt に reportlab を追加してください。") from e

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    ward = fetch_one("""
        SELECT name, status, guardian_type, facility_name, emergency_level, next_check_date
        FROM guardian_wards
        WHERE ward_id=%(ward_id)s
    """, {"ward_id": ward_id}) or {}

    result_text = normalize_text(ai_row.get("result_text", ""))
    theme = _extract_markdown_section(result_text, ["今回見えているテーマ", "今回見えていること"])
    not_decide = _extract_markdown_section(result_text, ["今すぐ決めなくてよいこと", "今決めなくてよいこと"])
    organize = _extract_markdown_section(result_text, ["少し整理した方がよいこと"])
    next_check = _extract_markdown_section(result_text, ["次回確認"])
    pending = _extract_markdown_section(result_text, ["判断保留", "保留していること", "保留事項", "今は保留すること"])

    if not theme:
        theme = result_text[:220]
    homework = ""
    if organize:
        homework += organize
    if next_check:
        homework += ("\n" if homework else "") + next_check
    if not homework:
        homework = "- 次回の面談・記録確認で一緒に確認します。"
    if not pending:
        pending = not_decide or "- 今回は、無理に結論を出さず次回も確認します。"

    one_liner = _build_guardian_report_one_liner(theme, organize, next_check, not_decide, pending)

    title = "にゃんとも後見整理レポート"
    subtitle = "本人の生活・希望・支援関係を、急がず確認するための内部整理メモです。"

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 16 * mm
    y = height - 17 * mm

    def wrap_text(value, font_name="HeiseiMin-W3", font_size=10, max_width=165*mm):
        text_value = normalize_text(value)
        result = []
        for paragraph in text_value.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                result.append("")
                continue
            current = ""
            for ch in paragraph:
                test = current + ch
                if c.stringWidth(test, font_name, font_size) <= max_width:
                    current = test
                else:
                    if current:
                        result.append(current)
                    current = ch
            if current:
                result.append(current)
        return result

    def draw_wrapped(x, y0, body, font_name="HeiseiMin-W3", font_size=9, max_width=160*mm, max_lines=5, line_gap=4.6*mm):
        c.setFont(font_name, font_size)
        lines = wrap_text(body, font_name, font_size, max_width)
        used = 0
        for line in lines[:max_lines]:
            c.drawString(x, y0, line)
            y0 -= line_gap
            used += 1
        return y0, used

    def draw_one_liner_box():
        nonlocal y
        box_h = 21 * mm
        c.setLineWidth(0.5)
        c.roundRect(margin_x, y-box_h, width - margin_x*2, box_h, 3.5*mm, stroke=1, fill=0)
        c.setFont("HeiseiKakuGo-W5", 10.5)
        c.drawString(margin_x + 4*mm, y - 6*mm, "今回のひとこと")
        draw_wrapped(
            margin_x + 4*mm,
            y - 12.5*mm,
            one_liner,
            "HeiseiMin-W3",
            9.3,
            width - margin_x*2 - 8*mm,
            max_lines=2,
            line_gap=4.3*mm,
        )
        y -= box_h + 7*mm

    def draw_four_frame_checklist():
        nonlocal y
        c.setFont("HeiseiKakuGo-W5", 11.5)
        c.drawString(margin_x, y, "4つの整理枠")
        y -= 6 * mm

        col_gap = 5 * mm
        row_gap = 5 * mm
        box_w = (width - margin_x*2 - col_gap) / 2
        box_h = 43 * mm
        left_x = margin_x
        right_x = margin_x + box_w + col_gap

        frames = [
            ("□ 今回見えていること", theme, left_x, y),
            ("□ 今決めなくてよいこと", not_decide or "- 次回も確認します。", right_x, y),
            ("□ 次回までの確認", homework, left_x, y - box_h - row_gap),
            ("□ 保留・確認中のこと", pending, right_x, y - box_h - row_gap),
        ]

        for heading, body, x, top_y in frames:
            c.roundRect(x, top_y - box_h, box_w, box_h, 3*mm, stroke=1, fill=0)
            c.setFont("HeiseiKakuGo-W5", 9.2)
            c.drawString(x + 3*mm, top_y - 5.2*mm, heading)
            compact = _shorten_report_lines(body, max_lines=5, max_chars=190)
            draw_wrapped(
                x + 3*mm,
                top_y - 11*mm,
                compact,
                "HeiseiMin-W3",
                8.0,
                box_w - 6*mm,
                max_lines=6,
                line_gap=3.9*mm,
            )
        y -= (box_h * 2 + row_gap + 7*mm)

    # header
    c.setFont("HeiseiKakuGo-W5", 17)
    c.drawString(margin_x, y, title)
    y -= 7 * mm
    c.setFont("HeiseiMin-W3", 8.7)
    c.drawString(margin_x, y, subtitle)
    y -= 7 * mm

    # meta box
    c.setLineWidth(0.5)
    c.roundRect(margin_x, y-18*mm, width - margin_x*2, 16*mm, 4*mm, stroke=1, fill=0)
    c.setFont("HeiseiMin-W3", 8.6)
    c.drawString(margin_x + 4*mm, y - 5.5*mm, f"対象者：{normalize_text(ward.get('name', '')) or '未設定'}")
    c.drawString(margin_x + 4*mm, y - 11.5*mm, f"後見類型：{normalize_text(ward.get('guardian_type', '')) or '未設定'}")
    c.drawString(width/2, y - 5.5*mm, f"作成日：{today_text()}")
    c.drawString(width/2, y - 11.5*mm, f"整理種別：{normalize_text(ai_row.get('support_type', 'カード整理AI'))}")
    y -= 24 * mm

    draw_one_liner_box()
    draw_four_frame_checklist()

    # footer note
    y = max(y, 28*mm)
    c.setLineWidth(0.4)
    note_h = 19 * mm
    c.roundRect(margin_x, y-note_h, width - margin_x*2, note_h, 3*mm, stroke=1, fill=0)
    c.setFont("HeiseiMin-W3", 7.6)
    footer_lines = [
        "※このレポートは、後見記録を整理するための内部メモです。",
        "法律・税務・医療・不動産・財産処分の判断を示すものではありません。",
        "家庭裁判所への提出書面そのものではなく、報告準備のための整理資料です。",
    ]
    fy = y - 5.5*mm
    for line in footer_lines:
        c.drawString(margin_x + 4*mm, fy, line)
        fy -= 4.0*mm
    c.drawString(margin_x, 13*mm, "にゃんとも 住まいと猫の相談室")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()
