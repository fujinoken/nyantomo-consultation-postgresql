import streamlit as st


def apply_dashboard_css():
    st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1280px;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e9edf5;
        padding: 18px 18px;
        border-radius: 18px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.06);
    }
    div[data-testid="stMetric"] label {
        color: #475569 !important;
        font-weight: 700;
    }
    div[data-testid="stMetricValue"] {
        color: #172033;
        font-weight: 800;
    }
    .ny-card-soft {
        background: linear-gradient(135deg, #fffaf0 0%, #ffffff 72%);
        border: 1px solid #f4ddb3;
        border-radius: 20px;
        padding: 22px;
        min-height: 130px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.045);
    }
    .ny-card-blue {
        background: linear-gradient(135deg, #f3f9ff 0%, #ffffff 75%);
        border: 1px solid #cfe1f7;
        border-radius: 20px;
        padding: 22px;
        min-height: 130px;
        box-shadow: 0 8px 22px rgba(30, 41, 59, 0.045);
    }
    .ny-hero {
        background: #ffffff;
        border: 1px solid #edf0f7;
        border-radius: 22px;
        overflow: hidden;
        box-shadow: 0 10px 26px rgba(30, 41, 59, 0.06);
        margin-bottom: 18px;
    }
    .ny-hero-caption {
        background: #fff1f1;
        padding: 14px 18px;
        font-weight: 700;
        color: #3f3f46;
        border-top: 1px solid #f5d6d6;
    }
    .ny-section-title {
        font-size: 1.18rem;
        font-weight: 800;
        color: #172033;
        margin-bottom: 0.35rem;
    }
    .ny-muted {
        color: #64748b;
        font-size: 0.92rem;
    }
    .ny-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #eef6ff;
        color: #2563eb;
        font-weight: 700;
        font-size: 0.85rem;
        margin-left: 8px;
    }
    .ny-footer {
        text-align: center;
        color: #64748b;
        font-size: 0.88rem;
        padding: 18px 0 4px;
    }
    </style>
    """, unsafe_allow_html=True)
