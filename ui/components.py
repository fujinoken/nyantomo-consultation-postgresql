import html

import streamlit as st

from core.utils import normalize_text


def safe_df_display(df, message, columns=None, height=None):
    if df is None or df.empty:
        st.info(message)
    else:
        show_df = df[columns] if columns else df
        st.dataframe(show_df, use_container_width=True, hide_index=True, height=height)


def ny_card_status_icon(status):
    """カード状態を視覚的に示すアイコンへ変換する。"""
    status = normalize_text(status)
    if status == "気になる":
        return "🟥"
    if status in ["検討中", "保留"]:
        return "🟨"
    if status == "整理済":
        return "🟩"
    return "⬜"


def ny_pending_status_icon(status):
    """保留事項の状態を視覚的に示すアイコンへ変換する。"""
    status = normalize_text(status)
    if status in ["家族確認待ち", "専門家確認待ち"]:
        return "🟧"
    if status in ["保留中", "次回確認"]:
        return "🟨"
    if status in ["整理済", "終了"]:
        return "🟩"
    return "⬜"


def ny_pick_summary(*values, max_len=36):
    """俯瞰カードに出す短い見出しを作る。"""
    for value in values:
        text_value = normalize_text(value)
        if text_value:
            text_value = " ".join(text_value.split())
            if len(text_value) > max_len:
                return text_value[:max_len] + "…"
            return text_value
    return "未入力"


def ny_html(value):
    return html.escape(normalize_text(value)).replace("\n", "<br>")


def render_nyantomo_card_tile(icon, title, headline, status, detail="", footer=""):
    """カードOS俯瞰用の小カードを表示する。"""
    title = ny_html(title)
    headline = ny_html(headline)
    status = ny_html(status)
    detail = ny_html(detail)
    footer = ny_html(footer)
    detail_html = f'<div class="ny-os-detail">{detail}</div>' if detail else ''
    footer_html = f'<div class="ny-os-footer">{footer}</div>' if footer else ''
    st.markdown(f"""
    <div class="ny-os-card">
        <div class="ny-os-title"><span class="ny-os-icon">{icon}</span> {title}</div>
        <div class="ny-os-headline">{headline}</div>
        <div class="ny-os-status">{status}</div>
        {detail_html}
        {footer_html}
    </div>
    """, unsafe_allow_html=True)


def resource_display(value):
    value = normalize_text(value)
    if not value:
        return "□ 不明"
    if value in RESOURCE_STATUS_OPTIONS:
        return value
    return RESOURCE_STATUS_LEGACY_MAP.get(value, value)


def resource_symbol(value):
    return resource_display(value).split(" ")[0]


def resource_text(value):
    parts = resource_display(value).split(" ", 1)
    return parts[1] if len(parts) > 1 else resource_display(value)
