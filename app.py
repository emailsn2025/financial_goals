import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import json
import pandas as pd
import requests
from datetime import date, datetime
import base64
import os
import io
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
from reportlab.lib.enums import TA_LEFT
from reportlab.graphics.shapes import Drawing, Rect, String

st.set_page_config(page_title="Net Worth & Goal Planner", page_icon="📊", layout="wide")

# ══════════════════════════════════════════════════════
# GOOGLE ANALYTICS (GA4)
# ══════════════════════════════════════════════════════
GA_MEASUREMENT_ID = "G-0GRGT501FX"
components.html(f"""
<script>
(function() {{
    if (window.parent.document.getElementById('ga-script-injected')) return;
    var s1 = window.parent.document.createElement('script');
    s1.id = 'ga-script-injected';
    s1.async = true;
    s1.src = '[https://www.googletagmanager.com/gtag/js?id=](https://www.googletagmanager.com/gtag/js?id=){GA_MEASUREMENT_ID}';
    window.parent.document.head.appendChild(s1);

    var s2 = window.parent.document.createElement('script');
    s2.innerHTML = `
        window.dataLayer = window.dataLayer || [];
        function gtag(){{ dataLayer.push(arguments); }}
        gtag('js', new Date());
        gtag('config', '{GA_MEASUREMENT_ID}');
    `;
    window.parent.document.head.appendChild(s2);
}})();
</script>
""", height=0, width=0)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetric"] { border: 1px solid rgba(128,128,128,0.2); border-radius: 10px; padding: 12px 16px; }
    div[data-testid="stMetric"] label { font-size: 13px !important; }
    .badge-green  { background:#059669; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-amber  { background:#d97706; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-red    { background:#dc2626; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-blue   { background:#2563eb; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
</style>
""", unsafe_allow_html=True)

ASSET_CLASSES = ["Debt", "Equity", "Property", "Precious Metals", "Other"]

DEFAULT_CAGR_BY_CLASS = {
    "Equity":          10.0,
    "Debt":             6.0,
    "Property":         7.0,
    "Precious Metals": 10.0,
    "Other":            8.0,
}
LINE_COLORS   = ["#2563eb","#059669","#d97706","#7c3aed","#0d9488","#e11d48","#0891b2","#ca8a04","#6366f1","#14b8a6"]
TAX_RATES     = {"Equity":0.125, "Precious Metals":0.125, "Debt":0.30, "Property":0.30, "Other":0.30}
TODAY         = date.today()
THIS_YEAR     = TODAY.year
YEAR_OPTIONS  = list(range(2000, 2101))

def cal_to_rel(cal_year):
    return max(cal_year - THIS_YEAR, 0)

def rel_to_cal(rel_year):
    return THIS_YEAR + int(rel_year)

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def intl_format(n):
    n = int(round(n)); neg = n < 0; n = abs(n)
    s = f"{n:,}"
    return ("-" if neg else "") + s

def indian_format(n):
    n = int(round(n)); neg = n < 0; n = abs(n); s = str(n)
    if len(s) <= 3: return ("-" if neg else "") + s
    last3 = s[-3:]; rest = s[:-3]; parts = []
    for i, c in enumerate(reversed(rest)):
        if i > 0 and i % 2 == 0: parts.append(",")
        parts.append(c)
    return ("-" if neg else "") + "".join(reversed(parts)) + "," + last3

def _number_format_mode():
    return st.session_state.get("number_format", "Western")

def fmt(n):
    n = round(n)
    if _number_format_mode() == "Indian":
        if abs(n) >= 1e7: return f"{n/1e7:.2f} Cr"
        if abs(n) >= 1e5: return f"{n/1e5:.2f} L"
        return indian_format(n)
    if abs(n) >= 1e9: return f"{n/1e9:.2f} B"
    if abs(n) >= 1e6: return f"{n/1e6:.2f} M"
    return intl_format(n)

def fmt_full(n):
    return indian_format(n) if _number_format_mode() == "Indian" else intl_format(n)

def parse_amount(s):
    if not s or not str(s).strip(): return 0
    c = str(s).replace(",", "").replace(" ", "").strip()
    try: return float(c) if "." in c else int(c)
    except: return 0

def safe_cell(r, col, default):
    v = r.get(col, default)
    return default if pd.isna(v) else v

def compound(principal, rate_pct, years):
    return _compound_cached(float(principal), float(rate_pct), float(years))

def currency_input(label, value, key, **kwargs):
    parsed_val = int(round(value)) if value else 0
    indian_mode = _number_format_mode() == "Indian"
    display = (indian_format(parsed_val) if indian_mode else intl_format(parsed_val)) if parsed_val else ""
    placeholder = "e.g. 18,00,000" if indian_mode else "e.g. 1,800,000"
    raw = st.text_input(label, value=display, key=key,
                        placeholder=placeholder, **kwargs)
    return parse_amount(raw)

def parse_date(s):
    if not s: return TODAY
    if isinstance(s, date): return s
    for fmt_str in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try: return datetime.strptime(str(s).strip(), fmt_str).date()
        except: pass
    return TODAY

def years_between(d1, d2):
    delta = (d2 - d1).days
    return max(delta / 365.25, 0)

def calc_asset_cagr(invested, maturity_amt, purchase_date_str, maturity_date_str):
    try:
        pd_  = parse_date(purchase_date_str)
        md_  = parse_date(maturity_date_str)
        yrs  = years_between(pd_, md_)
        if yrs <= 0 or invested <= 0 or maturity_amt <= 0: return 0.0
        return ((maturity_amt / invested) ** (1 / yrs) - 1) * 100
    except: return 0.0

def asset_tax_rate(asset_class):
    return TAX_RATES.get(asset_class, 0.30)

def asset_net_maturity(invested, maturity_amt, asset_class):
    gain = max(maturity_amt - invested, 0)
    tax  = gain * asset_tax_rate(asset_class)
    return maturity_amt - tax, tax

# ══════════════════════════════════════════════════════
# CACHED PURE COMPUTATION (no session state)
# ══════════════════════════════════════════════════════

@st.cache_data(max_entries=2048)
def _asset_value_at_year_cached(value, cagr, swp_monthly, swp_start_year, target_year, avg_inf):
    val          = float(value)
    swp          = float(swp_monthly or 0)
    swp_start    = int(swp_start_year or 0)
    monthly_rate = (1 + cagr / 100) ** (1/12) - 1
    for yr in range(target_year):
