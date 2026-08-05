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
import zipfile
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
from reportlab.lib.enums import TA_LEFT, TA_CENTER
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
    s1.src = 'https://www.googletagmanager.com/gtag/js?id={GA_MEASUREMENT_ID}';
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
    
    /* Force strictly the Tab Navigation Headers to 26px (prevents enlarging standard buttons) */
    button[role="tab"] p, button[role="tab"] span {
        font-size: 26px !important;
        font-weight: 700 !important;
    }

    /* Force all Page Markdown Headers to 26px */
    h1, h2, h3, h4, h5, h6 {
        font-size: 26px !important;
    }
    
    /* Allow dataframes to wrap text in headers and center align */
    [data-testid="stDataFrame"] th {
        white-space: normal !important;
        word-wrap: break-word !important;
        text-align: center !important;
    }
    [data-testid="stDataFrame"] td {
        white-space: normal !important;
        word-wrap: break-word !important;
        text-align: center !important;
    }
    
    table { text-align: center; }
    th { text-align: center !important; }
    td { text-align: center !important; }
    
    .badge-green  { background:#059669; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-amber  { background:#d97706; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-red    { background:#dc2626; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
    .badge-blue   { background:#2563eb; color:#fff; padding:2px 10px; border-radius:12px; font-size:13px; font-weight:600; display:inline-block; }
</style>
""", unsafe_allow_html=True)

ASSET_CLASSES = ["Debt", "Equity", "Property", "Precious Metals", "Other"]

DEFAULT_TAX_RATES = {
    "Equity": 12.5,
    "Debt": 30.0,
    "Property": 30.0,
    "Precious Metals": 12.5,
    "Other": 30.0
}

DEFAULT_CAGR_BY_CLASS = {
    "Equity":          10.0,
    "Debt":             6.0,
    "Property":         7.0,
    "Precious Metals": 10.0,
    "Other":            8.0,
}

LINE_COLORS   = ["#2563eb","#059669","#d97706","#7c3aed","#0d9488","#e11d48","#0891b2","#ca8a04","#6366f1","#14b8a6"]
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
    return st.session_state.get("number_format", "Indian")

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
    if pd.isna(s) or not str(s).strip(): return None
    if isinstance(s, date): return s
    s_str = str(s).strip().split(' ')[0].split('T')[0]
    for fmt_str in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try: return datetime.strptime(s_str, fmt_str).date()
        except: pass
    return None

def safe_date(d_str):
    try:
        return parse_date(d_str)
    except:
        return None

def years_between(d1, d2):
    if not d1 or not d2: return 0
    delta = (d2 - d1).days
    return max(delta / 365.25, 0)

def calc_asset_cagr(invested, maturity_amt, purchase_date_str, maturity_date_str):
    try:
        pd_  = parse_date(purchase_date_str) or TODAY
        md_  = parse_date(maturity_date_str) or TODAY
        yrs  = years_between(pd_, md_)
        if yrs <= 0 or invested <= 0 or maturity_amt <= 0: return 0.0
        return ((maturity_amt / invested) ** (1 / yrs) - 1) * 100
    except: return 0.0

def calc_asset_maturity(principal, cagr, purchase_date_str, maturity_date_str):
    try:
        pd_  = parse_date(purchase_date_str) or TODAY
        md_  = parse_date(maturity_date_str) or TODAY
        yrs  = years_between(pd_, md_)
        if yrs <= 0 or principal <= 0 or cagr <= 0: return 0.0
        return principal * ((1 + cagr / 100.0) ** yrs)
    except: return 0.0

def asset_tax_rate(asset_class):
    if not st.session_state.get("apply_tax_drag", False):
        return 0.0
    rate = st.session_state.get(f"tax_rate_{asset_class}", DEFAULT_TAX_RATES.get(asset_class, 30.0))
    return float(rate) / 100.0

def asset_net_maturity(cost_basis, maturity_amt, asset_class):
    if not st.session_state.get("apply_tax_drag", False):
        return maturity_amt, 0.0
    gain = max(maturity_amt - cost_basis, 0)
    tax  = gain * asset_tax_rate(asset_class)
    return maturity_amt - tax, tax

def get_asset_eff_cagr(a):
    c = float(a.get("cagr", 0) or 0)
    if st.session_state.get("apply_tax_drag", False) and not a.get("is_virtual_surplus"):
        c = c * (1.0 - asset_tax_rate(a.get("asset_class", "Equity")))
    return c

def display_styled_df(df, height=None):
    kwargs = {
        'hide_index': True, 
        'use_container_width': True
    }
    if height is not None:
        kwargs['height'] = int(height)
        
    if df.empty:
        st.dataframe(df, **kwargs)
        return
        
    styled = df.style.set_properties(**{
        'text-align': 'center',
        'white-space': 'normal',
        'word-wrap': 'break-word'
    }).set_table_styles([
        dict(selector='th', props=[('text-align', 'center'), ('white-space', 'normal')])
    ])
    
    st.dataframe(styled, **kwargs)

def prepare_df_for_export(data_list, default_cols):
    """Deep cleans dataframes for Excel to prevent file corruption from nested objects/formulas."""
    if not data_list:
        return pd.DataFrame(columns=default_cols)
    df = pd.DataFrame(data_list)
    for col in df.columns:
        # Safely convert lists (like tagged_goals) to string representation
        df[col] = df[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, (list, tuple, set)) else x)
        # Prevent Excel formula injection which can corrupt the file
        df[col] = df[col].apply(lambda x: f"'{x}" if isinstance(x, str) and x.startswith(("=", "+", "-", "@")) else x)
    return df

def generate_all_tables_excel_bytes():
    output = io.BytesIO()
    try:
        # Default pandas writer handles standard environments cleanly without strict engine dictation
        with pd.ExcelWriter(output) as writer:
            df_inc = prepare_df_for_export(st.session_state.income, ["name", "monthly", "growth", "start_year", "end_year"])
            df_inc.to_excel(writer, sheet_name="Income", index=False)
            
            df_exp = prepare_df_for_export(st.session_state.expenses, ["name", "monthly", "inflation", "start_year", "end_year"])
            df_exp.to_excel(writer, sheet_name="Expenses", index=False)
            
            df_goals = prepare_df_for_export(st.session_state.goals, ["name", "current_cost", "inflation", "start_year", "end_year", "frequency"])
            df_goals.to_excel(writer, sheet_name="Goals", index=False)
            
            df_assets = prepare_df_for_export(st.session_state.assets, ["name", "asset_type", "asset_class", "purchase_date", "invested", "value", "maturity_amt", "maturity_date", "cagr", "tagged_goals", "swp_monthly", "swp_start_year"])
            df_assets.to_excel(writer, sheet_name="Assets", index=False)
            
            df_liab = prepare_df_for_export(st.session_state.liabilities, ["name", "principal", "rate", "months"])
            df_liab.to_excel(writer, sheet_name="Liabilities", index=False)
            
            if 'summary_df' in st.session_state and not st.session_state['summary_df'].empty:
                df_sum = st.session_state['summary_df'].copy()
                for col in df_sum.columns:
                    df_sum[col] = df_sum[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, (list, tuple, set)) else str(x) if isinstance(x, dict) else x)
                df_sum.to_excel(writer, sheet_name="Goal Summary", index=False)
            else:
                pd.DataFrame(columns=["Goal","Start","End","Cumulative Cost","Target Cost (Used)","Net Present Value","Allocated from Current Corpus","% Met","Status","Current Add'l Contribution Required","Recommendation"]).to_excel(writer, sheet_name="Goal Summary", index=False)
        return output.getvalue(), "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        # Fallback if no valid Excel writer is installed on the host
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as zf:
            if st.session_state.income: zf.writestr("Income.csv", pd.DataFrame(st.session_state.income).to_csv(index=False))
            if st.session_state.expenses: zf.writestr("Expenses.csv", pd.DataFrame(st.session_state.expenses).to_csv(index=False))
            if st.session_state.goals: zf.writestr("Goals.csv", pd.DataFrame(st.session_state.goals).to_csv(index=False))
            
            df_assets = prepare_df_for_export(st.session_state.assets, [])
            if not df_assets.empty: zf.writestr("Assets.csv", df_assets.to_csv(index=False))
                
            if st.session_state.liabilities: zf.writestr("Liabilities.csv", pd.DataFrame(st.session_state.liabilities).to_csv(index=False))
            if 'summary_df' in st.session_state and not st.session_state['summary_df'].empty: 
                zf.writestr("Goal_Summary.csv", st.session_state['summary_df'].to_csv(index=False))
        return output.getvalue(), "zip", "application/zip"

# ══════════════════════════════════════════════════════
# VIRTUAL AUTO-SWEEP SURPLUS
# ══════════════════════════════════════════════════════

@st.cache_data(max_entries=1024)
def swept_surplus_at_year_cached(target_rel_year, eff_cagr, inc_tuple, exp_tuple, proj_start):
    if target_rel_year <= 0: return 0.0
    total_val = 0.0
    for rel_y in range(target_rel_year):
        cal_y = proj_start + rel_y
        
        inc = 0.0
        for e in inc_tuple:
            if e["start_year"] <= cal_y <= e["end_year"]:
                inc += e["monthly"] * 12 * ((1 + e["growth"]/100.0) ** rel_y)
                
        exp = 0.0
        for e in exp_tuple:
            if e["start_year"] <= cal_y <= e["end_year"]:
                exp += e["monthly"] * 12 * ((1 + e["inflation"]/100.0) ** rel_y)
        
        surplus = max(inc - exp, 0)
        remaining_years = target_rel_year - rel_y - 1
        if remaining_years > 0:
            total_val += surplus * ((1 + eff_cagr / 100.0) ** remaining_years)
        else:
            total_val += surplus
            
    return total_val
    
def swept_surplus_at_year(target_rel_year, eff_cagr):
    inc_tup = tuple({"monthly": e["monthly"], "growth": e.get("growth", 5.0), "start_year": int(e.get("start_year", THIS_YEAR)), "end_year": int(e.get("end_year", 2100))} for e in st.session_state.income)
    exp_tup = tuple({"monthly": e["monthly"], "inflation": e.get("inflation", 6.0), "start_year": int(e.get("start_year", THIS_YEAR)), "end_year": int(e.get("end_year", 2100))} for e in st.session_state.expenses)
    proj_start = int(st.session_state.get("proj_start_year", THIS_YEAR))
    return swept_surplus_at_year_cached(target_rel_year, eff_cagr, inc_tup, exp_tup, proj_start)

def get_effective_assets():
    assets = list(st.session_state.assets)
    if st.session_state.get("auto_sweep_surplus", False):
        assets.append({
            "name": "Unallocated Cash",
            "asset_type": "Auto-Sweep Surplus",
            "asset_class": "Debt",
            "purchase_date": str(TODAY),
            "invested": 0,
            "value": 0,
            "maturity_amt": 0,
            "maturity_date": "",
            "cagr": st.session_state.get("sweep_cagr", 8.0),
            "tagged_goals": [],
            "swp_monthly": 0,
            "swp_start_year": 0,
            "is_virtual_surplus": True
        })
    return assets

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
        if swp > 0 and yr >= swp_start:
            monthly_withdrawal = swp * (1 + avg_inf / 100) ** (yr - swp_start)
        else:
            monthly_withdrawal = 0
        for _ in range(12):
            val = val * (1 + monthly_rate) - monthly_withdrawal
            if val < 0: val = 0; break
    return max(val, 0)

@st.cache_data(max_entries=1024)
def _compound_cached(principal, rate_pct, years):
    return principal * (1 + rate_pct / 100) ** years

def clear_asset_cache():
    _asset_value_at_year_cached.clear()
    _goal_occurrences_cached.clear()
    _compound_cached.clear()
    swept_surplus_at_year_cached.clear()

# ══════════════════════════════════════════════════════
# ASSET VALUE WITH SWP
# ══════════════════════════════════════════════════════

def asset_swp_start_rel(a):
    raw = int(a.get("swp_start_year", 0) or 0)
    if raw <= 0:
        return 0
    if raw > 1000:
        return cal_to_rel(raw)
    return raw

def asset_swp_start_display(a):
    raw = int(a.get("swp_start_year", 0) or 0)
    if raw > 1000: return raw
    if raw > 0: return rel_to_cal(raw)
    return THIS_YEAR

def asset_value_at_year(a, target_year, avg_inf=6.0):
    if a.get("is_virtual_surplus"):
        return swept_surplus_at_year(target_year, get_asset_eff_cagr(a))
    return _asset_value_at_year_cached(
        value         = float(a.get("value", 0) or 0),
        cagr          = get_asset_eff_cagr(a),
        swp_monthly   = float(a.get("swp_monthly", 0) or 0),
        swp_start_year= asset_swp_start_rel(a),
        target_year   = int(target_year),
        avg_inf       = float(avg_inf),
    )

# ══════════════════════════════════════════════════════
# SESSION STATE & MIGRATION
# ══════════════════════════════════════════════════════

if "liabilities" in st.session_state and isinstance(st.session_state["liabilities"], (int, float)):
    st.session_state["liabilities"] = []

for key, default in [
    ("income", []), ("expenses", []), ("goals", []), ("assets", []), ("liabilities", []),
    ("projection_years", 30), ("data_version", 0),
    ("ret_opening_corpus", 0), ("ret_goal_name", ""),
    ("ret_annual_return", 0.0), ("ret_tax_class", "Equity"),
    ("ret_custom_tax", 20.0), ("ret_q_withdrawal", 0), ("ret_w_inflation", 7.0),
    ("proj_start_year", THIS_YEAR), ("proj_end_year", THIS_YEAR + 30),
    ("number_format", "Indian"), ("apply_tax_drag", False),
    ("auto_sweep_surplus", False), ("sweep_cagr", 8.0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

for cls in ASSET_CLASSES:
    if f"tax_rate_{cls}" not in st.session_state:
        old_rates = st.session_state.get("custom_tax_rates", {})
        st.session_state[f"tax_rate_{cls}"] = old_rates.get(cls, DEFAULT_TAX_RATES.get(cls, 0.0))

_v = st.session_state.data_version

# ══════════════════════════════════════════════════════
# LIABILITIES MATH
# ══════════════════════════════════════════════════════

def calculate_emi(principal, rate_annual, months):
    p = float(principal)
    m = int(months)
    if p <= 0 or m <= 0: return 0.0
    if rate_annual <= 0: return p / m
    r = float(rate_annual) / 12.0 / 100.0
    return p * r * ((1 + r) ** m) / (((1 + r) ** m) - 1)

@st.cache_data(max_entries=1024)
def liability_value_at_year_cached(principal, rate_annual, emi, months_passed):
    p = float(principal)
    r = float(rate_annual) / 12.0 / 100.0
    e = float(emi)
    for _ in range(int(months_passed)):
        if p <= 0: return 0.0
        interest = p * r
        principal_payment = e - interest
        p -= principal_payment
    return max(p, 0.0)

def liability_value_at_year(l, target_year):
    p = float(l.get("principal", 0))
    r = float(l.get("rate", 8.0))
    m = int(l.get("months", 0))
    emi = calculate_emi(p, r, m)
    return liability_value_at_year_cached(p, r, emi, target_year * 12)

def generate_annual_amortization(l):
    p = float(l.get("principal", 0))
    rate_annual = float(l.get("rate", 8.0))
    r = rate_annual / 12.0 / 100.0
    m = int(l.get("months", 0))
    emi = calculate_emi(p, rate_annual, m)
    
    rows = []
    curr_p = p
    year = 1
    year_interest = 0
    year_principal = 0
    
    for i in range(1, m + 1):
        interest = curr_p * r
        prin_pay = emi - interest
        curr_p -= prin_pay
        year_interest += interest
        year_principal += prin_pay
        
        if i % 12 == 0 or i == m:
            rows.append({
                "Year": f"Year {year}",
                "EMI Paid": fmt_full(year_interest + year_principal),
                "Principal Paid": fmt_full(year_principal),
                "Interest Paid": fmt_full(year_interest),
                "Remaining Balance": fmt_full(max(curr_p, 0))
            })
            year += 1
            year_interest = 0
            year_principal = 0
            
    return rows, emi

# ══════════════════════════════════════════════════════
# COMPUTED VALUES
# ══════════════════════════════════════════════════════

def get_dashboard_eval_year():
    base_yr = int(st.session_state.get("proj_start_year", THIS_YEAR))
    items = st.session_state.income + st.session_state.expenses
    if not items: return base_yr
    
    active_in_base = any(int(e.get("start_year", base_yr) or base_yr) <= base_yr <= int(e.get("end_year", 2100) or 2100) for e in items)
    
    if not active_in_base:
        future_years = [int(e.get("start_year", base_yr) or base_yr) for e in items if int(e.get("start_year", base_yr) or base_yr) > base_yr]
        if future_years:
            return min(future_years)
            
    return base_yr

def total_monthly_income():
    eval_yr = get_dashboard_eval_year()
    return sum(e["monthly"] for e in st.session_state.income
               if int(e.get("start_year", eval_yr) or eval_yr) <= eval_yr <= int(e.get("end_year", 2100) or 2100))

def total_monthly_expense():
    eval_yr = get_dashboard_eval_year()
    return sum(e["monthly"] for e in st.session_state.expenses
               if int(e.get("start_year", eval_yr) or eval_yr) <= eval_yr <= int(e.get("end_year", 2100) or 2100))

def avg_inflation():
    eval_yr = get_dashboard_eval_year()
    active = [e for e in st.session_state.expenses
              if int(e.get("start_year", eval_yr) or eval_yr) <= eval_yr <= int(e.get("end_year", 2100) or 2100)]
    tm = sum(e["monthly"] for e in active)
    if tm == 0: return 6.0
    return sum((e["monthly"]/tm)*e["inflation"] for e in active)

def total_assets():       return sum(a["value"] for a in get_effective_assets() if not a.get("is_virtual_surplus"))
def total_liabilities():  return sum(float(l.get("principal", 0)) for l in st.session_state.liabilities)
def total_net_worth():    return total_assets() - total_liabilities()
def monthly_surplus():    return total_monthly_income() - total_monthly_expense()

def liabilities_at_year(y):
    return sum(liability_value_at_year(l, y) for l in st.session_state.liabilities)

def weighted_cagr():
    ta = total_assets()
    if ta == 0: return 0.0
    return sum((a["value"]/ta) * get_asset_eff_cagr(a) for a in get_effective_assets() if not a.get("is_virtual_surplus"))

def portfolio_at_year(y):
    ai = avg_inflation()
    return sum(asset_value_at_year(a, y, ai) for a in get_effective_assets())

def risk_profile():
    ta = total_assets()
    if ta == 0: return "N/A"
    eff_assets = [a for a in get_effective_assets() if not a.get("is_virtual_surplus")]
    eq   = sum(a["value"] for a in eff_assets if a["asset_class"]=="Equity")/ta*100
    debt = sum(a["value"] for a in eff_assets if a["asset_class"] in ["Debt","Other"])/ta*100
    if eq   > 70: return "Aggressive"
    if debt > 60: return "Conservative"
    return "Balanced"

def goal_names():
    return [g["name"] or f"Goal {i+1}" for i, g in enumerate(st.session_state.goals)]

def goal_start_year(g):
    raw = int(g.get("start_year", 1) or 1)
    return cal_to_rel(raw) if raw > 1000 else max(raw, 0)

def goal_end_year(g):
    raw = int(g.get("end_year", 1) or 1)
    rel = cal_to_rel(raw) if raw > 1000 else max(raw, 0)
    return max(rel, goal_start_year(g))

def goal_frequency(g):
    return max(int(g.get("frequency", 0) or 0), 0)

def goal_uses_cumulative(g):
    return goal_frequency(g) > 0

@st.cache_data(max_entries=256)
def _goal_occurrences_cached(base, inf, start, end, freq):
    occurrences = []
    if freq <= 0:
        occurrences.append((start, _compound_cached(base, inf, start)))
    else:
        yr = start
        while yr < end:
            occurrences.append((yr, _compound_cached(base, inf, yr)))
            yr += freq
    return occurrences

def goal_occurrences(g):
    start = goal_start_year(g)
    end   = goal_end_year(g)
    freq  = goal_frequency(g)
    base  = float(g.get("current_cost", 0) or 0)
    inf   = float(g.get("inflation", 6) or 6)
    return _goal_occurrences_cached(base, inf, start, end, freq)

def goal_projections():
    sorted_goals = sorted(st.session_state.goals, key=lambda g: goal_start_year(g))
    out = []
    for g in sorted_goals:
        occs       = goal_occurrences(g)
        total_cost = sum(cost for _, cost in occs)
        first_cost = occs[0][1] if occs else 0
        last_year  = occs[-1][0] if occs else goal_start_year(g)
        out.append({
            **g,
            "start_year":      goal_start_year(g),
            "end_year":        goal_end_year(g),
            "occurrences":     occs,
            "inflated_cost":   first_cost,
            "cumulative_cost": total_cost,
            "last_year":       last_year,
        })
    return out

def goal_npv(g, wcagr_pct):
    occs = g.get("occurrences") or goal_occurrences(g)
    if wcagr_pct <= 0:
        return sum(cost for _, cost in occs)
    r = wcagr_pct / 100
    return sum(cost / ((1 + r) ** yr) if yr > 0 else cost for yr, cost in occs)

def goal_value_at_start(g, wcagr_pct):
    occs  = g.get("occurrences") or goal_occurrences(g)
    start = goal_start_year(g)
    if wcagr_pct <= 0:
        return sum(cost for _, cost in occs)
    r = wcagr_pct / 100
    return sum(cost / ((1 + r) ** (yr - start)) for yr, cost in occs)

# ── Smart allocation: FRACTIONAL APPROACH TO FIX MATH DISTORTION ──
def smart_allocation():
    ai        = avg_inflation()
    wcagr_pct = weighted_cagr()
    projs     = goal_projections()
    results   = []

    eff_assets = get_effective_assets()
    asset_consumed_frac = {i: 0.0 for i in range(len(eff_assets))}

    for g in projs:
        gname   = g["name"] or ""
        use_cum = goal_uses_cumulative(g)
        cost    = goal_value_at_start(g, wcagr_pct) if use_cum else g["inflated_cost"]
        yr      = g["start_year"]

        remaining_need = cost
        allocated_today = 0.0
        allocated_fv = 0.0
        tagged_names = []
        
        def process_assets_for_smart_alloc(is_tagged_pass):
            nonlocal remaining_need, allocated_today, allocated_fv
            for i, a in enumerate(eff_assets):
                if remaining_need <= 0: break
                is_tagged = gname and gname in (a.get("tagged_goals") or [])
                if (is_tagged_pass and is_tagged) or (not is_tagged_pass and not (a.get("tagged_goals") or [])):
                    if is_tagged_pass and a.get("name") not in tagged_names:
                        tagged_names.append(a.get("name") or "?")
                    
                    avail_frac = 1.0 - asset_consumed_frac[i]
                    if avail_frac <= 0: continue
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = val_at_yr * avail_frac
                    
                    if avail_val <= 0: continue
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        frac_used = draw / val_at_yr
                        asset_consumed_frac[i] += frac_used
                        remaining_need -= draw
                        allocated_fv += draw
                        
                        val_today = a.get("value", 0) if not a.get("is_virtual_surplus") else 0
                        draw_today = val_today * frac_used
                        allocated_today += draw_today

        # 1. Consume Tagged Assets
        process_assets_for_smart_alloc(is_tagged_pass=True)
        tagged_contrib_fv = allocated_fv
        
        # 2. Consume Untagged Assets
        process_assets_for_smart_alloc(is_tagged_pass=False)
        untagged_contrib_fv = allocated_fv - tagged_contrib_fv

        pct = round(min((allocated_fv / cost) * 100, 100) if cost > 0 else 0)
        status = "Fully Funded" if pct >= 100 else ("Partially Funded" if pct > 0 else "Unfunded")
        
        results.append({
            **g,
            "display_cost":     cost,
            "allocated":        allocated_fv,
            "allocated_today":  allocated_today,
            "tagged_contrib":   tagged_contrib_fv,
            "untagged_contrib": untagged_contrib_fv,
            "tagged_assets":    tagged_names,
            "pct":              pct,
            "status":           status,
        })
    return results

def calculate_surplus_today():
    ai        = avg_inflation()
    wcagr_pct = weighted_cagr()
    projs     = goal_projections()
    
    eff_assets = get_effective_assets()
    asset_consumed_frac = {i: 0.0 for i in range(len(eff_assets))}
    
    for g in projs:
        gname   = g["name"] or ""
        use_cum = goal_uses_cumulative(g)
        cost    = goal_value_at_start(g, wcagr_pct) if use_cum else g["inflated_cost"]
        yr      = g["start_year"]
        remaining_need = cost
        
        def process_assets_for_surplus(is_tagged_pass):
            nonlocal remaining_need
            for i, a in enumerate(eff_assets):
                if remaining_need <= 0: break
                is_tagged = gname and gname in (a.get("tagged_goals") or [])
                if (is_tagged_pass and is_tagged) or (not is_tagged_pass and not (a.get("tagged_goals") or [])):
                    avail_frac = 1.0 - asset_consumed_frac[i]
                    if avail_frac <= 0: continue
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = val_at_yr * avail_frac
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        frac_used = draw / val_at_yr
                        asset_consumed_frac[i] += frac_used
                        remaining_need -= draw

        process_assets_for_surplus(is_tagged_pass=True)
        process_assets_for_surplus(is_tagged_pass=False)
        
    surplus_today = 0.0
    for i, a in enumerate(eff_assets):
        if not a.get("is_virtual_surplus"):
            avail_frac = 1.0 - asset_consumed_frac[i]
            if avail_frac > 0:
                val_today = a.get("value", 0)
                surplus_today += val_today * avail_frac
            
    return surplus_today

def compute_granular_asset_allocation():
    ai        = avg_inflation()
    wcagr_pct = weighted_cagr()
    projs     = goal_projections()
    
    eff_assets = get_effective_assets()
    asset_consumed_frac = {i: 0.0 for i in range(len(eff_assets))}
    
    table_rows = []
    tot_allocated_all = 0.0
    
    for g in projs:
        gname   = g["name"] or "(unnamed)"
        use_cum = goal_uses_cumulative(g)
        cost    = goal_value_at_start(g, wcagr_pct) if use_cum else g["inflated_cost"]
        yr      = g["start_year"]
        
        remaining_need = cost
        
        def process_assets(is_tagged_pass):
            nonlocal remaining_need, tot_allocated_all
            for i, a in enumerate(eff_assets):
                if remaining_need <= 0: break
                is_tagged = gname and gname in (a.get("tagged_goals") or [])
                if (is_tagged_pass and is_tagged) or (not is_tagged_pass and not (a.get("tagged_goals") or [])):
                    avail_frac = 1.0 - asset_consumed_frac[i]
                    if avail_frac <= 0: continue
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = val_at_yr * avail_frac
                    if avail_val <= 0: continue
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        frac_used = draw / val_at_yr
                        asset_consumed_frac[i] += frac_used
                        remaining_need -= draw
                        
                        val_today = a.get("value", 0) if not a.get("is_virtual_surplus") else 0
                        draw_today = val_today * frac_used
                        tot_allocated_all += draw_today
                        
                        table_rows.append({
                            "Goal": gname,
                            "Asset Name": a["name"] or "(unnamed)",
                            "Asset Type": a.get("asset_type", "") or "—",
                            "Asset Class": a["asset_class"],
                            "cv_allocated": draw_today,
                            "How much of the Asset in Asset Name column is allocated": fmt_full(draw_today)
                        })

        # 1. Tagged Assets
        process_assets(is_tagged_pass=True)
        # 2. Untagged Assets
        process_assets(is_tagged_pass=False)
                        
        if remaining_need == cost:
            table_rows.append({
                "Goal": gname,
                "Asset Name": "— None (Unfunded) —",
                "Asset Type": "—",
                "Asset Class": "—",
                "cv_allocated": 0.0,
                "How much of the Asset in Asset Name column is allocated": "0"
            })
            
    # 3. Surplus / Unallocated Assets
    for i, a in enumerate(eff_assets):
        if a.get("is_virtual_surplus"): continue
        
        avail_frac = 1.0 - asset_consumed_frac[i]
        if avail_frac > 0.0001:
            val_today = a.get("value", 0)
            if val_today > 0:
                surplus_today = val_today * avail_frac
                tot_allocated_all += surplus_today
                table_rows.append({
                    "Goal": "Surplus / Unallocated",
                    "Asset Name": a["name"] or "(unnamed)",
                    "Asset Type": a.get("asset_type", "") or "—",
                    "Asset Class": a["asset_class"],
                    "cv_allocated": surplus_today,
                    "How much of the Asset in Asset Name column is allocated": fmt_full(surplus_today)
                })

    # Calculate % of Goal's Current Funding
    goal_cv_totals = {}
    for r in table_rows:
        g = r["Goal"]
        goal_cv_totals[g] = goal_cv_totals.get(g, 0.0) + r["cv_allocated"]
        
    final_rows = []
    for r in table_rows:
        g = r["Goal"]
        cv = r["cv_allocated"]
        tot = goal_cv_totals[g]
        pct = (cv / tot * 100) if tot > 0 else 0
        
        r["% of the Goal's Current Funding"] = f"{pct:.1f}%" if tot > 0 else "0.0%"
        del r["cv_allocated"]
        final_rows.append(r)
        
    if final_rows:
        final_rows.append({
            "Goal": "TOTAL",
            "Asset Name": "",
            "Asset Type": "",
            "Asset Class": "",
            "How much of the Asset in Asset Name column is allocated": fmt_full(tot_allocated_all),
            "% of the Goal's Current Funding": ""
        })
        
    return final_rows

def class_mix_chart(granular_rows):
    mix_data = {}
    for g_dict in st.session_state.goals:
        g_name = g_dict["name"] or "(unnamed)"
        mix_data[g_name] = {"Equity": 0, "Debt": 0, "Property": 0, "Precious Metals": 0, "Other": 0}
        
    mix_data["Surplus / Unallocated"] = {"Equity": 0, "Debt": 0, "Property": 0, "Precious Metals": 0, "Other": 0}
        
    for row in granular_rows:
        g = row["Goal"]
        if g == "TOTAL" or g not in mix_data: continue
        c = row["Asset Class"]
        if c == "—": continue
        amt = parse_amount(row["How much of the Asset in Asset Name column is allocated"])
        
        if c in mix_data[g]:
            mix_data[g][c] += amt
        else:
            mix_data[g]["Other"] += amt

    if not mix_data:
        return None

    goals_list = list(mix_data.keys())
    classes = ["Equity", "Debt", "Property", "Precious Metals", "Other"]
    colors_map = {
        "Equity": "#2563eb",
        "Debt": "#f97316",
        "Property": "#059669",
        "Precious Metals": "#eab308",
        "Other": "#64748b"
    }
    
    fig_mix = go.Figure()
    for cls in classes:
        pcts = []
        for g in goals_list:
            total_g = sum(mix_data[g].values())
            if total_g > 0:
                pcts.append((mix_data[g][cls] / total_g) * 100)
            else:
                pcts.append(0)
                
        fig_mix.add_trace(go.Bar(
            y=goals_list,
            x=pcts,
            name=cls,
            orientation='h',
            marker=dict(color=colors_map[cls]),
            hovertemplate="%{y} - " + cls + ": %{x:.1f}%<extra></extra>"
        ))
        
    fig_mix.update_layout(
        barmode='stack',
        xaxis=dict(title="Percentage (%)", range=[0, 100]),
        yaxis=dict(autorange="reversed", automargin=True),
        height=max(250, len(goals_list)*40 + 150),
        margin=dict(l=220, r=20, t=30, b=20),
        legend=dict(orientation="h", y=-0.2)
    )
    return fig_mix

def expense_coverage_years():
    if not st.session_state.income or not st.session_state.expenses: return None
    eval_yr = get_dashboard_eval_year()
    for y in range(1, 51):
        cal_y = eval_yr + y
        inc = sum(compound(e["monthly"], e.get("growth",5.0), y) for e in st.session_state.income
                  if int(e.get("start_year", eval_yr) or eval_yr) <= cal_y <= int(e.get("end_year", 2100) or 2100))
        exp = sum(compound(e["monthly"], e["inflation"], y) for e in st.session_state.expenses
                  if int(e.get("start_year", eval_yr) or eval_yr) <= cal_y <= int(e.get("end_year", 2100) or 2100))
        if exp > inc: return y
    return None

def get_recommendations():
    recs  = []
    alloc = smart_allocation()
    ai    = avg_inflation()
    ta    = total_assets()
    eff_assets = [a for a in get_effective_assets() if not a.get("is_virtual_surplus")]

    shortfalls = [a for a in alloc if a["pct"] < 100]
    if shortfalls:
        g   = shortfalls[0]
        gap = g["display_cost"] - g["allocated"]
        sip = gap / (g["start_year"]*12) if g["start_year"] > 0 else gap
        recs.append(("📊","Cover Shortfall",
            f'"{g["name"]}" is {g["pct"]}% funded. Save ~{fmt(sip)}/month to close the {fmt(gap)} gap.'))

    for a in eff_assets:
        if get_asset_eff_cagr(a) < ai and st.session_state.expenses:
            recs.append(("⚠️","Inflation Warning",
                f'"{a["name"]}" returns {get_asset_eff_cagr(a):.1f}% — below avg inflation {ai:.1f}%.'))

    if any(goal_start_year(g)<=3 for g in st.session_state.goals) and \
       any(a["asset_class"]=="Equity" for a in eff_assets):
        recs.append(("🔄","Horizon Matching",
            "Goals within 3 years detected. Consider shifting equity into debt for capital protection."))

    if ta > 0:
        ct = {}
        for a in eff_assets: ct[a["asset_class"]] = ct.get(a["asset_class"],0)+a["value"]
        for cls, val in ct.items():
            if (val/ta)*100 > 60:
                recs.append(("⚖️","Diversification Alert", f"{cls} is {round((val/ta)*100)}% of portfolio."))

    tm = total_monthly_expense()
    if tm > 0:
        liq = sum(a["value"] for a in eff_assets if a["asset_class"] in ["Debt","Other"])
        e6m = tm*6*(1+ai/100)
        if liq < e6m:
            recs.append(("🛡️","Emergency Fund",
                f"Keep {fmt(e6m)} (6 months expenses) in liquid assets. Current: {fmt(liq)}."))

    cross = expense_coverage_years()
    if cross and cross <= 20:
        recs.append(("📉","Income Gap Ahead", f"Expenses projected to overtake income by Year {cross}."))

    return recs[:5]

# ══════════════════════════════════════════════════════
# EXCEL IMPORT HELPERS
# ══════════════════════════════════════════════════════

def import_goals_from_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":        ["goal name","name","goal"],
            "current_cost":["cost today","today's cost","cost","amount","current cost"],
            "inflation":   ["inflation %","inflation","inflation rate"],
            "start_year":  ["start year","start","from year","target year","year"],
            "end_year":    ["end year","end","to year","until year"],
            "frequency":   ["frequency (yrs)","frequency (years)","frequency","freq","every n years","recurrence"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None

        new_goals = []
        for _, row in df.iterrows():
            g = {"name":"","current_cost":0,"inflation":6.0,
                 "start_year":1,"end_year":1,"frequency":0}
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field == "current_cost":
                        g[field] = parse_amount(str(val))
                    elif field == "inflation":
                        g[field] = float(str(val).replace("%","").strip() or 6)
                    elif field in ("start_year","end_year"):
                        raw_yr = int(float(str(val).strip() or THIS_YEAR))
                        if raw_yr <= 1000: raw_yr = THIS_YEAR + raw_yr
                        g[field] = max(2000, min(raw_yr, 2100))
                    elif field == "frequency":
                        g[field] = int(float(str(val).strip() or 0))
                    else:
                        g[field] = str(val).strip()
            g["end_year"] = max(g["end_year"], g["start_year"])
            new_goals.append(g)
        return new_goals, None
    except Exception as e:
        return [], str(e)

def import_assets_from_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":           ["asset name","name","asset"],
            "asset_type":     ["asset type","type","instrument type","sub type","subtype","instrument"],
            "asset_class":    ["class","asset class"],
            "purchase_date":  ["purchase date","buy date","date of purchase","start date"],
            "invested":       ["invested amount","invested","cost","purchase price","buy price"],
            "value":          ["current value","value","current","market value"],
            "maturity_amt":   ["maturity amount","maturity","maturity value","fv","future value"],
            "maturity_date":  ["maturity date","due date","end date"],
            "cagr":           ["cagr %","cagr","return %","expected return","return"],
            "tagged_goals":   ["tag goals","goals","tagged goals","goal"],
            "swp_monthly":    ["swp monthly","swp","swp amount","swp /mo"],
            "swp_start_year": ["swp start yr","swp start year","swp year","swp from"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None

        new_assets = []
        defaulted_cagr_list = []
        for _, row in df.iterrows():
            a = {
                "name":"","asset_type":"","asset_class":"Equity","purchase_date":"","invested":0,
                "value":0,"maturity_amt":0,"maturity_date":"","cagr":0.0,
                "tagged_goals":[],"swp_monthly":0,"swp_start_year":0,
            }
            cagr_provided = False
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field in ("invested","value","maturity_amt","swp_monthly"):
                        a[field] = parse_amount(str(val))
                    elif field == "cagr":
                        a[field] = float(str(val).replace("%","").strip() or 0)
                        cagr_provided = True
                    elif field == "swp_start_year":
                        raw_yr = int(float(str(val).strip() or 0))
                        if 0 < raw_yr <= 1000: raw_yr = THIS_YEAR + raw_yr
                        a[field] = max(0, min(raw_yr, 2100)) if raw_yr > 0 else 0
                    elif field == "asset_class":
                        cls = str(val).strip()
                        a[field] = cls if cls in ASSET_CLASSES else "Equity"
                    elif field == "tagged_goals":
                        raw = str(val).strip()
                        a[field] = [x.strip() for x in raw.split(",") if x.strip()]
                    elif field in ("purchase_date","maturity_date"):
                        a[field] = str(val).strip()
                    else:
                        a[field] = str(val).strip()

            inv = a["invested"]
            mat = a["maturity_amt"]
            pdate = a["purchase_date"]
            mdate = a["maturity_date"]
            cls = a["asset_class"]

            if mat > 0 and inv > 0 and mdate and not cagr_provided:
                auto = round(calc_asset_cagr(inv, mat, pdate or str(TODAY), mdate), 2)
                if auto > 0:
                    a["cagr"] = auto
                    cagr_provided = True

            if not cagr_provided:
                a["cagr"] = DEFAULT_CAGR_BY_CLASS.get(cls, 8.0)
                defaulted_cagr_list.append((a["name"] or "(unnamed)", cls, a["cagr"]))

            if a["value"] <= 0 and inv > 0:
                a["value"] = inv

            if a["maturity_amt"] <= 0 and a["cagr"] > 0 and mdate:
                principal = inv if inv > 0 else a["value"]
                a["maturity_amt"] = int(round(calc_asset_maturity(principal, a["cagr"], pdate or str(TODAY), mdate)))

            new_assets.append(a)
        return new_assets, defaulted_cagr_list, None
    except Exception as e:
        return [], [], str(e)

def import_liabilities_from_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":       ["loan name", "name", "loan", "description"],
            "principal":  ["outstanding principal", "principal", "balance", "amount", "loan amount"],
            "rate":       ["interest rate %", "interest rate", "rate %", "rate", "roi"],
            "months":     ["remaining months", "months", "tenure", "duration", "term"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None

        new_liab = []
        for _, row in df.iterrows():
            l = {"name": "", "principal": 0, "rate": 8.0, "months": 12}
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field == "principal":
                        l[field] = parse_amount(str(val))
                    elif field == "rate":
                        l[field] = float(str(val).replace("%", "").strip() or 8.0)
                    elif field == "months":
                        l[field] = int(float(str(val).strip() or 12))
                    else:
                        l[field] = str(val).strip()
            new_liab.append(l)
        return new_liab, None
    except Exception as e:
        return [], str(e)

# ══════════════════════════════════════════════════════
# CHARTS
# ══════════════════════════════════════════════════════

def import_income_from_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":       ["source","name","income source","description"],
            "monthly":    ["monthly rs","monthly","amount","monthly amount","rs"],
            "growth":     ["growth %/yr","growth","growth rate","growth %","rate"],
            "start_year": ["start year","start","from year","from"],
            "end_year":   ["end year","end","to year","until","to"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None
        new_income = []
        for _, row in df.iterrows():
            inc = {"name":"","monthly":0,"growth":5.0,"start_year":THIS_YEAR,"end_year":THIS_YEAR+30}
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field == "monthly": inc[field] = parse_amount(str(val))
                    elif field == "growth": inc[field] = float(str(val).replace("%","").strip() or 5)
                    elif field in ("start_year","end_year"):
                        raw = int(float(str(val).strip() or THIS_YEAR))
                        if raw <= 1000: raw = THIS_YEAR + raw
                        inc[field] = max(2000, min(raw, 2100))
                    else: inc[field] = str(val).strip()
            inc["end_year"] = max(inc["end_year"], inc["start_year"])
            new_income.append(inc)
        return new_income, None
    except Exception as e:
        return [], str(e)

def import_expenses_from_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":       ["name","expense","description","category"],
            "monthly":    ["monthly rs","monthly","amount","monthly amount","rs"],
            "inflation":  ["inflation %","inflation","inflation rate","rate"],
            "start_year": ["start year","start","from year","from"],
            "end_year":   ["end year","end","to year","until","to"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None
        new_expenses = []
        for _, row in df.iterrows():
            exp = {"name":"","monthly":0,"inflation":6.0,"start_year":THIS_YEAR,"end_year":THIS_YEAR+30}
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field == "monthly": exp[field] = parse_amount(str(val))
                    elif field == "inflation": exp[field] = float(str(val).replace("%","").strip() or 6)
                    elif field in ("start_year","end_year"):
                        raw = int(float(str(val).strip() or THIS_YEAR))
                        if raw <= 1000: raw = THIS_YEAR + raw
                        exp[field] = max(2000, min(raw, 2100))
                    else: exp[field] = str(val).strip()
            exp["end_year"] = max(exp["end_year"], exp["start_year"])
            new_expenses.append(exp)
        return new_expenses, None
    except Exception as e:
        return [], str(e)

def expense_income_chart():
    years = list(range(st.session_state.projection_years+1))
    proj_start = int(st.session_state.get("proj_start_year", THIS_YEAR))
    fig   = go.Figure()
    exp_totals = [0.0]*len(years)
    for i, e in enumerate(st.session_state.expenses):
        e_start = int(e.get("start_year", THIS_YEAR) or THIS_YEAR)
        e_end   = int(e.get("end_year", 2100) or 2100)
        vals = []
        for y in years:
            cal_y = proj_start + y
            if cal_y < e_start or cal_y > e_end:
                vals.append(0.0)
            else:
                vals.append(compound(e["monthly"], e["inflation"], cal_y - proj_start))
        
        for j,v in enumerate(vals): exp_totals[j]+=v
        fig.add_trace(go.Scatter(x=years, y=vals, name=e["name"] or f"Expense {i+1}",
            line=dict(color=LINE_COLORS[i%len(LINE_COLORS)], width=2),
            hovertemplate="%{y:,.0f}<extra>%{fullData.name}</extra>"))
            
    if st.session_state.expenses:
        fig.add_trace(go.Scatter(x=years, y=exp_totals, name="Total Expenses",
            line=dict(color="#dc2626", width=3, dash="dash"),
            hovertemplate="%{y:,.0f}<extra>Total Expenses</extra>"))
            
    if st.session_state.income:
        inc = []
        for y in years:
            cal_y = proj_start + y
            m_sum = sum(compound(e["monthly"], e.get("growth",5.0), cal_y - proj_start) 
                        for e in st.session_state.income 
                        if int(e.get("start_year", THIS_YEAR) or THIS_YEAR) <= cal_y <= int(e.get("end_year", 2100) or 2100))
            inc.append(m_sum)
        fig.add_trace(go.Scatter(x=years, y=inc, name="Total Income",
            line=dict(color="#059669", width=3, dash="dot"),
            hovertemplate="%{y:,.0f}<extra>Total Income</extra>"))
            
    fig.update_layout(title="Monthly Income vs Expenses", xaxis_title="Year", yaxis_title="Amount",
        hovermode="x unified", template=None, height=400,
        legend=dict(orientation="h", y=-0.15), margin=dict(l=60,r=20,t=50,b=60))
    return fig

def asset_chart():
    ai    = avg_inflation()
    max_y = max(st.session_state.projection_years, max((goal_end_year(g) for g in st.session_state.goals), default=30))
    years = list(range(max_y+1))
    fig   = go.Figure(); totals=[0.0]*len(years)
    for i, a in enumerate(get_effective_assets()):
        if a.get("is_virtual_surplus"): continue
        vals = [asset_value_at_year(a, y, ai) for y in years]
        for j,v in enumerate(vals): totals[j]+=v
        swp_amt = a.get("swp_monthly",0) or 0
        swp_yr  = asset_swp_start_display(a)
        name    = a["name"] or f"Asset {i+1}"
        label   = f"{name} (SWP {fmt_full(swp_amt)}/mo from {swp_yr})" if swp_amt else name
        fig.add_trace(go.Scatter(x=years, y=vals, name=label,
            line=dict(color=LINE_COLORS[i%len(LINE_COLORS)], width=2),
            hovertemplate="%{y:,.0f}<extra>%{fullData.name}</extra>"))
    if [a for a in get_effective_assets() if not a.get("is_virtual_surplus")]:
        fig.add_trace(go.Scatter(x=years, y=totals, name="Total Portfolio",
            line=dict(color="#1e293b", width=3, dash="dash"),
            hovertemplate="%{y:,.0f}<extra>Total Portfolio</extra>"))
    fig.update_layout(title="Asset Growth Projection (net of SWP)", xaxis_title="Year", yaxis_title="Amount",
        hovermode="x unified", template=None, height=400,
        legend=dict(orientation="h", y=-0.2), margin=dict(l=60,r=20,t=50,b=80))
    return fig

def allocation_pie_chart():
    ct = {}
    for a in get_effective_assets():
        if a.get("is_virtual_surplus"): continue
        ct[a["asset_class"]] = ct.get(a["asset_class"],0)+a["value"]
    labels,values = list(ct.keys()), list(ct.values())
    if not values or sum(values) == 0: return None
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.45,
        marker=dict(colors=LINE_COLORS[:len(labels)]),
        textinfo="label+percent", textposition="outside",
        hovertemplate="%{label}: %{value:,.0f}<extra></extra>"))
    fig.update_layout(title="Asset Allocation", template=None, height=350,
        margin=dict(l=20,r=20,t=50,b=20), showlegend=False)
    return fig

def asset_type_pie_chart():
    ct = {}
    for a in get_effective_assets():
        if a.get("is_virtual_surplus"): continue
        t = (a.get("asset_type") or "").strip() or "Unspecified"
        ct[t] = ct.get(t, 0) + a["value"]
    labels, values = list(ct.keys()), list(ct.values())
    if not values or sum(values) == 0: return None
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.45,
        marker=dict(colors=LINE_COLORS[:len(labels)]),
        textinfo="label+percent", textposition="outside",
        hovertemplate="%{label}: %{value:,.0f}<extra></extra>"))
    fig.update_layout(title="Asset Allocation by Type", template=None, height=350,
        margin=dict(l=20,r=20,t=50,b=20), showlegend=False)
    return fig

def nw_bar_chart():
    max_y = max(30, max((goal_end_year(g) for g in st.session_state.goals), default=30))
    years = list(range(0, max_y+1, 5))
    vals  = [max(portfolio_at_year(y) - liabilities_at_year(y), 0) for y in years]
    fig   = go.Figure(go.Bar(x=[f"Yr {y}" for y in years], y=vals,
        marker_color="#2563eb", hovertemplate="%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Net Worth Projection (Assets - Liabilities)", template=None, height=350,
        margin=dict(l=60,r=20,t=50,b=40), yaxis_title="Amount")
    return fig

def retirement_drawdown_chart(rows):
    quarters_label  = [r["Quarter"] for r in rows]
    corpus_vals     = [r["Opening Corpus"] for r in rows]
    withdrawal_vals = [r["Withdrawal"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=quarters_label, y=corpus_vals, name="Corpus",
        fill="tozeroy", fillcolor="rgba(37,99,235,0.1)",
        line=dict(color="#2563eb", width=2),
        hovertemplate="%{y:,.0f}<extra>Corpus</extra>"))
    fig.add_trace(go.Bar(x=quarters_label, y=withdrawal_vals, name="Quarterly Withdrawal",
        marker_color="rgba(220,38,38,0.5)", yaxis="y2",
        hovertemplate="%{y:,.0f}<extra>Withdrawal</extra>"))
    fig.update_layout(
        title="Corpus Drawdown Over Time",
        xaxis=dict(title="Quarter", tickangle=-45,
            tickvals=quarters_label[::4],
            ticktext=[quarters_label[i] for i in range(0,len(quarters_label),4)]),
        yaxis=dict(title="Corpus", tickformat=","),
        yaxis2=dict(title="Withdrawal", overlaying="y", side="right", showgrid=False),
        hovermode="x unified", template=None, height=420,
        legend=dict(orientation="h", y=-0.25), margin=dict(l=60,r=60,t=50,b=80))
    return fig

# ══════════════════════════════════════════════════════
# RETIREMENT SIMULATION
# ══════════════════════════════════════════════════════

@st.cache_data(max_entries=64)
def retirement_simulation(opening_corpus, annual_return_pct, asset_class,
                           quarterly_withdrawal, withdrawal_inflation_pct,
                           tax_rate_override=None, start_cal_year=THIS_YEAR):
    tax_rate      = tax_rate_override if tax_rate_override is not None else asset_tax_rate(asset_class)
    quarterly_ret = (1 + annual_return_pct / 100) ** 0.25 - 1
    corpus        = float(opening_corpus)
    total_invested= float(opening_corpus)
    total_withdrawn = 0.0
    rows = []; quarter = 0

    while corpus > 0:
        quarter += 1
        year_offset = (quarter-1)//4
        cal_year = start_cal_year + year_offset
        q_label = f"{cal_year} Q{(quarter-1)%4+1}"
        inflation_factor = (1 + withdrawal_inflation_pct/100) ** year_offset
        withdrawal = min(quarterly_withdrawal * inflation_factor, corpus)

        total_value    = corpus
        cost_basis_pct = min(total_invested/total_value, 1.0) if total_value > 0 else 1.0
        gain_portion   = withdrawal * (1 - cost_basis_pct)
        tax_amount     = gain_portion * tax_rate
        net_withdrawal = withdrawal + tax_amount

        if corpus - net_withdrawal < 0:
            actual_gross   = corpus / (1 + (1-cost_basis_pct)*tax_rate)
            gain_portion   = actual_gross * (1-cost_basis_pct)
            tax_amount     = gain_portion * tax_rate
            net_withdrawal = corpus
            withdrawal     = actual_gross
            corpus_after   = 0
        else:
            corpus_after = corpus - net_withdrawal

        if corpus > 0:
            total_invested = max(total_invested - cost_basis_pct*withdrawal, 0)

        gross_return = corpus_after * quarterly_ret
        corpus_end   = corpus_after + gross_return
        net_gain     = corpus_end - corpus

        rows.append({
            "Quarter": q_label, "Opening Corpus": corpus,
            "Withdrawal": withdrawal, "Return %": f"{annual_return_pct:.1f}%",
            "Gross Return": gross_return, "Gain Portion": gain_portion,
            "Tax Rate": f"{tax_rate*100:.1f}%", "Tax Amount": tax_amount,
            "Net Return": gross_return-tax_amount, "Net Gain": net_gain,
            "Closing Corpus": corpus_end,
        })
        total_withdrawn += withdrawal
        corpus = corpus_end
        if corpus <= 1: corpus = 0
        if quarter > 4000: break

    return rows, total_withdrawn

# ══════════════════════════════════════════════════════
# PDF EXPORT
# ══════════════════════════════════════════════════════

def _pdf_table(headers, rows, col_widths=None, font_size=7):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
        ('FONTSIZE',     (0,0), (-1,-1), font_size),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID',         (0,0), (-1,-1), 0.4, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING',   (0,0), (-1,-1), 3),
        ('BOTTOMPADDING',(0,0), (-1,-1), 3),
    ]))
    return t

def _pdf_progress_bar(pct, width=130, height=14):
    pct = min(max(pct, 0), 100)
    fill_color = colors.HexColor('#059669') if pct >= 100 else (
                 colors.HexColor('#d97706') if pct > 50 else colors.HexColor('#dc2626'))
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor('#e2e8f0'), strokeColor=None))
    fill_w = width * pct / 100
    if fill_w > 0:
        d.add(Rect(0, 0, fill_w, height, fillColor=fill_color, strokeColor=None))
    text_color = colors.white if pct > 20 else colors.HexColor('#334155')
    d.add(String(width/2, height/2 - 3, f"{round(pct)}%", fontSize=8,
                 fillColor=text_color, textAnchor='middle'))
    return d

def _fig_to_pdf_image(fig, width_cm=25, height_cm=9.5, name="chart", errors=None):
    if fig is None:
        return None
    try:
        fig = go.Figure(fig)
        fig.update_layout(paper_bgcolor="white", plot_bgcolor="white", font=dict(color="#1e293b"))
        png_bytes = fig.to_image(format="png", width=1500, height=int(1500 * height_cm / width_cm), scale=2)
        return RLImage(io.BytesIO(png_bytes), width=width_cm*cm, height=height_cm*cm)
    except Exception as e:
        if errors is not None:
            errors.append((name, f"{type(e).__name__}: {e}"))
        return None

def generate_full_pdf_report():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.2*cm, rightMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm,
        title="Net Worth & Goal Planner Report",
    )
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle('H', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor('#2563eb'), spaceBefore=10, spaceAfter=5)
    sub_style = ParagraphStyle('S', parent=styles['Heading3'], fontSize=10, textColor=colors.HexColor('#334155'), spaceBefore=6, spaceAfter=3)
    normal_style = ParagraphStyle('N', parent=styles['Normal'], fontSize=9, leading=13)
    caption_style = ParagraphStyle('C', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#64748b'))

    story = []
    chart_errors = []

    # ══════════════════════════════════════════════════════
    # HYBRID PDF BANNER (Mockup Implementation)
    # ══════════════════════════════════════════════════════
    # Banner Colors
    navy_bg = colors.HexColor('#1e293b')
    dark_navy_bg = colors.HexColor('#0f172a')
    white_text = colors.white
    grey_text = colors.HexColor('#94a3b8')
    warning_color = colors.HexColor('#f59e0b')
    privacy_color = colors.HexColor('#34d399')

    # Banner Specific Paragraph Styles
    b_title_style = ParagraphStyle('BT', parent=styles['Normal'], fontSize=16, textColor=white_text, fontName='Helvetica-Bold', spaceAfter=4)
    b_sub_style = ParagraphStyle('BS', parent=styles['Normal'], fontSize=9, textColor=grey_text)
    b_center_style = ParagraphStyle('BC', parent=styles['Normal'], fontSize=13, textColor=grey_text, fontName='Helvetica-Oblique', alignment=TA_CENTER)
    b_disc_style = ParagraphStyle('BD', parent=styles['Normal'], fontSize=7.5, textColor=grey_text, leading=11)

    # Row 1 Content
    left_content = [
        Paragraph("📊 Net Worth &amp; Goal Planner", b_title_style),
        Paragraph("Project your finances · Track goals · Allocate assets", b_sub_style)
    ]
    center_content = Paragraph("Developed by Sandeep Narang", b_center_style)
    
    # Grab the shiftgaze logo if it exists
    logo_path = os.path.join(os.path.dirname(__file__), "shiftgaze_logo.jpg")
    right_content = ""
    if os.path.exists(logo_path):
        # Setting kind='proportional' prevents the image from distorting
        right_content = RLImage(logo_path, width=4*cm, height=1.6*cm, kind='proportional')

    # Row 2 Content
    disclaimer_text = f"<font color='{warning_color}'>⚠️ <b>Disclaimer:</b></font> This calculator is for personal planning only and does not constitute financial advice. Projections are estimates — actual returns, inflation and tax may differ. Consult a qualified financial advisor before making investment decisions."
    privacy_text = f"<font color='{privacy_color}'>🔒 <b>Privacy:</b></font> Your financial data — income, expenses, goals, and assets — never leaves your browser session. It is never stored, transmitted, or retained anywhere; it's lost when you close the tab unless you download it using the Save button."
    
    row2_content = [
        Paragraph(disclaimer_text, b_disc_style),
        Spacer(1, 4),
        Paragraph(privacy_text, b_disc_style)
    ]

    # Construct the Table (Width totals ~27.3cm which fits perfectly within A4 margins)
    banner_data = [
        [left_content, center_content, right_content],
        [row2_content, '', '']  # Empty strings are needed as placeholders for the merged cells
    ]

    banner_table = Table(banner_data, colWidths=[10.5*cm, 10.5*cm, 6.3*cm])
    banner_table.setStyle(TableStyle([
        # Row 1 Background & Alignment
        ('BACKGROUND', (0, 0), (2, 0), navy_bg),
        ('VALIGN', (0, 0), (2, 0), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),  # Push logo to the far right
        
        # Row 2 Background, Spanning & Alignment
        ('BACKGROUND', (0, 1), (2, 1), dark_navy_bg),
        ('SPAN', (0, 1), (2, 1)),            # Merge the bottom row across all 3 columns
        ('VALIGN', (0, 1), (2, 1), 'MIDDLE'),
        
        # Global Table Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        # Add a subtle border matching your UI
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#334155')),
    ]))

    # Add the Banner to the PDF
    story.append(banner_table)
    story.append(Spacer(1, 14))
    
    # ══════════════════════════════════════════════════════
    # REPORT BODY STARTS HERE
    # ══════════════════════════════════════════════════════
    
    story.append(Paragraph(f"Generated: {date.today().strftime('%d %b %Y')}", caption_style))
    story.append(Spacer(1, 14))

    # --- CALCULATE METRICS FOR TILES ---
    eval_yr = get_dashboard_eval_year()
    alloc_list = smart_allocation()
    
    total_goals = len(alloc_list)
    fully_funded = sum(1 for g in alloc_list if g["pct"] >= 100)
    goals_met_str = f"{fully_funded} / {total_goals}" if total_goals > 0 else "0 / 0"
    
    ret_goal_name = st.session_state.get("ret_goal_name", "")
    retire_goal = next((g for g in alloc_list if g["name"] == ret_goal_name), None)
    if not retire_goal:
        retire_goal = next((g for g in alloc_list if "retire" in (g["name"] or "").lower() or "pension" in (g["name"] or "").lower()), None)
    ret_funded_str = f"{retire_goal['pct']}%" if retire_goal else "N/A"
    
    annual_inc = total_monthly_income() * 12
    annual_exp = total_monthly_expense() * 12
    annual_sur = monthly_surplus() * 12

    ten_yr_proj = fmt(max(portfolio_at_year(10) - liabilities_at_year(10), 0))
    wcagr_val   = f"{weighted_cagr():.1f}%"
    risk_prof   = risk_profile()
    
    tot_alloc = sum(g["allocated"] for g in alloc_list)
    tot_cost  = sum(g["display_cost"] for g in alloc_list)
    funding_ratio = (tot_alloc / tot_cost * 100) if tot_cost > 0 else 0
    
    surplus_today = calculate_surplus_today()
    wcagr = weighted_cagr() / 100
    total_gap_today = sum(
        max(g.get("display_cost", 0) - g.get("allocated", 0), 0) / ((1 + wcagr) ** max(g.get("start_year", 0), 0))
        for g in alloc_list
    )

    if total_goals == 0:
        status_text = "No Goals"
    elif fully_funded == total_goals:
        if surplus_today > 0:
            status_text = f"All Met! (+{fmt(surplus_today)})"
        else:
            status_text = "All Met!"
    elif funding_ratio >= 85:
        status_text = f"Nearly Met (-{fmt(total_gap_today)})"
    else:
        status_text = f"Not Met (-{fmt(total_gap_today)})"

    # --- PDF TILES RENDERER ---
    story.append(Paragraph("Dashboard", heading_style))
    story.append(Spacer(1, 6))

    def make_pdf_cell(title, val):
        return Paragraph(
            f"<para align='center'><font color='#64748b' size=9>{title}</font><br/><br/>"
            f"<font color='#1e293b' size=14><b>{val}</b></font></para>", 
            styles['Normal']
        )

    grid_data = [
        [make_pdf_cell("Total Assets", fmt(total_assets())), 
         make_pdf_cell("Total Liabilities", fmt(total_liabilities())), 
         make_pdf_cell("Total Net Worth", fmt(total_net_worth())), 
         make_pdf_cell("10-Year Projection", ten_yr_proj)],
        
        [make_pdf_cell(f"Annual Income (Yr {eval_yr})", fmt(annual_inc)), 
         make_pdf_cell(f"Annual Expenses (Yr {eval_yr})", fmt(annual_exp)), 
         make_pdf_cell(f"Annual Surplus (Yr {eval_yr})", fmt(annual_sur)), 
         make_pdf_cell("Weighted CAGR", wcagr_val)],
         
        [make_pdf_cell("Goals Fully Funded", goals_met_str), 
         make_pdf_cell("Retirement Corpus Funded", ret_funded_str), 
         make_pdf_cell("Risk Profile", risk_prof), 
         make_pdf_cell("Goal Status", status_text)]
    ]

    tile_table = Table(grid_data, colWidths=[6.5*cm]*4, rowHeights=[2.0*cm]*3)
    tile_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    
    story.append(tile_table)
    story.append(Spacer(1, 14))

    # --- REST OF THE REPORT ---
    if [a for a in get_effective_assets() if not a.get("is_virtual_surplus")]:
        chart_row = []
        nw_img = _fig_to_pdf_image(nw_bar_chart(), width_cm=12, height_cm=7.5, name="Net Worth Projection", errors=chart_errors)
        pie_img = _fig_to_pdf_image(allocation_pie_chart(), width_cm=12, height_cm=7.5, name="Asset Allocation (Dashboard)", errors=chart_errors)
        imgs = [im for im in [nw_img, pie_img] if im is not None]
        if imgs:
            story.append(Table([imgs], colWidths=[12.5*cm]*len(imgs)))
            story.append(Spacer(1, 8))

    if st.session_state.goals:
        story.append(Paragraph("Goal Coverage", sub_style))
        gc_headers = ["Goal", "Timeframe", "Completion", "Status"]
        gc_rows = []
        for g in smart_allocation():
            freq = goal_frequency(g)
            freq_str = f" · every {freq}yr" if freq > 0 else " · one-time"
            yr_str = f"Yr {g['start_year']}–{g['end_year']}{freq_str}" if freq > 0 else f"Yr {g['start_year']}"
            gc_rows.append([g["name"] or "(unnamed)", yr_str, _pdf_progress_bar(g["pct"]), g["status"]])
        gc_table = Table([gc_headers] + gc_rows, colWidths=[5*cm, 3.5*cm, 4.5*cm, 3.5*cm])
        gc_table.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,0), colors.HexColor('#1e293b')),
            ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID',         (0,0), (-1,-1), 0.4, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING',  (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ]))
        story.append(gc_table)
        story.append(Spacer(1, 10))

    if st.session_state.goals:
        story.append(Paragraph("Goal Summary", sub_style))
        alloc_list = smart_allocation()
        wcagr_pct  = weighted_cagr()
        wcagr      = wcagr_pct / 100

        headers = ["Goal","Start","End","Cumulative Cost","Target Cost","NPV","Alloc. (Today's Value)","% Met","Status"]
        rows = []
        tot_cum = tot_target = tot_npv = tot_alloc_today = 0.0
        
        for alloc in alloc_list:
            name  = alloc["name"] or "(unnamed)"
            pct   = alloc["pct"]
            cost  = alloc["display_cost"]
            at    = alloc["allocated_today"]
            npv   = goal_npv(alloc, wcagr_pct)
            
            start_cal = alloc["start_year"] if alloc["start_year"] > 1000 else rel_to_cal(goal_start_year(alloc))
            end_cal   = alloc["end_year"]   if alloc["end_year"] > 1000   else rel_to_cal(goal_end_year(alloc))
            freq      = goal_frequency(alloc)
            
            rows.append([
                name, str(start_cal), str(end_cal) if freq>0 or end_cal!=start_cal else "—",
                fmt_full(alloc["cumulative_cost"]), fmt_full(cost), fmt_full(npv), fmt_full(at),
                f"{pct}%", alloc.get("status","—"),
            ])
            tot_cum += alloc["cumulative_cost"]
            tot_target += cost
            tot_npv += npv
            tot_alloc_today += at
            
        rows.append(["TOTAL","","", fmt_full(tot_cum), fmt_full(tot_target), fmt_full(tot_npv), fmt_full(tot_alloc_today), "", ""])
        story.append(_pdf_table(headers, rows))
        story.append(Spacer(1, 10))

    recs = get_recommendations()
    if recs:
        story.append(Paragraph("Recommendations", sub_style))
        for icon, rtitle, text in recs:
            story.append(Paragraph(f"• <b>{rtitle}</b> — {text}", normal_style))
    story.append(PageBreak())

    story.append(Paragraph("Income &amp; Expenses", heading_style))
    if st.session_state.income or st.session_state.expenses:
        ie_img = _fig_to_pdf_image(expense_income_chart(), width_cm=25, height_cm=9, name="Income vs Expenses", errors=chart_errors)
        if ie_img:
            story.append(ie_img)
            story.append(Spacer(1, 8))
    if st.session_state.income:
        story.append(Paragraph("Monthly Income Sources", sub_style))
        headers = ["Source","Monthly","Growth %/yr","Start Year","End Year"]
        rows = [[i["name"] or "—", fmt_full(i["monthly"]), f'{i.get("growth",5.0)}%',
                 str(i.get("start_year", THIS_YEAR)), str(i.get("end_year", THIS_YEAR+30))]
                for i in st.session_state.income]
        tot_monthly = sum(i["monthly"] for i in st.session_state.income)
        rows.append(["TOTAL", fmt_full(tot_monthly), "", "", ""])
        story.append(_pdf_table(headers, rows))
        story.append(Spacer(1, 8))

    if st.session_state.expenses:
        story.append(Paragraph("Monthly Expenses", sub_style))
        headers = ["Name","Monthly","Inflation %","Start Year","End Year"]
        rows = [[e["name"] or "—", fmt_full(e["monthly"]), f'{e["inflation"]}%',
                 str(e.get("start_year", THIS_YEAR)), str(e.get("end_year", THIS_YEAR+30))]
                for e in st.session_state.expenses]
        tot_monthly = sum(e["monthly"] for e in st.session_state.expenses)
        rows.append(["TOTAL", fmt_full(tot_monthly), "", "", ""])
        story.append(_pdf_table(headers, rows))
    story.append(PageBreak())

    story.append(Paragraph("Financial Goals", heading_style))
    if st.session_state.goals:
        proj = goal_projections()
        headers = ["Goal","Cost Today","Inflation %","Start","End","Frequency","Occurrences","First Payment","Total (Nominal)"]
        rows = []
        for g in proj:
            freq = goal_frequency(g)
            freq_str = f"Every {freq} yr(s)" if freq>0 else "One-time"
            start_cal = g["start_year"] if g["start_year"]>1000 else rel_to_cal(g["start_year"])
            end_cal   = g["end_year"]   if g["end_year"]>1000   else rel_to_cal(g["end_year"])
            rows.append([
                g["name"] or "—", fmt_full(g["current_cost"]), f'{g["inflation"]}%',
                str(start_cal), str(end_cal), freq_str, str(len(g["occurrences"])),
                fmt_full(g["inflated_cost"]), fmt_full(g["cumulative_cost"]),
            ])
        tot_cost_today = sum(g["current_cost"] for g in proj)
        tot_occurrences = sum(len(g["occurrences"]) for g in proj)
        tot_first_payment = sum(g["inflated_cost"] for g in proj)
        tot_total_cost = sum(g["cumulative_cost"] for g in proj)
        rows.append([
            "TOTAL", fmt_full(tot_cost_today), "", "", "", "", 
            str(tot_occurrences), fmt_full(tot_first_payment), fmt_full(tot_total_cost)
        ])
        story.append(_pdf_table(headers, rows))

        story.append(Spacer(1, 10))
        story.append(Paragraph("Class Mix Funding Each Goal", sub_style))
        granular_rows = compute_granular_asset_allocation()
        mix_img = _fig_to_pdf_image(class_mix_chart(granular_rows), width_cm=25, height_cm=10, name="Class Mix Chart", errors=chart_errors)
        if mix_img:
            story.append(mix_img)
            story.append(Spacer(1, 10))

        story.append(Paragraph("Corpus Composition by Goal", sub_style))
        cc_headers = ["Goal", "Asset Name", "Asset Type", "Asset Class", "Allocated (Today)", "% of Goal's Current Funding"]
        cc_rows = []
        for r in granular_rows:
            cc_rows.append([
                r.get("Goal", ""), 
                r.get("Asset Name", ""), 
                r.get("Asset Type", ""), 
                r.get("Asset Class", ""),
                r.get("How much of the Asset in Asset Name column is allocated", ""),
                r.get("% of the Goal's Current Funding", "")
            ])
        story.append(_pdf_table(cc_headers, cc_rows, font_size=7))
        
    story.append(PageBreak())

    story.append(Paragraph("Asset Portfolio", heading_style))
    story.append(Paragraph(
        f"<b>Total Assets:</b> {fmt_full(total_assets())} &nbsp;&nbsp; "
        f"<b>Weighted CAGR:</b> {weighted_cagr():.1f}%", normal_style))
    story.append(Spacer(1, 6))
    eff_assets = get_effective_assets()
    apply_tax_summary = st.session_state.get("apply_tax_drag", False)
    
    if eff_assets:
        if len(eff_assets) <= 20:
            asset_img = _fig_to_pdf_image(asset_chart(), width_cm=25, height_cm=9, name="Asset Growth Chart", errors=chart_errors)
            if asset_img:
                story.append(asset_img)
                story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(
                f"(Per-asset growth chart omitted — {len(eff_assets)} assets is too "
                f"many to render legibly. See the summary table below.)", caption_style))
            story.append(Spacer(1, 6))

        type_pie_img = _fig_to_pdf_image(asset_type_pie_chart(), width_cm=12, height_cm=8, name="Asset Allocation by Type", errors=chart_errors)
        class_pie_img = _fig_to_pdf_image(allocation_pie_chart(), width_cm=12, height_cm=8, name="Asset Allocation by Class", errors=chart_errors)
        pie_imgs = [im for im in [class_pie_img, type_pie_img] if im is not None]
        if pie_imgs:
            story.append(Table([pie_imgs], colWidths=[12.5*cm]*len(pie_imgs)))
            story.append(Spacer(1, 8))

        ai = avg_inflation()
        headers = ["Asset","Type","Class","Cur Val","Gross CAGR"]
        if apply_tax_summary:
            headers.extend(["Tax %", "Net CAGR"])
        headers.extend(["Goals","SWP","5 Yrs","10 Yrs","20 Yrs"])
        
        rows = []
        for a in eff_assets:
            tags = ", ".join(a.get("tagged_goals") or []) or "—"
            swp  = f'{fmt_full(a.get("swp_monthly",0) or 0)}/mo' if (a.get("swp_monthly") or 0) > 0 else "—"
            
            val = a.get("value",0) or 0
            
            row_data = [
                a["name"] or "—", 
                a.get("asset_type","") or "—", 
                a["asset_class"],
                fmt_full(val) if not a.get("is_virtual_surplus") else "—",
                f'{a.get("cagr", 0.0):.2f}%'
            ]
            if apply_tax_summary:
                row_data.extend([
                    f'{asset_tax_rate(a["asset_class"])*100:.1f}%',
                    f'{get_asset_eff_cagr(a):.2f}%'
                ])
            row_data.extend([
                tags, swp,
                fmt_full(asset_value_at_year(a,5,ai)),
                fmt_full(asset_value_at_year(a,10,ai)),
                fmt_full(asset_value_at_year(a,20,ai))
            ])
            rows.append(row_data)
            
        tot_row = [
            "TOTAL", "", "—", fmt_full(total_assets()), "—"
        ]
        if apply_tax_summary:
            tot_row.extend(["—", f"{weighted_cagr():.1f}%"])
        else:
            tot_row[-1] = f"{weighted_cagr():.1f}%"
            
        tot_row.extend([
            "", "",
            fmt_full(portfolio_at_year(5)),
            fmt_full(portfolio_at_year(10)),
            fmt_full(portfolio_at_year(20))
        ])
        rows.append(tot_row)
        story.append(_pdf_table(headers, rows, font_size=6.5))
    story.append(PageBreak())

    if st.session_state.liabilities:
        story.append(Paragraph("Liabilities & Loans", heading_style))
        story.append(Paragraph(f"<b>Total Outstanding Principal:</b> {fmt_full(total_liabilities())}", normal_style))
        story.append(Spacer(1, 6))
        
        headers = ["Loan Name", "Outstanding Principal", "Interest Rate %", "Remaining Months", "Calculated EMI"]
        rows = []
        for l in st.session_state.liabilities:
            emi = calculate_emi(l["principal"], l["rate"], l["months"])
            rows.append([
                l["name"] or "—", 
                fmt_full(l["principal"]), 
                f'{l["rate"]}%', 
                str(l["months"]), 
                fmt_full(emi)
            ])
        story.append(_pdf_table(headers, rows))
        story.append(PageBreak())

    story.append(Paragraph("Retirement Corpus Drawdown", heading_style))
    ret_corpus = float(st.session_state.get("ret_opening_corpus", 0) or 0)
    ret_goal_name   = st.session_state.get("ret_goal_name", "")
    ret_qw     = float(st.session_state.get("ret_q_withdrawal", 0) or 0)
    if ret_corpus > 0 and ret_qw > 0:
        ret_return    = st.session_state.get("ret_annual_return", 9.0)
        ret_tax_class = st.session_state.get("ret_tax_class", "Equity")
        ret_custom_tax= st.session_state.get("ret_custom_tax", 20.0)
        ret_winf      = st.session_state.get("ret_w_inflation", 7.0)
        eff_tax = (ret_custom_tax/100) if ret_custom_tax > 0 else None

        all_goals = st.session_state.get("goals", [])
        selected_goal = next((g for g in all_goals if (g.get("name") or "") == ret_goal_name), None)
        goal_year_rel = cal_to_rel(selected_goal.get("start_year", THIS_YEAR)) if selected_goal else 0
        start_cal_year = rel_to_cal(goal_year_rel)

        rows_sim, total_withdrawn = retirement_simulation(
            ret_corpus, ret_return, ret_tax_class, ret_qw, ret_winf, eff_tax, start_cal_year)
        total_quarters = len(rows_sim)
        total_years    = total_quarters / 4
        total_tax_paid = sum(r["Tax Amount"] for r in rows_sim)
        total_return   = sum(r["Gross Return"] for r in rows_sim)

        story.append(Paragraph(
            f"<b>Goal:</b> {ret_goal_name or '—'} &nbsp;&nbsp; "
            f"<b>Opening Corpus:</b> {fmt_full(ret_corpus)} &nbsp;&nbsp; "
            f"<b>Expected Return:</b> {ret_return:.1f}% &nbsp;&nbsp; "
            f"<b>Tax Class:</b> {ret_tax_class}", normal_style))
        story.append(Paragraph(
            f"<b>Quarterly Withdrawal:</b> {fmt_full(ret_qw)} (inflating {ret_winf:.1f}%/yr) &nbsp;&nbsp; "
            f"<b>Corpus Lasts:</b> {total_years:.1f} years ({total_quarters} quarters)", normal_style))
        story.append(Paragraph(
            f"<b>Total Withdrawn:</b> {fmt_full(total_withdrawn)} &nbsp;&nbsp; "
            f"<b>Total Tax Paid:</b> {fmt_full(total_tax_paid)} &nbsp;&nbsp; "
            f"<b>Total Returns Earned:</b> {fmt_full(total_return)}", normal_style))
        story.append(Spacer(1, 8))

        ret_img = _fig_to_pdf_image(retirement_drawdown_chart(rows_sim), width_cm=25, height_cm=9, name="Retirement Corpus Drawdown", errors=chart_errors)
        if ret_img:
            story.append(ret_img)
            story.append(Spacer(1, 8))

        annual = {}
        for r in rows_sim:
            yr = r["Quarter"].split(" ")[0]
            if yr not in annual:
                annual[yr] = {"Year": yr, "Opening": r["Opening Corpus"],
                              "Withdrawal": 0, "Tax": 0, "Return": 0, "Closing": 0}
            annual[yr]["Withdrawal"] += r["Withdrawal"]
            annual[yr]["Tax"]        += r["Tax Amount"]
            annual[yr]["Return"]     += r["Gross Return"]
            annual[yr]["Closing"]     = r["Closing Corpus"]
        headers = ["Year","Opening Corpus","Withdrawal","Tax Paid","Return Earned","Closing Corpus"]
        ann_rows = [[a["Year"], fmt_full(a["Opening"]), fmt_full(a["Withdrawal"]), fmt_full(a["Tax"]),
                     fmt_full(a["Return"]), fmt_full(a["Closing"])] for a in annual.values()]
                     
        tot_withdrawal = sum(a["Withdrawal"] for a in annual.values())
        tot_tax_amt = sum(a["Tax"] for a in annual.values())
        tot_gross_ret = sum(a["Return"] for a in annual.values())
        ann_rows.append([
            "TOTAL", "", fmt_full(round(tot_withdrawal)), fmt_full(round(tot_tax_amt)),
            fmt_full(round(tot_gross_ret)), ""
        ])
                     
        story.append(Paragraph("Annual Summary", sub_style))
        story.append(_pdf_table(headers, ann_rows))
    elif ret_corpus > 0:
        story.append(Paragraph(
            f"<b>Goal:</b> {ret_goal_name or '—'} &nbsp;&nbsp; <b>Opening Corpus:</b> {fmt_full(ret_corpus)}",
            normal_style))
        story.append(Paragraph(
            "Set a quarterly withdrawal amount in the Retirement tab to see the full drawdown simulation here.",
            caption_style))
    else:
        story.append(Paragraph("No retirement corpus configured yet — visit the Retirement tab to set it up.", normal_style))

    if chart_errors:
        story.append(PageBreak())
        story.append(Paragraph("Notes", heading_style))
        story.append(Paragraph(
            f"{len(chart_errors)} chart(s) could not be rendered in this PDF (tables above are unaffected):",
            normal_style))
        for name, err in chart_errors:
            story.append(Paragraph(f"• <b>{name}:</b> {err}", caption_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue(), chart_errors

def get_logo_b64():
    logo_path = os.path.join(os.path.dirname(__file__), "shiftgaze_logo.jpg")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_logo_b64()
logo_html = (
    f'<img src="data:image/jpeg;base64,{logo_b64}" '
    f'style="height:70px; object-fit:contain; border-radius:8px;"/>'
    if logo_b64 else ""
)

st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    padding: 16px 28px;
    border-radius: 12px;
    margin-bottom: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
">
    <div style="display: flex; align-items: center;">
        <div style="flex: 0 0 auto;">
            <div style="color:#ffffff; font-size:26px; font-weight:700; letter-spacing:-0.5px; white-space:nowrap;">
                📊 Net Worth &amp; Goal Planner
            </div>
            <div style="color:#94a3b8; font-size:13px; margin-top:3px; white-space:nowrap;">
                Project your finances · Track goals · Allocate assets
            </div>
        </div>
        <div style="flex: 1 1 auto; text-align:center; color:#94a3b8; font-size:26px; font-style:italic; padding:0 12px;">
            Developed by Sandeep Narang
        </div>
        <div style="flex: 0 0 auto; display:flex; align-items:center; gap:12px;">
            {logo_html}
        </div>
    </div>
    <div style="margin-top:14px; padding-top:12px; border-top:1px solid rgba(148,163,184,0.2); font-size:11px; line-height:1.6;">
        <span style="color:#f59e0b;">⚠️ Disclaimer:</span>
        <span style="color:#94a3b8;"> This calculator is for personal planning only and does not constitute financial advice.
        Projections are estimates — actual returns, inflation and tax may differ.
        Consult a qualified financial advisor before making investment decisions.</span>
        <br/>
        <span style="color:#34d399;">🔒 Privacy:</span>
        <span style="color:#94a3b8;"> Your financial data — income, expenses, goals, and assets — never leaves your
        browser session. It is never stored, transmitted, or retained anywhere; it's lost when you close
        the tab unless you download it using the Save button below. The one exception: if you submit
        feedback below, only your rating and comment text are sent — nothing from your financial data.</span>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="
    background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
    border-left: 4px solid #2563eb;
    border-radius: 8px;
    padding: 14px 20px;
    margin-bottom: 12px;
">
<details>
<summary style="color:#93c5fd; font-size:14px; font-weight:600; cursor:pointer; list-style:none;">
    ℹ️ How to use this planner &nbsp;·&nbsp;
    <span style="color:#64748b; font-weight:400; font-size:12px;">Click to expand</span>
</summary>
<div style="margin-top:12px; color:#cbd5e1; font-size:13px; line-height:1.7;">

<b style="color:#93c5fd;">Step 1 — Income &amp; Expenses</b><br/>
Enter monthly income sources (salary, rental, freelance) in the spreadsheet-style table — each with
its own growth rate and active start/end years. Do the same for expenses (rent, groceries, loan EMIs)
with an inflation rate per item. Add or delete rows directly in the table, or bulk-import via Excel. 
<br/><i style="color:#a5b4fc;">New: You can enable the <b>Auto-Sweep Surplus</b> toggle at the bottom of this tab to automatically capture your unspent income each year and sweep it into a virtual "Unallocated Cash" asset growing at a custom rate. This virtual asset will automatically be used to fund your future goals!</i>

<br/><br/><b style="color:#93c5fd;">Step 2 — Goals</b><br/>
Add financial goals with a cost in today's money, a start year, end year, and recurrence frequency.
One-time goals (a home purchase) use the same start and end year with frequency 0. Recurring goals
(school fees, retirement) set frequency to 1 for annual, 2 for every two years, etc. — the app
automatically inflates and totals every future payment, and always funds recurring goals against
their realistic multi-year cost, not just the first payment.

<br/><br/><b style="color:#93c5fd;">Step 3 — Assets</b><br/>
Add investments and savings in the table: name, an optional free-text <b>Asset Type</b> (e.g. Mutual
Fund, FD, Direct Equity) alongside the broader <b>Class</b> dropdown, current value, and expected
CAGR. For fixed instruments enter the invested amount, maturity amount, and dates. Set custom tax rates for each asset class and toggle <b>Apply Automatic Tax Drag</b> to dynamically convert your gross CAGRs into net, post-tax returns across the app. Tag an asset to one or more goals to earmark
it; untagged assets form a shared pool that fills any remaining gaps. Set up a systematic withdrawal
plan (SWP) on an asset if it's already being drawn down.

<br/><br/><b style="color:#93c5fd;">Step 4 — Liabilities</b><br/>
Enter your outstanding loans, interest rates, and remaining tenure. The app calculates your exact monthly EMI to display an amortization schedule, and properly deducts the principal burndown from your projected Net Worth over time. <i style="color:#a5b4fc;">Note: Continue logging your actual EMI payments in the Expenses tab to keep your monthly cashflow accurate.</i>

<br/><br/><b style="color:#93c5fd;">Step 5 — Retirement</b><br/>
Select your retirement goal — the corpus, return rate, and withdrawal amount are pre-filled from
whatever assets you've tagged to it. The tab runs a real quarter-by-quarter drawdown simulation:
each withdrawal is taxed only on its gain portion (using your custom tax rates), while the remaining balance keeps compounding.
It shows exactly how many years the corpus lasts, with a chart and a full year-by-year breakdown.

<br/><br/><b style="color:#93c5fd;">Dashboard</b><br/>
Everything rolls up here: net worth, monthly cash flow, a goal-by-goal funding summary (including
Net Present Value and how much of your current portfolio is allocated to each goal), a surplus or
shortfall banner, and personalized recommendations.

<br/><br/><b style="color:#93c5fd;">Tips</b><br/>
• Tag assets to goals for more accurate, ring-fenced allocation<br/>
• Use <b>💾 Save &amp; Load</b> below to download your data as a file and reload it next session —
  this includes your custom tax rates, Auto-Sweep settings, and Retirement tab settings too<br/>
• Use <b>📄 Export All Tabs to PDF</b> to generate a single shareable report with every chart and table<br/>
• Import Income, Expenses, Goals, Assets, and Liabilities in bulk via Excel — look for the import panel in each tab<br/>
• All figures use plain comma-grouped numbers with Million/Billion abbreviations for large amounts —
  enter and read values in whatever currency youre tracking
</div>
</details>
</div>
""", unsafe_allow_html=True)

tab_settings, tab_dash, tab_inc_exp, tab_goals, tab_assets, tab_liab, tab_retire = st.tabs([
    "1. ⚙️ Settings",
    "2. Dashboard", 
    "3. Income & Expenses", 
    "4. Goals", 
    "5. Assets", 
    "6. 💳 Liabilities", 
    "7. 🏖️ Retirement"
])

# ══════════════════════════════════════════════════════
# CALCULATOR SETTINGS TAB
# ══════════════════════════════════════════════════════
with tab_settings:
    st.markdown("# 1. ⚙️ Calculator Settings")
    
    if "_setting_success_msg" in st.session_state:
        st.success(st.session_state["_setting_success_msg"])
        del st.session_state["_setting_success_msg"]

    # i) Save & Load Your Data
    c_set_1, c_desc_1 = st.columns([1, 1])
    with c_set_1:
        st.markdown("#### i) Save & Load Your Data")
        st.markdown('<div style="color: #ef4444; font-weight: bold; margin-bottom: 10px;">⚠️ Reminder: Please download your data before you end the session!</div>', unsafe_allow_html=True)
        
        export_data = {
            "income":st.session_state.income, "expenses":st.session_state.expenses,
            "projection_years":st.session_state.projection_years,
            "goals":st.session_state.goals, "assets":st.session_state.assets,
            "liabilities": st.session_state.liabilities,
            "ret_opening_corpus": st.session_state.get("ret_opening_corpus", 0),
            "ret_goal_name":      st.session_state.get("ret_goal_name", ""),
            "ret_annual_return":  st.session_state.get("ret_annual_return", 9.0),
            "ret_tax_class":      st.session_state.get("ret_tax_class", "Equity"),
            "ret_custom_tax":     st.session_state.get("ret_custom_tax", 20.0),
            "ret_q_withdrawal":   st.session_state.get("ret_q_withdrawal", 0),
            "ret_w_inflation":    st.session_state.get("ret_w_inflation", 7.0),
            "apply_tax_drag":     st.session_state.get("apply_tax_drag", False),
            "auto_sweep_surplus": st.session_state.get("auto_sweep_surplus", False),
            "sweep_cagr":         st.session_state.get("sweep_cagr", 8.0),
            "tax_rates":          {cls: st.session_state.get(f"tax_rate_{cls}", DEFAULT_TAX_RATES[cls]) for cls in ASSET_CLASSES}
        }
        if st.download_button("⬇️ Download JSON Save File", data=json.dumps(export_data, indent=2), file_name="financial_planner_data.json", mime="application/json", use_container_width=True, key="download_json_settings"):
            st.toast("✅ Save file downloaded successfully!")
        
        up = st.file_uploader("Load JSON Data", type=["json"], label_visibility="collapsed", key="upload_json_settings")
        if up:
            try:
                st.session_state["_pending_load"] = json.loads(up.read().decode())
                st.success("✓ File read — ready to apply")
            except Exception as e: st.error(str(e))
        if st.session_state.get("_pending_load"):
            if st.button("✅ Apply Loaded Data", use_container_width=True, type="primary", key="apply_json_settings"):
                d = st.session_state.pop("_pending_load")
                for k in ["income","expenses","goals","assets","liabilities","projection_years",
                          "ret_opening_corpus","ret_goal_name","ret_annual_return",
                          "ret_tax_class","ret_custom_tax","ret_q_withdrawal","ret_w_inflation", 
                          "apply_tax_drag", "auto_sweep_surplus", "sweep_cagr"]:
                    if k in d:
                        if k == "liabilities" and isinstance(d[k], (int, float)):
                            st.session_state[k] = []
                        else:
                            st.session_state[k] = d[k]
                if "tax_rates" in d:
                    for cls, rate in d["tax_rates"].items():
                        st.session_state[f"tax_rate_{cls}"] = rate
                clear_asset_cache()
                st.session_state.data_version += 1
                st.session_state["_setting_success_msg"] = "✅ Data successfully loaded!"
                st.rerun()
                
        if st.button("🔄 Reset to Empty", use_container_width=True, key="reset_json_settings"):
            for k in ["income","expenses","goals","assets","liabilities"]: st.session_state[k] = []
            st.session_state.projection_years = 30
            st.session_state.ret_opening_corpus = 0
            st.session_state.ret_goal_name      = ""
            st.session_state.ret_annual_return  = 9.0
            st.session_state.ret_tax_class      = "Equity"
            st.session_state.ret_custom_tax     = 20.0
            st.session_state.ret_q_withdrawal   = 0
            st.session_state.ret_w_inflation    = 7.0
            st.session_state.apply_tax_drag     = False
            st.session_state.auto_sweep_surplus = False
            st.session_state.sweep_cagr         = 8.0
            for cls in ASSET_CLASSES:
                st.session_state[f"tax_rate_{cls}"] = DEFAULT_TAX_RATES[cls]
            clear_asset_cache()
            st.session_state.data_version += 1
            st.session_state["_setting_success_msg"] = "✅ Data reset to empty!"
            st.rerun()
    with c_desc_1:
        st.markdown("#### Instructions")
        st.info("Because this planner runs entirely in your browser for privacy, your data is lost when you close the tab. Download your session as a JSON file to keep it safe.\n\nYou can later upload the JSON file here to resume your session. Use the Reset button to wipe all data and start fresh.")

    st.divider()

    # ii) Tax Configuration & Settings
    c_set_2, c_desc_2 = st.columns([1, 1])
    with c_set_2:
        st.markdown("#### ii) Tax Configuration & Settings")
        apply_tax = st.toggle("Apply Automatic Tax Drag", value=st.session_state.apply_tax_drag, key=f"v{_v}_tax_drag_toggle_settings")
        if apply_tax != st.session_state.apply_tax_drag:
            st.session_state.apply_tax_drag = apply_tax
            clear_asset_cache()
            st.rerun()

        st.markdown("##### Custom Tax Rates by Class (%)")
        tr_cols = st.columns(3)
        
        new_rates = {}
        for i, cls in enumerate(ASSET_CLASSES):
            with tr_cols[i % 3]:
                current_val = float(st.session_state.get(f"tax_rate_{cls}", DEFAULT_TAX_RATES.get(cls, 0.0)))
                new_val = st.number_input(cls, value=current_val, min_value=0.0, max_value=99.0, step=0.5, key=f"v{_v}_tax_input_{cls}_settings")
                new_rates[cls] = new_val
                
        # Only rerun if a rate actually changed
        if any(st.session_state.get(f"tax_rate_{cls}") != new_rates[cls] for cls in ASSET_CLASSES):
            for cls in ASSET_CLASSES:
                st.session_state[f"tax_rate_{cls}"] = new_rates[cls]
            clear_asset_cache()
            st.rerun()
    with c_desc_2:
        st.markdown("#### Instructions")
        st.info("When enabled, the app automatically applies taxes to your Expected CAGRs, Maturity Amounts, and Retirement Drawdowns based on the asset class's standard LTCG tax rate. \n\nAdjust the tax rates for each asset class as needed. If turned off, all tax impact is exactly 0.")

    st.divider()

    # iii) Number Format
    c_set_3, c_desc_3 = st.columns([1, 1])
    with c_set_3:
        st.markdown("#### iii) Number Format")
        fmt_choice = st.radio(
            "Select Number Format",
            options=["Western (1,000,000)", "Indian (10,00,000)"],
            index=0 if st.session_state.number_format == "Western" else 1,
            horizontal=False,
            key=f"v{_v}_number_format_radio_settings",
        )
        st.session_state.number_format = "Western" if fmt_choice.startswith("Western") else "Indian"
    with c_desc_3:
        st.markdown("#### Instructions")
        st.info("Switches comma grouping and magnitude labels across every number in the app.\n\n**Western**: 1,000,000 · Million/Billion.\n\n**Indian**: 10,00,000 · Lakh/Crore.\n\n*Note: This is a display setting only; your entered values don't change.*")

    st.divider()

    # iv) Download All Tables to Excel
    c_set_4, c_desc_4 = st.columns([1, 1])
    with c_set_4:
        st.markdown("#### iv) Download All Tables to Excel")
        if st.button("📦 Prepare Tables Download", use_container_width=True, key="prep_excel_settings"):
            with st.spinner("Compiling tables..."):
                table_bytes, ext, mime = generate_all_tables_excel_bytes()
                st.session_state["_excel_ready"] = table_bytes
                st.session_state["_excel_ext"] = ext
                st.session_state["_excel_mime"] = mime
                st.success("✓ Data compiled — click below to download")

        if st.session_state.get("_excel_ready"):
            ext = st.session_state.get("_excel_ext", "xlsx")
            mime = st.session_state.get("_excel_mime", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if st.download_button(
                "⬇️ Download All Tables",
                data=st.session_state["_excel_ready"],
                file_name=f"financial_planner_tables_{THIS_YEAR}.{ext}",
                mime=mime,
                use_container_width=True,
                key="download_excel_settings"
            ):
                st.toast(f"✅ {ext.upper()} file downloaded successfully!")
    with c_desc_4:
        st.markdown("#### Instructions")
        st.info("Download all your entered inputs (Income, Expenses, Goals, Assets, Liabilities) and the calculated summary tables into a single multi-sheet Excel file (or ZIP archive). This is useful for offline backup and detailed personal analysis.")


# ══════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════
with tab_dash:
    st.markdown("# 2. Dashboard")
    eval_yr = get_dashboard_eval_year()
    alloc_list = smart_allocation()
    
    total_goals = len(alloc_list)
    fully_funded = sum(1 for g in alloc_list if g["pct"] >= 100)
    goals_met_str = f"{fully_funded} / {total_goals}" if total_goals > 0 else "0 / 0"
    
    ret_goal_name = st.session_state.get("ret_goal_name", "")
    retire_goal = next((g for g in alloc_list if g["name"] == ret_goal_name), None)
    if not retire_goal:
        retire_goal = next((g for g in alloc_list if "retire" in (g["name"] or "").lower() or "pension" in (g["name"] or "").lower()), None)
    ret_funded_str = f"{retire_goal['pct']}%" if retire_goal else "N/A"
    
    annual_inc = total_monthly_income() * 12
    annual_exp = total_monthly_expense() * 12
    annual_sur = monthly_surplus() * 12

    # PREPARE CONSOLIDATED METRICS
    ten_yr_proj = fmt(max(portfolio_at_year(10) - liabilities_at_year(10), 0))
    wcagr_val   = f"{weighted_cagr():.1f}%"
    risk_prof   = risk_profile()
    
    tot_alloc = sum(g["allocated"] for g in alloc_list)
    tot_cost  = sum(g["display_cost"] for g in alloc_list)
    funding_ratio = (tot_alloc / tot_cost * 100) if tot_cost > 0 else 0
    
    # Calculate surplus upfront for the dashboard tile
    surplus_today = calculate_surplus_today()
    
    # Calculate Present Value (PV) of the gap using the weighted CAGR
    wcagr = weighted_cagr() / 100
    total_gap_today = sum(
        max(g.get("display_cost", 0) - g.get("allocated", 0), 0) / ((1 + wcagr) ** max(g.get("start_year", 0), 0))
        for g in alloc_list
    )
    
    if total_goals == 0:
        status_emoji, status_text = "⚪", "No Goals"
    elif fully_funded == total_goals:
        if surplus_today > 0:
            status_emoji, status_text = "😊", f"All Met! (+{fmt(surplus_today)})"
        else:
            status_emoji, status_text = "😊", "All Met!"
    elif funding_ratio >= 85:
        status_emoji, status_text = "😐", f"Nearly Met (-{fmt(total_gap_today)})"
    else:
        status_emoji, status_text = "😟", f"Not Met (-{fmt(total_gap_today)})"

    # HTML TILE GENERATOR (Single-line to prevent markdown parsing errors)
    def make_tile(title, value, subtitle=""):
        sub_html = f'<div style="color:#64748b; font-size:14px; margin-top:4px; text-align:center;">{subtitle}</div>' if subtitle else ""
        return f'<div style="background:#1e293b; border-radius:10px; padding:16px 20px; border:1px solid #334155; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center;"><div style="color:#94a3b8; font-size:16px; font-weight:600; margin-bottom:4px;">{title}</div><div style="color:#fff; font-size:30px; font-weight:700;">{value}</div>{sub_html}</div>'

    # STRICT 4-COLUMN GRID (12 Tiles = 3 Rows of 4)
    dash_html = '<div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:14px; margin-bottom:24px;">'
    dash_html += make_tile("Total Assets", fmt(total_assets()))
    dash_html += make_tile("Total Liabilities", fmt(total_liabilities()))
    dash_html += make_tile("Total Net Worth", fmt(total_net_worth()))
    dash_html += make_tile("10-Year Projection", ten_yr_proj)
    
    dash_html += make_tile(f"Annual Income (Yr {eval_yr})", fmt(annual_inc))
    dash_html += make_tile(f"Annual Expenses (Yr {eval_yr})", fmt(annual_exp))
    dash_html += make_tile(f"Annual Surplus (Yr {eval_yr})", fmt(annual_sur))
    dash_html += make_tile("Weighted CAGR", wcagr_val)
    
    dash_html += make_tile("Goals Fully Funded", goals_met_str)
    dash_html += make_tile("Retirement Corpus Funded", ret_funded_str)
    dash_html += make_tile("Risk Profile", risk_prof)
    dash_html += make_tile("Goal Status", status_emoji, status_text)
    dash_html += '</div>'
    
    st.markdown(dash_html, unsafe_allow_html=True)

    if not alloc_list:
        st.info("Add goals and assets to see allocation.")
    else:
        sort_choice = st.selectbox(
            "Arrange goals by",
            ["Target Date (Soonest First)", "Goal Amount (Highest First)",
             "% Completion (Highest First)", "Not Started First"],
            key=f"v{_v}_goal_sort",
        )
        if sort_choice == "Target Date (Soonest First)":
            alloc_sorted = sorted(alloc_list, key=lambda g: g["start_year"])
        elif sort_choice == "Goal Amount (Highest First)":
            alloc_sorted = sorted(alloc_list, key=lambda g: g["display_cost"], reverse=True)
        elif sort_choice == "% Completion (Highest First)":
            alloc_sorted = sorted(alloc_list, key=lambda g: g["pct"], reverse=True)
        else:
            alloc_sorted = sorted(alloc_list, key=lambda g: g["pct"])

        tiles_html = '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(270px, 1fr)); gap:14px; margin-top:10px;">'
        for g in alloc_sorted:
            pct = min(g["pct"], 100)
            bar_color = "#059669" if pct >= 100 else ("#d97706" if pct > 50 else "#dc2626")
            cost_label = "Cumulative cost" if goal_uses_cumulative(g) else "First occurrence cost"
            freq = goal_frequency(g)
            freq_str = f" · every {freq}yr" if freq > 0 else " · one-time"
            yr_str = f"Yr {g['start_year']}–{g['end_year']}{freq_str}" if freq > 0 else f"Yr {g['start_year']}"

            tile = (
                f'<div style="background:#1e293b; border-radius:10px; padding:14px 16px; border:1px solid #334155;">'
                f'<div style="font-weight:700; font-size:14px; color:#fff; margin-bottom:2px;">{g["name"]}</div>'
                f'<div style="font-size:11px; color:#94a3b8; margin-bottom:10px;">{yr_str}</div>'
                f'<div style="background:#334155; border-radius:6px; height:22px; position:relative; overflow:hidden;">'
                f'<div style="background:{bar_color}; height:100%; width:{pct}%; border-radius:6px; transition:width 0.4s;"></div>'
                f'<div style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; color:#fff; text-shadow:0 1px 2px rgba(0,0,0,0.5);">{g["pct"]}%</div>'
                f'</div>'
                f'<div style="font-size:11px; color:#94a3b8; margin-top:8px;">{cost_label}: {fmt(g["display_cost"])}</div>'
                f'<div style="font-size:11px; color:#94a3b8;">Allocated: {fmt(g["allocated"])}</div>'
                f'<div style="margin-top:8px;">'
                f'<span style="background:{bar_color}; color:#fff; padding:3px 10px; border-radius:10px; font-size:10px; font-weight:600;">{g["status"]}</span>'
                f'</div>'
                f'</div>'
            )
            tiles_html += tile
        tiles_html += '</div>'
        st.markdown(tiles_html, unsafe_allow_html=True)

        all_fully_funded = len(alloc_list) > 0 and all(g.get("pct", 0) >= 100 for g in alloc_list)
        total_cost_all   = sum(g.get("display_cost", 0) for g in alloc_list)
        
        if all_fully_funded and surplus_today > 0:
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#059669,#047857); '
                f'border-radius:10px; padding:18px 24px; margin-top:24px; '
                f'box-shadow:0 4px 12px rgba(5,150,105,0.3);">'
                f'<div style="color:#fff; font-size:20px; font-weight:700; margin-bottom:6px;">'
                f'🎉 All Goals Fully Funded!</div>'
                f'<div style="color:#d1fae5; font-size:14px; line-height:1.6;">'
                f'After meeting every goal, your portfolio has an estimated surplus worth '
                f'<strong style="color:#fff; font-size:17px;">{fmt(surplus_today)}</strong> '
                f'<b>in today\'s money</b> (as of {THIS_YEAR}).<br/>'
                f'<em style="color:#a7f3d0; font-size:12px;">Note: surplus accuracy depends on correct '
                f'CAGRs — see warnings above.</em>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        elif all_fully_funded and surplus_today <= 0:
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#0369a1,#0c4a6e); '
                f'border-radius:10px; padding:18px 24px; margin-top:24px;">'
                f'<div style="color:#fff; font-size:20px; font-weight:700; margin-bottom:6px;">'
                f'✅ All Goals Funded — Tight Fit</div>'
                f'<div style="color:#bae6fd; font-size:14px;">'
                f'All goals are met but with little headroom. '
                f'Consider building a buffer against market volatility.'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        elif len(alloc_list) > 0:
            wcagr = weighted_cagr() / 100
            total_gap_today = sum(
                max(g.get("display_cost", 0) - g.get("allocated", 0), 0) / ((1 + wcagr) ** max(g.get("start_year", 0), 0))
                for g in alloc_list
            )
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#dc2626,#991b1b); '
                f'border-radius:10px; padding:18px 24px; margin-top:24px;">'
                f'<div style="color:#fff; font-size:20px; font-weight:700; margin-bottom:6px;">'
                f'⚠️ Portfolio Shortfall</div>'
                f'<div style="color:#fee2e2; font-size:14px;">'
                f'Total funding gap across all goals: '
                f'<strong style="color:#fff; font-size:17px;">{fmt(total_gap_today)}</strong> '
                f'<b>in today\'s money</b>.<br/>'
                f'See the Current Add\'l Contribution Required column in the Goal Summary below for per-goal top-up amounts.'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    
    eff_assets = get_effective_assets()
    if eff_assets or st.session_state.liabilities:
        cl, cr = st.columns(2)
        with cl:
            st.plotly_chart(nw_bar_chart(), width="stretch")
        with cr:
            pie = allocation_pie_chart()
            if pie: st.plotly_chart(pie, width="stretch")

    recs = get_recommendations()
    if recs:
        st.markdown("### Recommendations")
        for icon,title,text in recs:
            st.markdown(f"**{icon} {title}** — {text}")

    if st.session_state.goals:
        st.markdown("### Goal Summary")
        st.caption(
            "For recurring goals, **Cumulative Cost** is the raw nominal sum of every future "
            "payment. **Target Cost (Used)** — what funding is actually checked against — is "
            "smaller: it's the lump sum needed at the goal's own start year, assuming that sum "
            "keeps growing at your portfolio's CAGR while being drawn down (the same principle "
            "the Retirement tab's drawdown simulation uses)."
        )
        
        ai               = avg_inflation()
        ta               = total_assets()
        eq_pct           = sum(a["value"] for a in eff_assets if a["asset_class"]=="Equity") / ta * 100 if ta > 0 else 0
        wcagr_pct        = weighted_cagr()
        wcagr            = wcagr_pct / 100

        summary_rows = []
        tot_cumulative = tot_target = tot_npv = tot_allocated_today = tot_contrib = 0.0
        tot_allocated = 0.0
        fully_funded_count = 0

        for alloc in alloc_list:
            name  = alloc["name"] or "(unnamed)"
            pct   = alloc["pct"]
            cost  = alloc["display_cost"]
            allocated       = alloc["allocated"]
            allocated_today = alloc["allocated_today"]
            npv_of_cost     = goal_npv(alloc, wcagr_pct)
            gap             = max(cost - allocated, 0)

            years_left = max(goal_start_year(alloc), 1)
            if wcagr > 0 and years_left > 0:
                annual_contrib = gap * wcagr / ((1 + wcagr) ** years_left - 1) if ((1 + wcagr) ** years_left - 1) > 0 else gap / years_left
            else:
                annual_contrib = gap / years_left if years_left > 0 else gap

            if pct >= 100:
                rec = "✅ On track — maintain current allocation"
                fully_funded_count += 1
            else:
                tips = []
                if eq_pct < 50 and years_left > 7:
                    tips.append("increase equity allocation for higher long-term growth")
                if gap > 0 and annual_contrib > 0:
                    tips.append(f"invest {fmt_full(annual_contrib)} more per year")
                if not alloc.get("tagged_assets"):
                    tips.append("tag assets to this goal for better tracking")
                if ai > weighted_cagr():
                    tips.append("inflation exceeds portfolio returns — consider higher-growth assets")
                rec = "; ".join(tips).capitalize() if tips else "Review asset allocation"

            start_cal = alloc["start_year"] if alloc["start_year"] > 1000 else rel_to_cal(goal_start_year(alloc))
            end_cal   = alloc["end_year"]   if alloc["end_year"]   > 1000 else rel_to_cal(goal_end_year(alloc))
            freq      = goal_frequency(alloc)

            summary_rows.append({
                "Goal":                              name,
                "Start":                             str(start_cal),
                "End":                               str(end_cal) if freq > 0 or end_cal != start_cal else "—",
                "Cumulative Cost":                   fmt_full(alloc["cumulative_cost"]),
                "Target Cost (Used)":                fmt_full(cost),
                "Net Present Value":                 fmt_full(npv_of_cost),
                "Allocated from Current Corpus":     fmt_full(allocated_today),
                "% Met":                             f"{pct}%",
                "Status":                            alloc["status"],
                "Current Add'l Contribution Required": fmt_full(annual_contrib) if gap > 0 else "—",
                "Recommendation":                    rec,
            })

            tot_cumulative       += alloc["cumulative_cost"]
            tot_target           += cost
            tot_npv              += npv_of_cost
            tot_allocated_today  += allocated_today
            tot_allocated        += allocated
            tot_contrib          += annual_contrib if gap > 0 else 0

        overall_pct = round((tot_allocated / tot_target) * 100) if tot_target > 0 else 0
        summary_rows.append({
            "Goal":                              "TOTAL",
            "Start":                             "",
            "End":                               "",
            "Cumulative Cost":                   fmt_full(tot_cumulative),
            "Target Cost (Used)":                fmt_full(tot_target),
            "Net Present Value":                 fmt_full(tot_npv),
            "Allocated from Current Corpus":     fmt_full(tot_allocated_today),
            "% Met":                             f"{overall_pct}%",
            "Status":                            f"{fully_funded_count}/{len(alloc_list)} Fully Funded",
            "Current Add'l Contribution Required": fmt_full(tot_contrib) if tot_contrib > 0 else "—",
            "Recommendation":                    "—",
        })

        summary_df = pd.DataFrame(summary_rows)
        st.session_state['summary_df'] = summary_df
        display_styled_df(summary_df)

        st.download_button(
            label="📥 Download Goal Summary Table (CSV)", 
            data=summary_df.to_csv(index=False).encode('utf-8'), 
            file_name='goal_summary.csv', 
            mime='text/csv',
            key="download_goal_summary_dash"
        )

        zero_cagr_val = sum(a.get("value",0) for a in eff_assets if (a.get("cagr") or 0) == 0 and not a.get("is_virtual_surplus"))
        recurring_goals = [g for g in goal_projections() if goal_frequency(g) > 0]
        suspect_goals = [g for g in goal_projections() if goal_frequency(g) == 0 and goal_end_year(g) > goal_start_year(g)]
        
        if zero_cagr_val > 0 or recurring_goals or suspect_goals:
            with st.expander("⚠️ Data Quality Warnings — may affect surplus accuracy", expanded=True):
                if suspect_goals:
                    for g in suspect_goals:
                        gname = g.get("name","?") or "(unnamed)"
                        start_disp = g["start_year"] if g["start_year"] > 1000 else rel_to_cal(goal_start_year(g))
                        end_disp   = g["end_year"]   if g["end_year"]   > 1000 else rel_to_cal(goal_end_year(g))
                        st.error(
                            f"🚨 **\"{gname}\" spans {start_disp}–{end_disp} but Frequency is set to 0 "
                            f"(one-time).** It's currently being funded as a SINGLE payment in {start_disp} "
                            f"only — the years in between are being ignored entirely. If this is meant to "
                            f"recur (e.g. annual retirement expenses, yearly fees), set Frequency to 1 "
                            f"(or however many years between payments) in the Goals tab and click "
                            f"**Apply Goal Changes**. If it's genuinely a one-time cost, set End Year "
                            f"equal to Start Year to clear this warning."
                        )
                if zero_cagr_val > 0:
                    st.warning(
                        f"**{fmt(zero_cagr_val)} ({zero_cagr_val/max(total_assets(),1)*100:.0f}% of portfolio) "
                        f"has 0% CAGR.** These assets earn nothing in projections, dragging down your "
                        f"weighted CAGR to {weighted_cagr():.1f}%. Go to Assets tab and enter expected "
                        f"returns for: " +
                        ", ".join(a.get("name","?") for a in eff_assets
                                  if (a.get("cagr") or 0) == 0)[:200]
                    )
                if recurring_goals:
                    names = ", ".join(g.get("name","?") for g in recurring_goals)
                    st.info(
                        f"ℹ️ **Recurring goals are always funded against their full multi-year cost:** "
                        f"{names}. The app treats a recurring commitment (e.g. school fees every year) as needing "
                        f"the SUM of all its payments — not just the first one — before calling it funded."
                    )

    FEEDBACK_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwSEyeDApgHgM71xmef4tryXR9M-jP2Hi9njW8QB_mbBKnWnA4NSE_DJSvU7caAQOTX/exec"

    st.markdown("---")
    st.markdown("### 💬 Feedback")
    st.caption("Found this useful? Let us know, or tell us what's missing.")
    st.caption(
        "🔒 Only your rating and the comment text below are ever sent when you submit — "
        "nothing else on this page (your income, expenses, goals, or assets) is read or transmitted."
    )
    fb_cols = st.columns([1, 3])
    with fb_cols[0]:
        rating = st.feedback("thumbs", key=f"v{_v}_fb_thumbs")
    with fb_cols[1]:
        fb_text = st.text_input("Comments (optional)", key=f"v{_v}_fb_text",
            label_visibility="collapsed", placeholder="Any comments or feature requests?")
    if st.button("Submit Feedback", key=f"v{_v}_fb_submit"):
        feedback_payload = {
            "rating":  rating,
            "comment": fb_text,
            "ts":      datetime.now().isoformat(),
        }
        try:
            resp = requests.post(FEEDBACK_WEBHOOK_URL, json=feedback_payload,
                                  timeout=8, allow_redirects=False)
            hops = 0
            while resp.status_code in (301, 302, 303, 307, 308) and hops < 5:
                next_url = resp.headers.get("Location")
                if not next_url: break
                resp = requests.get(next_url, timeout=8, allow_redirects=False)
                hops += 1

            if resp.status_code == 200:
                st.success("Thanks for the feedback!")
            else:
                st.warning("Feedback saved locally, but the server didn't confirm receipt. Please try again.")
                with st.expander("Debug details", expanded=False):
                    st.code(f"Status: {resp.status_code}\nResponse: {resp.text[:500]}")
        except Exception as e:
            st.warning("Couldn't reach the feedback server right now — please try again in a moment.")
            with st.expander("Debug details", expanded=False):
                st.code(str(e))
        st.session_state.setdefault("_feedback_log", []).append(feedback_payload)

    # Export to PDF Moved to the Bottom of Dashboard 
    st.markdown("---")
    st.markdown("### 📄 Export All Tabs to PDF")
    st.caption("Generates a single PDF covering Dashboard, Income & Expenses, Goals, Assets, Liabilities, and Retirement.")
    st.markdown('<div style="color: #ef4444; font-weight: bold; margin-bottom: 10px;">⚠️ Reminder: Please download your PDF report before you end the session!</div>', unsafe_allow_html=True)
    if st.button("📄 Generate PDF Report", use_container_width=True, type="primary", key="gen_pdf_settings"):
        with st.spinner("Building PDF..."):
            try:
                pdf_bytes, chart_errors = generate_full_pdf_report()
                st.session_state["_pdf_ready"] = pdf_bytes
                st.session_state["_pdf_chart_errors"] = chart_errors
                if chart_errors:
                    st.warning(
                        f"✓ Report ready, but {len(chart_errors)} chart(s) could not be rendered "
                        f"(tables are unaffected — details below). Click below to download anyway."
                    )
                    with st.expander("Chart rendering errors", expanded=True):
                        for name, err in chart_errors:
                            st.caption(f"**{name}:** {err}")
                else:
                    st.success("✓ Report ready — click below to download")
            except Exception as e:
                st.error(f"Could not generate PDF: {e}")
    
    if st.session_state.get("_pdf_ready"):
        st.download_button(
            "⬇️ Download PDF Report",
            data=st.session_state["_pdf_ready"],
            file_name=f"financial_planner_report_{THIS_YEAR}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="download_pdf_settings"
        )

# ══════════════════════════════════════════════════════
# INCOME & EXPENSES
# ══════════════════════════════════════════════════════
with tab_inc_exp:
    st.markdown("# 3. Income & Expenses")
    if st.session_state.expenses or st.session_state.income:
        st.plotly_chart(expense_income_chart(), width="stretch")

    st.markdown("### 💰 Monthly Income Sources")
    st.caption(f"Total: {fmt_full(total_monthly_income())}/month")
    st.markdown('<div style="color: #ef4444; font-weight: 600; font-size: 13px; margin-bottom: 12px;">⚠️ Note: Please enter your income net of tax (your actual take-home pay).</div>', unsafe_allow_html=True)

    with st.expander("📥 Import Income from Excel", expanded=False):
        st.caption("Columns: Source | Monthly | Growth %/yr | Start Year | End Year")
        inc_file = st.file_uploader("Upload Income Excel", type=["xlsx","xls"], key=f"v{_v}_inc_upload")
        if inc_file:
            new_inc, err = import_income_from_excel(inc_file)
            if err:
                st.error(f"Error: {err}")
            else:
                st.success(f"✓ Found {len(new_inc)} income sources.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Replace all income", key=f"v{_v}_inc_replace"):
                        st.session_state.income = new_inc
                        clear_asset_cache()
                        st.rerun()
                with c2:
                    if st.button("Append to existing", key=f"v{_v}_inc_append"):
                        st.session_state.income.extend(new_inc)
                        clear_asset_cache()
                        st.rerun()

    inc_df = pd.DataFrame([{
        "Source":       inc.get("name", ""),
        "Monthly":      fmt_full(inc.get("monthly", 0) or 0),
        "Growth %/yr":  float(inc.get("growth", 5.0) or 5.0),
        "Start Year":   int(inc.get("start_year", THIS_YEAR) or THIS_YEAR),
        "End Year":     int(inc.get("end_year", THIS_YEAR + 30) or THIS_YEAR + 30),
    } for inc in st.session_state.income])

    if inc_df.empty:
        inc_df = pd.DataFrame(columns=["Source", "Monthly", "Growth %/yr", "Start Year", "End Year"])

    edited_inc = st.data_editor(
        inc_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"inc_editor_v{_v}_{st.session_state.number_format}",
        column_config={
            "Source":      st.column_config.TextColumn("Source", width="large"),
            "Monthly":     st.column_config.TextColumn("Monthly", help="e.g. 1,800,000"),
            "Growth %/yr": st.column_config.NumberColumn("Growth %/yr", format="%.1f", min_value=0.0, max_value=30.0, step=0.5),
            "Start Year":  st.column_config.NumberColumn("Start Year", format="%d", min_value=2000, max_value=2100, step=1),
            "End Year":    st.column_config.NumberColumn("End Year", format="%d", min_value=2000, max_value=2100, step=1),
        }
    )
    st.caption("Edits above are staged in the table — nothing recalculates until you click Apply.")
    apply_inc = st.button("✅ Apply Income Changes", key=f"v{_v}_apply_inc", type="primary", use_container_width=True)

    if apply_inc:
        new_inc_state = []
        for _, r in edited_inc.iterrows():
            raw_name = r.get("Source", "")
            name = "" if pd.isna(raw_name) else str(raw_name).strip()
            raw_monthly = r.get("Monthly", 0)
            monthly = 0 if pd.isna(raw_monthly) else int(parse_amount(str(raw_monthly)))
            if not name and monthly == 0: continue
            new_inc_state.append({
                "name":       name,
                "monthly":    monthly,
                "growth":     float(safe_cell(r, "Growth %/yr", 5.0)),
                "start_year": int(safe_cell(r, "Start Year", THIS_YEAR)),
                "end_year":   int(safe_cell(r, "End Year", THIS_YEAR + 30)),
            })
        st.session_state.income = new_inc_state
        st.toast(f"✓ Applied — {len(new_inc_state)} income source(s) updated")
        clear_asset_cache()
        st.rerun()

    st.divider()
    st.markdown("### 💸 Monthly Expenses")
    st.caption(f"Total: {fmt_full(total_monthly_expense())}/month · Avg inflation: {avg_inflation():.1f}%")

    with st.expander("📥 Import Expenses from Excel", expanded=False):
        st.caption("Columns: Name | Monthly | Inflation % | Start Year | End Year")
        exp_file = st.file_uploader("Upload Expenses Excel", type=["xlsx","xls"], key=f"v{_v}_exp_upload")
        if exp_file:
            new_exp, err = import_expenses_from_excel(exp_file)
            if err:
                st.error(f"Error: {err}")
            else:
                st.success(f"✓ Found {len(new_exp)} expenses.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Replace all expenses", key=f"v{_v}_exp_replace"):
                        st.session_state.expenses = new_exp
                        clear_asset_cache()
                        st.rerun()
                with c2:
                    if st.button("Append to existing", key=f"v{_v}_exp_append"):
                        st.session_state.expenses.extend(new_exp)
                        clear_asset_cache()
                        st.rerun()

    exp_df = pd.DataFrame([{
        "Name":         e.get("name", ""),
        "Monthly":      fmt_full(e.get("monthly", 0) or 0),
        "Inflation %":  float(e.get("inflation", 6.0) or 6.0),
        "Start Year":   int(e.get("start_year", THIS_YEAR) or THIS_YEAR),
        "End Year":     int(e.get("end_year", THIS_YEAR + 30) or THIS_YEAR + 30),
    } for e in st.session_state.expenses])

    if exp_df.empty:
        exp_df = pd.DataFrame(columns=["Name", "Monthly", "Inflation %", "Start Year", "End Year"])

    edited_exp = st.data_editor(
        exp_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"exp_editor_v{_v}_{st.session_state.number_format}",
        column_config={
            "Name":        st.column_config.TextColumn("Name", width="large"),
            "Monthly":     st.column_config.TextColumn("Monthly", help="e.g. 1,800,000"),
            "Inflation %": st.column_config.NumberColumn("Inflation %", format="%.1f", min_value=0.0, max_value=30.0, step=0.5),
            "Start Year":  st.column_config.NumberColumn("Start Year", format="%d", min_value=2000, max_value=2100, step=1),
            "End Year":    st.column_config.NumberColumn("End Year", format="%d", min_value=2000, max_value=2100, step=1),
        }
    )
    st.caption("Edits above are staged in the table — nothing recalculates until you click Apply.")
    apply_exp = st.button("✅ Apply Expense Changes", key=f"v{_v}_apply_exp", type="primary", use_container_width=True)

    if apply_exp:
        new_exp_state = []
        for _, r in edited_exp.iterrows():
            raw_name = r.get("Name", "")
            name = "" if pd.isna(raw_name) else str(raw_name).strip()
            raw_monthly = r.get("Monthly", 0)
            monthly = 0 if pd.isna(raw_monthly) else int(parse_amount(str(raw_monthly)))
            if not name and monthly == 0: continue
            new_exp_state.append({
                "name":       name,
                "monthly":    monthly,
                "inflation":  float(safe_cell(r, "Inflation %", 6.0)),
                "start_year": int(safe_cell(r, "Start Year", THIS_YEAR)),
                "end_year":   int(safe_cell(r, "End Year", THIS_YEAR + 30)),
            })
        st.session_state.expenses = new_exp_state
        st.toast(f"✓ Applied — {len(new_exp_state)} expense(s) updated")
        clear_asset_cache()
        st.rerun()

    st.divider()
    st.markdown("**Projection Horizon**")
    ph_cols = st.columns([1.5, 1.5, 3])
    with ph_cols[0]:
        ph_start_raw = int(st.session_state.get("proj_start_year", THIS_YEAR) or THIS_YEAR)
        if ph_start_raw <= 1000: ph_start_raw = THIS_YEAR
        ph_start_raw = max(2000, min(ph_start_raw, 2100))
        proj_start = st.number_input("From", value=ph_start_raw,
            min_value=2000, max_value=2100, step=1, key=f"v{_v}_proj_start")
    with ph_cols[1]:
        if st.session_state.expenses:
            ph_end_raw = max((int(e.get("end_year", THIS_YEAR)) for e in st.session_state.expenses), default=THIS_YEAR + 30)
        else:
            ph_end_raw = THIS_YEAR + 30
            
        proj_end = st.number_input("To", value=ph_end_raw,
            min_value=proj_start, max_value=2100, step=1, key=f"v{_v}_proj_end_auto")
    with ph_cols[2]:
        proj_span = max(proj_end - proj_start, 1)
        st.caption(f"Projecting {proj_span} years ({proj_start} – {proj_end})")
    st.session_state.proj_start_year = proj_start
    st.session_state.proj_end_year   = proj_end
    st.session_state.projection_years = proj_span

    if st.session_state.expenses:
        st.markdown("### Year-by-Year Expense Breakdown")
        table_data = []
        
        milestones = sorted(set(
            [proj_start] +
            [proj_start + y for y in [1,5,10,15,20,25,30] if proj_start + y <= proj_end] +
            [proj_end]
        ))
        
        for cal_y in milestones:
            y = cal_y - proj_start
            row = {"Year": str(cal_y)}; total = 0
            for i, e in enumerate(st.session_state.expenses):
                k = e["name"] or f"e{i}"
                e_start = int(e.get("start_year", THIS_YEAR) or THIS_YEAR)
                e_end   = int(e.get("end_year", 2100) or 2100)
                if cal_y < e_start or cal_y > e_end:
                    row[e["name"] or "—"] = "—"; continue
                
                v = compound(e["monthly"], e["inflation"], y)
                row[e["name"] or "—"] = fmt_full(round(v)); total += v
            row["Total Expenses"] = fmt_full(total)

            monthly_salary = 0
            for inc in st.session_state.income:
                i_start = int(inc.get("start_year", THIS_YEAR) or THIS_YEAR)
                i_end   = int(inc.get("end_year", 2100) or 2100)
                if cal_y < i_start or cal_y > i_end:
                    continue
                monthly_salary += compound(inc.get("monthly", 0) or 0, inc.get("growth", 5.0) or 5.0, y)

            monthly_diff = monthly_salary - total
            row["Monthly Salary"]            = fmt_full(round(monthly_salary))
            row["Monthly Surplus/Shortage"]   = fmt_full(round(monthly_diff))
            row["Annual Surplus/Shortage"]    = fmt_full(round(monthly_diff * 12))
            
            table_data.append(row)
            
        display_styled_df(pd.DataFrame(table_data))
        
        st.markdown("---")
        st.markdown("### 🔄 Auto-Sweep Surplus")
        st.caption("Automatically invest your Annual Surplus into a virtual 'Unallocated Cash' asset. This asset will be available to fund future goals.")
        sweep_cols = st.columns([1, 2, 2])
        with sweep_cols[0]:
            auto_sweep = st.toggle("Enable Auto-Sweep", value=st.session_state.get("auto_sweep_surplus", False), key=f"v{_v}_auto_sweep")
        with sweep_cols[1]:
            sweep_cagr = st.number_input("Sweep CAGR %", value=float(st.session_state.get("sweep_cagr", 8.0)), step=0.5, disabled=not auto_sweep, key=f"v{_v}_sweep_cagr")
        
        if auto_sweep != st.session_state.get("auto_sweep_surplus", False) or sweep_cagr != st.session_state.get("sweep_cagr", 8.0):
            st.session_state.auto_sweep_surplus = auto_sweep
            st.session_state.sweep_cagr = sweep_cagr
            clear_asset_cache()
            st.rerun()

        if auto_sweep:
            st.markdown("#### Projected Annual Surplus (Swept to Unallocated Cash)")
            surplus_rows = []
            proj_start = int(st.session_state.get("proj_start_year", THIS_YEAR))
            last_inc_yr = max((int(e.get("end_year", THIS_YEAR)) for e in st.session_state.income), default=proj_start)
            
            if st.session_state.income:
                for rel_y in range(last_inc_yr - proj_start + 1):
                    cal_y = proj_start + rel_y
                    
                    inc = 0.0
                    for e in st.session_state.income:
                        if int(e.get("start_year", THIS_YEAR)) <= cal_y <= int(e.get("end_year", 2100)):
                            inc += e["monthly"] * 12 * ((1 + e.get("growth", 5.0)/100.0) ** rel_y)
                            
                    exp = 0.0
                    for e in st.session_state.expenses:
                        if int(e.get("start_year", THIS_YEAR)) <= cal_y <= int(e.get("end_year", 2100)):
                            exp += e["monthly"] * 12 * ((1 + e["inflation"]/100.0) ** rel_y)
                    
                    annual_surplus = max(inc - exp, 0)
                    if annual_surplus > 0 or inc > 0:
                        surplus_rows.append({
                            "Year": str(cal_y),
                            "Projected Income": fmt_full(inc),
                            "Projected Expenses": fmt_full(exp),
                            "Annual Surplus Swept": fmt_full(annual_surplus)
                        })
                if surplus_rows:
                    display_styled_df(pd.DataFrame(surplus_rows))
                else:
                    st.caption("No positive surplus or active income found in the projection period.")
            else:
                st.caption("Add active income sources to view and sweep surplus.")

# ══════════════════════════════════════════════════════
# GOALS
# ══════════════════════════════════════════════════════
with tab_goals:
    st.markdown("# 4. Goals")
    st.markdown("### 🎯 Financial Goals")

    with st.expander("📥 Import Goals from Excel", expanded=False):
        st.caption(
            "Upload an .xlsx file with columns: Goal Name, Cost Today, Inflation %, "
            "Start Year, End Year, Frequency (yrs)"
        )
        goal_file = st.file_uploader("Upload Goals Excel", type=["xlsx","xls"], key=f"v{_v}_goal_upload")
        if goal_file:
            new_goals, err = import_goals_from_excel(goal_file)
            if err:
                st.error(f"Error reading file: {err}")
            else:
                st.success(f"✓ Found {len(new_goals)} goals. Choose action:")
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Replace all goals", key=f"v{_v}_goal_replace"):
                        st.session_state.goals = new_goals
                        clear_asset_cache()
                        st.rerun()
                with col_b:
                    if st.button("Append to existing", key=f"v{_v}_goal_append"):
                        st.session_state.goals.extend(new_goals)
                        clear_asset_cache()
                        st.rerun()

    goals_df = pd.DataFrame([{
        "Goal Name":       g.get("name", ""),
        "Cost Today":      fmt_full(g.get("current_cost", 0) or 0),
        "Inflation %":     float(g.get("inflation", 6.0) or 6.0),
        "Start Year":      int(g.get("start_year", THIS_YEAR + 5) or THIS_YEAR + 5),
        "End Year":        int(g.get("end_year", g.get("start_year", THIS_YEAR + 5)) or THIS_YEAR + 5),
        "Frequency (yrs)": int(g.get("frequency", 0) or 0),
    } for g in st.session_state.goals])

    if goals_df.empty:
        goals_df = pd.DataFrame(columns=["Goal Name", "Cost Today", "Inflation %", "Start Year", "End Year", "Frequency (yrs)"])

    edited_goals = st.data_editor(
        goals_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"goals_editor_v{_v}_{st.session_state.number_format}",
        column_config={
            "Goal Name":       st.column_config.TextColumn("Goal Name", width="large"),
            "Cost Today":      st.column_config.TextColumn("Cost Today", help="e.g. 1,800,000"),
            "Inflation %":     st.column_config.NumberColumn("Inflation %", format="%.1f", min_value=0.0, max_value=30.0, step=0.5),
            "Start Year":      st.column_config.NumberColumn("Start Year", format="%d", min_value=2000, max_value=2100, step=1),
            "End Year":        st.column_config.NumberColumn("End Year", format="%d", min_value=2000, max_value=2100, step=1),
            "Frequency (yrs)": st.column_config.NumberColumn("Frequency (yrs)", format="%d", min_value=0, max_value=50, step=1, help="0=one-time, 1=annual, 2=every 2 years"),
        }
    )
    st.caption("Edits above are staged in the table — nothing recalculates until you click Apply.")
    apply_goals = st.button("✅ Apply Goal Changes", key=f"v{_v}_apply_goals", type="primary", use_container_width=True)

    if apply_goals:
        new_goals_state = []
        for _, r in edited_goals.iterrows():
            raw_name = r.get("Goal Name", "")
            name = "" if pd.isna(raw_name) else str(raw_name).strip()
            raw_cost = r.get("Cost Today", 0)
            cost = 0 if pd.isna(raw_cost) else int(parse_amount(str(raw_cost)))
            if not name and cost == 0: continue
            sy = int(safe_cell(r, "Start Year", THIS_YEAR + 5))
            ey = int(safe_cell(r, "End Year", sy))
            if ey < sy: ey = sy
            new_goals_state.append({
                "name":         name,
                "current_cost": cost,
                "inflation":    float(safe_cell(r, "Inflation %", 6.0)),
                "start_year":   sy,
                "end_year":     ey,
                "frequency":    int(safe_cell(r, "Frequency (yrs)", 0)),
            })
        st.session_state.goals = new_goals_state
        st.toast(f"✓ Applied — {len(new_goals_state)} goal(s) updated")
        st.rerun()

    if st.session_state.goals:
        st.markdown("### Projected Goal Costs")

        suspect = [g for g in goal_projections()
                  if goal_frequency(g) == 0 and goal_end_year(g) > goal_start_year(g)]
        if suspect:
            names = ", ".join(g.get("name","?") or "(unnamed)" for g in suspect)
            st.error(
                f"🚨 **{names}** — Frequency is 0 (one-time) but End Year is after Start Year. "
                f"Only the FIRST year is being funded; the rest of the span is ignored. "
                f"Set Frequency ≥ 1 above if this should recur every year (or every N years)."
            )

        proj = goal_projections(); rows = []
        tot_cost_today = 0
        tot_occurrences = 0
        tot_first_payment = 0
        tot_total_cost = 0
        
        for g in proj:
            freq = goal_frequency(g)
            freq_str = f"Every {freq} yr(s)" if freq > 0 else "One-time"
            start_cal = g["start_year"] if g["start_year"] > 1000 else rel_to_cal(g["start_year"])
            end_cal   = g["end_year"]   if g["end_year"]   > 1000 else rel_to_cal(g["end_year"])
            row = {
                "Goal":           g["name"] or "(unnamed)",
                "Cost Today":     fmt_full(g["current_cost"]),
                "Inflation":      f'{g["inflation"]}%',
                "Start":          str(start_cal),
                "End":            str(end_cal),
                "Frequency":      freq_str,
                "Occurrences":    str(len(g["occurrences"])),
                "First Payment":  fmt_full(g["inflated_cost"]),
                "Total Cost":     fmt_full(g["cumulative_cost"]),
            }
            rows.append(row)
            tot_cost_today += g["current_cost"]
            tot_occurrences += len(g["occurrences"])
            tot_first_payment += g["inflated_cost"]
            tot_total_cost += g["cumulative_cost"]
            
        if rows:
            rows.append({
                "Goal":           "TOTAL",
                "Cost Today":     fmt_full(tot_cost_today),
                "Inflation":      "",
                "Start":          "",
                "End":            "",
                "Frequency":      "",
                "Occurrences":    str(tot_occurrences),
                "First Payment":  fmt_full(tot_first_payment),
                "Total Cost":     fmt_full(tot_total_cost),
            })
            
        display_styled_df(pd.DataFrame(rows))

    if get_effective_assets() and st.session_state.goals:
        st.markdown("### Class Mix Funding Each Goal")
        
        granular_rows = compute_granular_asset_allocation()
        fig_mix = class_mix_chart(granular_rows)
        if fig_mix:
            st.plotly_chart(fig_mix, width="stretch")

        st.markdown("### Corpus Composition by Goal (Pivot Table)")
        st.caption(
            "A cross-tabulated breakdown showing precisely which assets are funding each goal. "
            "Values are displayed in **today's money**. Untagged assets are drawn from a shared pool and consumed sequentially."
        )

        df_gran = pd.DataFrame(granular_rows)
        
        if not df_gran.empty and len(df_gran) > 1:
            # 1. Remove the pre-calculated TOTAL row so we don't double count
            df_filtered = df_gran[df_gran["Goal"] != "TOTAL"].copy()
            
            # 2. Convert formatted strings back to numeric for the pivot math
            df_filtered["Amount"] = df_filtered["How much of the Asset in Asset Name column is allocated"].apply(parse_amount)
            
            # 3. Create the pivot table (Rows: Goals, Columns: Assets, Values: Amount)
            pivot_df = pd.pivot_table(
                df_filtered, 
                values="Amount", 
                index="Goal", 
                columns="Asset Name", 
                aggfunc="sum", 
                fill_value=0,
                margins=True,       # Adds row and column totals
                margins_name="TOTAL"
            )
            
            # 4. Re-format the numeric values back into your selected display format
            for col in pivot_df.columns:
                pivot_df[col] = pivot_df[col].apply(fmt_full)
                
            # 5. Reset the index so 'Goal' renders as a standard column header in Streamlit
            pivot_df = pivot_df.reset_index()
            
            # Display the resulting pivot matrix
            display_styled_df(pivot_df)
        else:
            st.info("No allocation data available to display.")

# ══════════════════════════════════════════════════════
# ASSETS
# ══════════════════════════════════════════════════════
with tab_assets:
    st.markdown("# 5. Assets")
    eff_assets = get_effective_assets()
    if eff_assets and len(eff_assets) <= 15:
        st.plotly_chart(asset_chart(), width="stretch")

    if eff_assets:
        type_pie = asset_type_pie_chart()
        if type_pie:
            col_chart, col_cagr = st.columns([1, 1])
            with col_chart:
                st.plotly_chart(type_pie, width="stretch")
            with col_cagr:
                ta_now = total_assets()
                def calc_cls_cagr(target_cls):
                    subset = [a for a in eff_assets if a["asset_class"] == target_cls] if target_cls else eff_assets
                    sub_val = sum(a["value"] for a in subset)
                    if sub_val == 0: return 0.0
                    return sum((a["value"] / sub_val) * get_asset_eff_cagr(a) for a in subset)
                
                cagr_all     = calc_cls_cagr(None)
                cagr_equity  = calc_cls_cagr("Equity")
                cagr_debt    = calc_cls_cagr("Debt")
                cagr_prop    = calc_cls_cagr("Property")
                cagr_metals  = calc_cls_cagr("Precious Metals")
                cagr_other   = calc_cls_cagr("Other")
                
                st.markdown(f"""
                <div style="background:#1e293b; border-radius:10px; padding:18px 20px; border:1px solid #334155; margin-top:50px;">
                    <div style="font-weight:700; font-size:16px; color:#fff; margin-bottom:14px; border-bottom:1px solid #334155; padding-bottom:8px;">
                        Weighted CAGR Breakdown
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#94a3b8; font-size:14px;">All Assets (Overall)</span>
                        <span style="color:#38bdf8; font-weight:700; font-size:14px;">{cagr_all:.2f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#94a3b8; font-size:14px;">Equity Class Assets</span>
                        <span style="color:#fff; font-weight:600; font-size:14px;">{cagr_equity:.2f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#94a3b8; font-size:14px;">Debt Class Assets</span>
                        <span style="color:#fff; font-weight:600; font-size:14px;">{cagr_debt:.2f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#94a3b8; font-size:14px;">Property Class Assets</span>
                        <span style="color:#fff; font-weight:600; font-size:14px;">{cagr_prop:.2f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#94a3b8; font-size:14px;">Precious Metals Class Assets</span>
                        <span style="color:#fff; font-weight:600; font-size:14px;">{cagr_metals:.2f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                        <span style="color:#94a3b8; font-size:14px;">Other Class Assets</span>
                        <span style="color:#fff; font-weight:600; font-size:14px;">{cagr_other:.2f}%</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("### 📈 Asset Portfolio")
    st.caption(f"Total Assets: {fmt_full(total_assets())} · Weighted CAGR: {weighted_cagr():.1f}%")

    with st.expander("📥 Import Assets from Excel", expanded=False):
        st.caption(
            "Upload an .xlsx with columns: Asset Name, Asset Type, Class, Purchase Date, Invested Amount, "
            "Current Value, Maturity Amount, Maturity Date, CAGR %, Tag Goals, SWP Monthly, SWP Start Yr"
        )
        asset_file = st.file_uploader("Upload Assets Excel", type=["xlsx","xls"], key=f"v{_v}_asset_upload")
        if asset_file:
            new_assets, defaulted_cagr_list, err = import_assets_from_excel(asset_file)
            if err:
                st.error(f"Error reading file: {err}")
            else:
                st.success(f"✓ Found {len(new_assets)} assets. Choose action:")
                if defaulted_cagr_list:
                    names_str = ", ".join(f"{n} ({c}: {cg:.1f}%)" for n, c, cg in defaulted_cagr_list)
                    st.warning(
                        f"⚠️ {len(defaulted_cagr_list)} asset(s) had no CAGR in the file — a "
                        f"class-based default will be applied: {names_str}"
                    )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Replace all assets", key=f"v{_v}_asset_replace"):
                        st.session_state.assets = new_assets
                        st.session_state["_cagr_defaults_applied"] = defaulted_cagr_list
                        st.session_state.data_version += 1; st.rerun()
                with col_b:
                    if st.button("Append to existing", key=f"v{_v}_asset_append"):
                        st.session_state.assets.extend(new_assets)
                        st.session_state["_cagr_defaults_applied"] = defaulted_cagr_list
                        st.session_state.data_version += 1; st.rerun()

    gnames = goal_names()

    assets_data = []
    apply_tax = st.session_state.get("apply_tax_drag", False)
    for a in st.session_state.assets:
        row = {
            "Asset Name":       a.get("name", ""),
            "Asset Type":       a.get("asset_type", ""),
            "Class":            a.get("asset_class", "Equity") if a.get("asset_class") in ASSET_CLASSES else "Equity",
            "Purch Date":       safe_date(a.get("purchase_date")),
            "Invested":         fmt_full(a.get("invested", 0) or 0),
            "Cur Val":          fmt_full(a.get("value", 0) or 0),
            "Mat Amt":          fmt_full(a.get("maturity_amt", 0) or 0),
            "Mat Date":         safe_date(a.get("maturity_date")),
            "Gross CAGR %":     float(a.get("cagr", 0.0) or 0.0),
        }
        if apply_tax:
            tr = float(st.session_state.get(f"tax_rate_{row['Class']}", DEFAULT_TAX_RATES.get(row['Class'], 0.0)))
            row["Tax %"] = tr
            row["Net CAGR %"] = row["Gross CAGR %"] * (1 - tr/100.0)
            
        row["Tag Goal"] = a.get("tagged_goals")[0] if a.get("tagged_goals") else ""
        row["SWP /mo"]  = fmt_full(a.get("swp_monthly", 0) or 0)
        row["SWP Yr"]   = asset_swp_start_display(a)
        assets_data.append(row)

    cols_list = ["Asset Name", "Asset Type", "Class", "Purch Date", "Invested", "Cur Val", "Mat Amt", "Mat Date", "Gross CAGR %"]
    if apply_tax:
        cols_list.extend(["Tax %", "Net CAGR %"])
    cols_list.extend(["Tag Goal", "SWP /mo", "SWP Yr"])

    if not assets_data:
        assets_df = pd.DataFrame(columns=cols_list)
    else:
        assets_df = pd.DataFrame(assets_data)

    col_cfg = {
        "Asset Name":      st.column_config.TextColumn("Asset Name", width="small"),
        "Asset Type":      st.column_config.TextColumn("Asset Type", width="small", help="e.g. Mutual Fund, FD, PMS, Direct Equity, Sovereign Gold Bond"),
        "Class":           st.column_config.SelectboxColumn("Class", options=ASSET_CLASSES, required=True, width="small"),
        "Purch Date":      st.column_config.DateColumn("Purch Date", format="YYYY-MM-DD", help="Double click to open calendar", width="small"),
        "Invested":        st.column_config.TextColumn("Invested", help="e.g. 1,800,000", width="small"),
        "Cur Val":         st.column_config.TextColumn("Cur Val", help="e.g. 1,800,000", width="small"),
        "Mat Amt":         st.column_config.TextColumn("Mat Amt", help="e.g. 1,800,000", width="small"),
        "Mat Date":        st.column_config.DateColumn("Mat Date", format="YYYY-MM-DD", help="Double click to open calendar", width="small"),
        "Gross CAGR %":    st.column_config.NumberColumn("Gross CAGR %", format="%.2f", min_value=0.0, max_value=50.0, step=0.5, help="Auto-calculated if maturity info provided", width="small"),
    }
    if apply_tax:
        col_cfg["Tax %"]      = st.column_config.NumberColumn("Tax %", format="%.1f", disabled=True, width="small")
        col_cfg["Net CAGR %"] = st.column_config.NumberColumn("Net CAGR %", format="%.2f", disabled=True, width="small")
        
    col_cfg["Tag Goal"] = st.column_config.SelectboxColumn("Tag Goal", options=[""] + gnames, help="Select a single goal to tag this asset to", width="small")
    col_cfg["SWP /mo"]  = st.column_config.TextColumn("SWP /mo", help="e.g. 1,800,000", width="small")
    col_cfg["SWP Yr"]   = st.column_config.NumberColumn("SWP Yr", format="%d", min_value=2000, max_value=2100, help="Calendar year, e.g. 2030", width="small")

    edited_assets = st.data_editor(
        assets_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"assets_editor_v{_v}_{st.session_state.number_format}",
        height=min(400 + len(assets_df) * 8, 700),
        column_config=col_cfg,
        column_order=cols_list
    )
    
    st.caption("Edits above are staged in the table — nothing recalculates until you click Apply.")
    apply_assets_btn = st.button("✅ Apply Asset Changes", key=f"v{_v}_apply_assets", type="primary", use_container_width=True)

    if apply_assets_btn:
        new_assets_state = []
        defaulted_cagr_assets = []
        for _, r in edited_assets.iterrows():
            raw_name = r.get("Asset Name", "")
            name = "" if pd.isna(raw_name) else str(raw_name).strip()
            
            raw_val = r.get("Cur Val", 0)
            val = 0 if pd.isna(raw_val) else int(parse_amount(str(raw_val)))

            raw_inv = r.get("Invested", 0)
            inv = 0 if pd.isna(raw_inv) else int(parse_amount(str(raw_inv)))

            if val <= 0 and inv > 0:
                val = inv

            if not name and val == 0:
                continue

            raw_atype = r.get("Asset Type", "")
            atype = "" if pd.isna(raw_atype) else str(raw_atype).strip()

            raw_mat = r.get("Mat Amt", 0)
            mat = 0 if pd.isna(raw_mat) else int(parse_amount(str(raw_mat)))

            raw_pdate = r.get("Purch Date")
            pdate = raw_pdate.strftime("%Y-%m-%d") if pd.notna(raw_pdate) and hasattr(raw_pdate, 'strftime') else ""

            raw_mdate = r.get("Mat Date")
            mdate = raw_mdate.strftime("%Y-%m-%d") if pd.notna(raw_mdate) and hasattr(raw_mdate, 'strftime') else ""

            cls = r.get("Class", "Equity")
            if pd.isna(cls) or cls not in ASSET_CLASSES: cls = "Equity"

            raw_cagr = r.get("Gross CAGR %", None)
            cagr_is_blank = pd.isna(raw_cagr) or str(raw_cagr).strip() == ""
            manual_cagr = 0.0 if cagr_is_blank else float(raw_cagr)

            if mat > 0 and inv > 0 and mdate and cagr_is_blank:
                auto = round(calc_asset_cagr(inv, mat, pdate or str(TODAY), mdate), 2)
                if auto > 0:
                    cagr = auto
                else:
                    cagr = manual_cagr
            elif cagr_is_blank:
                cagr = DEFAULT_CAGR_BY_CLASS.get(cls, 8.0)
                defaulted_cagr_assets.append((name or "(unnamed)", cls, cagr))
            else:
                cagr = manual_cagr

            if mat <= 0 and cagr > 0 and mdate:
                principal = inv if inv > 0 else val
                mat = int(round(calc_asset_maturity(principal, cagr, pdate or str(TODAY), mdate)))

            raw_tag = r.get("Tag Goal", "")
            tag_str = "" if pd.isna(raw_tag) else str(raw_tag).strip()
            tags = [tag_str] if tag_str and tag_str in gnames else []

            raw_swp = r.get("SWP /mo", 0)
            swp = 0 if pd.isna(raw_swp) else int(parse_amount(str(raw_swp)))
            swpyr = int(safe_cell(r, "SWP Yr", THIS_YEAR))

            new_assets_state.append({
                "name":           name,
                "asset_type":     atype,
                "asset_class":    cls,
                "purchase_date":  pdate,
                "invested":       inv,
                "value":          val,
                "maturity_amt":   mat,
                "maturity_date":  mdate,
                "cagr":           cagr,
                "tagged_goals":   tags,
                "swp_monthly":    swp,
                "swp_start_year": swpyr,
            })

        st.session_state.assets = new_assets_state
        st.session_state["_cagr_defaults_applied"] = defaulted_cagr_assets
        st.toast(f"✓ Applied — {len(new_assets_state)} asset(s) updated")
        clear_asset_cache()
        st.rerun()

    if st.session_state.get("_cagr_defaults_applied"):
        defaulted = st.session_state.pop("_cagr_defaults_applied")
        names_str = ", ".join(f"{n} ({c}: {cg:.1f}%)" for n, c, cg in defaulted)
        st.warning(
            f"⚠️ **{len(defaulted)} asset(s) had no CAGR entered — a class-based default was "
            f"applied. Please review and adjust if needed:** {names_str}"
        )

    if eff_assets:
        with st.expander(f"📊 Asset Summary Table ({len(eff_assets)} assets) — click to expand", expanded=False):
            ai = avg_inflation(); rows=[]
            tot_inv = 0
            tot_mat = 0
            tot_tax = 0
            tot_net = 0
            
            for a in eff_assets:
                tags   = ", ".join(a.get("tagged_goals") or []) or "—"
                swp    = f'{fmt_full(a.get("swp_monthly",0) or 0)}/mo' if (a.get("swp_monthly") or 0) > 0 else "—"
                
                inv = a.get("invested",0) or 0
                val = a.get("value",0) or 0
                mat = a.get("maturity_amt",0) or 0
                
                cost_basis = inv if inv > 0 else val
                net_m, tax_m = asset_net_maturity(cost_basis, mat, a["asset_class"]) if mat > 0 else (0,0)
                
                tot_inv += inv
                tot_mat += mat
                tot_tax += tax_m if apply_tax else 0
                tot_net += net_m if apply_tax else mat
                
                row_data = {
                    "Asset":         a["name"] or "(unnamed)",
                    "Type":          a.get("asset_type","") or "—",
                    "Class":         a["asset_class"],
                    "Purch Date":    a.get("purchase_date","") or "—",
                    "Invested":      fmt_full(inv) if inv else "—",
                    "Cur Val":       fmt_full(val) if not a.get("is_virtual_surplus") else "—",
                    "Mat Amt":       fmt_full(mat) if mat else "—",
                    "Mat Date":      a.get("maturity_date","") or "—",
                    "Gross CAGR":    f'{a.get("cagr", 0.0):.2f}%',
                }
                if apply_tax:
                    row_data["Tax Rate %"] = f'{asset_tax_rate(a["asset_class"])*100:.1f}%'
                    row_data["Net CAGR"]   = f'{get_asset_eff_cagr(a):.2f}%'
                    
                row_data.update({
                    "Tax on Gains":  fmt_full(tax_m) if (tax_m > 0 and apply_tax) else "0",
                    "Net Maturity":  fmt_full(net_m) if apply_tax else (fmt_full(mat) if mat else "—"),
                    "Tagged Goals":  tags,
                    "SWP":           swp,
                    "5 Yrs":         fmt_full(asset_value_at_year(a, 5, ai)),
                    "10 Yrs":        fmt_full(asset_value_at_year(a,10, ai)),
                    "20 Yrs":        fmt_full(asset_value_at_year(a,20, ai)),
                })
                rows.append(row_data)
                
            tot_data = {
                "Asset":         "TOTAL",
                "Type":          "",
                "Class":         "",
                "Purch Date":    "",
                "Invested":      fmt_full(tot_inv) if tot_inv else "—",
                "Cur Val":       fmt_full(total_assets()),
                "Mat Amt":       fmt_full(tot_mat) if tot_mat else "—",
                "Mat Date":      "",
                "Gross CAGR":    "—",
            }
            if apply_tax:
                tot_data["Tax Rate %"] = "—"
                tot_data["Net CAGR"]   = f"{weighted_cagr():.1f}%"
            else:
                tot_data["Gross CAGR"] = f"{weighted_cagr():.1f}%"
                
            tot_data.update({
                "Tax on Gains":  fmt_full(tot_tax) if apply_tax else "0",
                "Net Maturity":  fmt_full(tot_net) if tot_net else "—",
                "Tagged Goals":  "",
                "SWP":           "",
                "5 Yrs":         fmt_full(portfolio_at_year(5)),
                "10 Yrs":        fmt_full(portfolio_at_year(10)),
                "20 Yrs":        fmt_full(portfolio_at_year(20)),
            })
            rows.append(tot_data)
            display_styled_df(pd.DataFrame(rows))

# ══════════════════════════════════════════════════════
# LIABILITIES TAB
# ══════════════════════════════════════════════════════
with tab_liab:
    st.markdown("# 6. 💳 Liabilities")
    st.markdown("### 💳 Liabilities & Loans")
    st.caption("Track your outstanding debt. This automatically reduces your projected Net Worth over time.")
    st.info("💡 **Cashflow Note:** Since you already log your loan EMIs in the **Expenses** tab, this section purely tracks your principal burndown to calculate an accurate Net Worth projection. It does not alter your monthly surplus.")

    with st.expander("📥 Import Liabilities from Excel", expanded=False):
        st.caption("Columns: Loan Name | Outstanding Principal | Interest Rate % | Remaining Months")
        liab_file = st.file_uploader("Upload Liabilities Excel", type=["xlsx","xls"], key=f"v{_v}_liab_upload")
        if liab_file:
            new_liab, err = import_liabilities_from_excel(liab_file)
            if err:
                st.error(f"Error: {err}")
            else:
                st.success(f"✓ Found {len(new_liab)} liabilities.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Replace all liabilities", key=f"v{_v}_liab_replace"):
                        st.session_state.liabilities = new_liab
                        st.rerun()
                with c2:
                    if st.button("Append to existing", key=f"v{_v}_liab_append"):
                        st.session_state.liabilities.extend(new_liab)
                        st.rerun()

    liab_df = pd.DataFrame([{
        "Loan Name":             l.get("name", ""),
        "Outstanding Principal": fmt_full(l.get("principal", 0) or 0),
        "Interest Rate %":       float(l.get("rate", 8.0) or 8.0),
        "Remaining Months":      int(l.get("months", 12) or 12),
    } for l in st.session_state.liabilities])

    if liab_df.empty:
        liab_df = pd.DataFrame(columns=["Loan Name", "Outstanding Principal", "Interest Rate %", "Remaining Months"])

    edited_liab = st.data_editor(
        liab_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"liab_editor_v{_v}_{st.session_state.number_format}",
        column_config={
            "Loan Name":             st.column_config.TextColumn("Loan Name", width="large"),
            "Outstanding Principal": st.column_config.TextColumn("Outstanding Principal", help="e.g. 1,800,000"),
            "Interest Rate %":       st.column_config.NumberColumn("Interest Rate %", format="%.2f", min_value=0.0, max_value=50.0, step=0.5),
            "Remaining Months":      st.column_config.NumberColumn("Remaining Months", format="%d", min_value=1, max_value=600, step=1),
        }
    )
    st.caption("Edits above are staged in the table — nothing recalculates until you click Apply.")
    apply_liab = st.button("✅ Apply Liability Changes", key=f"v{_v}_apply_liab", type="primary", use_container_width=True)

    if apply_liab:
        new_liab_state = []
        for _, r in edited_liab.iterrows():
            raw_name = r.get("Loan Name", "")
            name = "" if pd.isna(raw_name) else str(raw_name).strip()
            
            raw_p = r.get("Outstanding Principal", 0)
            principal = 0 if pd.isna(raw_p) else int(parse_amount(str(raw_p)))
            
            if not name and principal == 0: continue
            
            rate = float(safe_cell(r, "Interest Rate %", 8.0))
            months = int(safe_cell(r, "Remaining Months", 12))
            
            new_liab_state.append({
                "name":      name,
                "principal": principal,
                "rate":      rate,
                "months":    months
            })
        st.session_state.liabilities = new_liab_state
        st.toast(f"✓ Applied — {len(new_liab_state)} liability/ies updated")
        st.rerun()

    if st.session_state.liabilities:
        st.markdown("---")
        st.markdown("### 📅 Amortization Schedules")
        
        for l in st.session_state.liabilities:
            principal = l.get('principal', 0)
            rate = l.get('rate', 0)
            months = l.get('months', 0)
            emi = calculate_emi(principal, rate, months)
            
            with st.expander(f"Amortization: **{l['name'] or 'Unnamed Loan'}** (Principal: {fmt_full(principal)} | Rate: {rate}%)", expanded=False):
                st.markdown(f"**Calculated Monthly EMI:** {fmt_full(emi)}")
                sched, _ = generate_annual_amortization(l)
                if sched:
                    display_styled_df(pd.DataFrame(sched))
                else:
                    st.caption("No schedule generated (check principal/months).")

# ══════════════════════════════════════════════════════
# RETIREMENT TAB
# ══════════════════════════════════════════════════════
with tab_retire:
    st.markdown("# 7. 🏖️ Retirement")
    st.markdown("### 🏖️ Retirement Corpus Drawdown Planner")
    st.caption("Model how long your retirement corpus lasts under quarterly SWP with tax-adjusted returns.")

    all_goals   = st.session_state.goals
    goal_options= [g["name"] or f"Goal {i+1}" for i,g in enumerate(all_goals)]
    retire_goals= [g for g in all_goals if "retire" in g.get("name","").lower() or "pension" in g.get("name","").lower()]

    if not goal_options:
        st.warning("⚠️ Please add at least one goal in the 'Goals' tab first to unlock the Retirement Planner.")
    else:
        col_cfg, col_info = st.columns([1,1])
        with col_cfg:
            st.markdown("#### Configuration")

            default_idx = 0
            saved_goal_name = st.session_state.get("ret_goal_name", "")
            if saved_goal_name and saved_goal_name in goal_options:
                default_idx = goal_options.index(saved_goal_name)
            elif retire_goals:
                names = [g["name"] for g in all_goals]
                default_idx = names.index(retire_goals[0]["name"]) if retire_goals[0]["name"] in names else 0

            selected_goal_name = st.selectbox("Select Goal", goal_options,
                index=default_idx, key=f"v{_v}_ret_goal")

            st.session_state.ret_goal_name = selected_goal_name

            eff_assets     = get_effective_assets()
            tagged_assets  = [a for a in eff_assets if selected_goal_name in (a.get("tagged_goals") or [])]
            selected_goal  = next((g for g in all_goals if (g["name"] or f"Goal {all_goals.index(g)+1}") == selected_goal_name), None)
            
            goal_year_rel  = cal_to_rel(selected_goal.get("start_year", THIS_YEAR)) if selected_goal else 0
            start_cal_year = rel_to_cal(goal_year_rel)
            ai             = avg_inflation()

            wcagr_pct = weighted_cagr()
            allocs = smart_allocation()
            selected_goal_alloc = next((g for g in allocs if g["name"] == selected_goal_name), None)
            
            if selected_goal_alloc:
                target_cost = selected_goal_alloc["display_cost"]
                npv_of_cost = goal_npv(selected_goal_alloc, wcagr_pct)
            else:
                target_cost = 0.0
                npv_of_cost = 0.0

            if tagged_assets:
                projected_corpus = sum(asset_value_at_year(a, goal_year_rel, ai) for a in tagged_assets)
                dominant_class   = max(set(a["asset_class"] for a in tagged_assets),
                    key=lambda c: sum(a["value"] for a in tagged_assets if a["asset_class"]==c))
                st.caption(f"🏷️ {len(tagged_assets)} asset(s) tagged · projected at Yr {rel_to_cal(goal_year_rel)}: **{fmt_full(projected_corpus)}** · class: **{dominant_class}**")
            else:
                dominant_class   = "Equity"
                st.caption("No assets tagged to this goal.")

            st.caption(f"🎯 The NPV for this goal is **{fmt_full(npv_of_cost)}** (Target Cost: {fmt_full(target_cost)})")

            saved_corpus = st.session_state.get("ret_opening_corpus", 0) or 0
            default_corpus = int(saved_corpus) if saved_corpus > 0 else int(npv_of_cost)
            opening_corpus = currency_input("Opening Corpus (at retirement)",
                default_corpus,
                key=f"v{_v}_ret_corpus")

            st.session_state.ret_opening_corpus = opening_corpus

            saved_return = st.session_state.get("ret_annual_return", 0.0) or 0.0
            default_return = round(saved_return, 1) if saved_return > 0 else round(wcagr_pct, 1)
            annual_return = st.number_input("Expected Annual Return %",
                value=default_return, min_value=0.0, max_value=30.0, step=0.5,
                key=f"v{_v}_ret_return")

            saved_cls = st.session_state.get("ret_tax_class", "")
            default_cls = saved_cls if saved_cls in ASSET_CLASSES else dominant_class
            asset_class_for_tax = st.selectbox("Asset Class (for LTCG tax rate)", ASSET_CLASSES,
                index=ASSET_CLASSES.index(default_cls) if default_cls in ASSET_CLASSES else 1,
                key=f"v{_v}_ret_cls")

            tax_rate_display = asset_tax_rate(asset_class_for_tax)
            if not st.session_state.get("apply_tax_drag"):
                st.caption("LTCG tax rate: **0.0%** (Automatic Tax Drag is currently turned **OFF** in Settings tab)")
            else:
                st.caption(f"LTCG tax rate: **{tax_rate_display*100:.1f}%** (based on settings) — on gain portion only")

            custom_tax = st.number_input("Override Tax Rate % (0 = use settings)",
                value=float(st.session_state.get("ret_custom_tax", 20.0)),
                min_value=0.0, max_value=50.0, step=0.5, key=f"v{_v}_ret_tax")
            effective_tax = (custom_tax/100) if custom_tax > 0 else None

            st.divider()
            st.markdown("**Quarterly Withdrawal**")
            monthly_exp = total_monthly_expense()
            suggested_qw = monthly_exp * 3 * (1 + ai/100) ** goal_year_rel

            saved_qw = st.session_state.get("ret_q_withdrawal", 0) or 0
            default_qw = int(saved_qw) if saved_qw > 0 else (int(suggested_qw) if suggested_qw > 0 else 0)
            q_withdrawal = currency_input(
                "Quarterly Withdrawal (inflates annually)",
                default_qw,
                key=f"v{_v}_ret_qwd")
            if monthly_exp > 0:
                st.caption(f"Suggested: {fmt_full(suggested_qw)} (3× monthly expenses inflated to Yr {rel_to_cal(goal_year_rel)})")

            saved_winf = st.session_state.get("ret_w_inflation", 0.0) or 0.0
            default_winf = round(saved_winf, 1) if saved_winf > 0 else 7.0
            withdrawal_inflation = st.number_input("Withdrawal Inflation Rate %/yr",
                value=default_winf, min_value=0.0, max_value=20.0, step=0.5, key=f"v{_v}_ret_winf")

            st.session_state.ret_annual_return = annual_return
            st.session_state.ret_tax_class     = asset_class_for_tax
            st.session_state.ret_custom_tax    = custom_tax
            st.session_state.ret_q_withdrawal  = q_withdrawal
            st.session_state.ret_w_inflation   = withdrawal_inflation

        with col_info:
            st.markdown("#### How This Works")
            st.markdown("""
**Each quarter:**
1. Withdrawal taken from corpus **at the start** (before returns)
2. Remaining corpus earns the quarterly return
3. Tax on **gain portion only**: `withdrawal × (1 − cost basis %)`
4. Tax deducted from corpus alongside withdrawal

**Formula:**
> Opening Corpus
> − Quarterly Withdrawal
> − Tax on Gain Portion
> + Return on Remainder
> = Closing Corpus

**Tax rates:** Configured via your custom settings in the Settings tab.

Withdrawal inflates every year at your chosen rate.
            """)

        st.divider()

        if opening_corpus <= 0:
            st.info("Enter an opening corpus above to see the projection.")
        elif q_withdrawal <= 0:
            st.info("Enter a quarterly withdrawal amount to run the simulation.")
        else:
            rows, total_withdrawn = retirement_simulation(
                opening_corpus, annual_return, asset_class_for_tax,
                q_withdrawal, withdrawal_inflation, effective_tax, start_cal_year)

            total_quarters = len(rows)
            total_years    = total_quarters / 4
            total_tax      = sum(r["Tax Amount"] for r in rows)
            total_return   = sum(r["Gross Return"] for r in rows)

            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Corpus Lasts",        f"{total_years:.1f} yrs ({total_quarters} qtrs)")
            m2.metric("Total Withdrawn",     fmt_full(total_withdrawn))
            m3.metric("Total Tax Paid",      fmt_full(total_tax))
            m4.metric("Total Returns Earned",fmt_full(total_return))

            fig = retirement_drawdown_chart(rows)
            st.plotly_chart(fig, width="stretch")

            st.markdown("### Quarterly Drawdown Table")
            view = st.radio("View", ["By Quarter","Annual Summary"], horizontal=True, key=f"v{_v}_ret_view")

            if view == "By Quarter":
                display_rows = [{
                    "Quarter":        r["Quarter"],
                    "Opening Corpus": fmt_full(round(r["Opening Corpus"])),
                    "Withdrawal":     fmt_full(round(r["Withdrawal"])),
                    "Return %":       r["Return %"],
                    "Gross Return":   fmt_full(round(r["Gross Return"])),
                    "Gain Portion":   fmt_full(round(r["Gain Portion"])),
                    "Tax Rate":       r["Tax Rate"],
                    "Tax Amount":     fmt_full(round(r["Tax Amount"])),
                    "Net Return":     fmt_full(round(r["Net Return"])),
                    "Net Gain (Q)":   fmt_full(round(r["Net Gain"])),
                    "Closing Corpus": fmt_full(round(r["Closing Corpus"])),
                } for r in rows]
                
                tot_q_with = sum(r["Withdrawal"] for r in rows)
                tot_q_gross = sum(r["Gross Return"] for r in rows)
                tot_q_gain = sum(r["Gain Portion"] for r in rows)
                tot_q_tax = sum(r["Tax Amount"] for r in rows)
                tot_q_net_ret = sum(r["Net Return"] for r in rows)
                tot_q_net_gain = sum(r["Net Gain"] for r in rows)
                
                display_rows.append({
                    "Quarter":        "TOTAL",
                    "Opening Corpus": "",
                    "Withdrawal":     fmt_full(round(tot_q_with)),
                    "Return %":       "",
                    "Gross Return":   fmt_full(round(tot_q_gross)),
                    "Gain Portion":   fmt_full(round(tot_q_gain)),
                    "Tax Rate":       "",
                    "Tax Amount":     fmt_full(round(tot_q_tax)),
                    "Net Return":     fmt_full(round(tot_q_net_ret)),
                    "Net Gain (Q)":   fmt_full(round(tot_q_net_gain)),
                    "Closing Corpus": "",
                })
                display_styled_df(pd.DataFrame(display_rows), height=450)
            else:
                annual = {}
                for r in rows:
                    yr = r["Quarter"].split(" ")[0]
                    if yr not in annual:
                        annual[yr] = {"Year": yr, "Opening Corpus":r["Opening Corpus"],
                            "Total Withdrawal":0,"Total Gross Return":0,"Total Gain Portion":0,
                            "Total Tax":0,"Total Net Return":0,"Net Gain":0,"Closing Corpus":0}
                    annual[yr]["Total Withdrawal"]  += r["Withdrawal"]
                    annual[yr]["Total Gross Return"] += r["Gross Return"]
                    annual[yr]["Total Gain Portion"] += r["Gain Portion"]
                    annual[yr]["Total Tax"]          += r["Tax Amount"]
                    annual[yr]["Total Net Return"]   += r["Net Return"]
                    annual[yr]["Net Gain"]           += r["Net Gain"]
                    annual[yr]["Closing Corpus"]      = r["Closing Corpus"]
                
                ann_rows = [{
                    "Year":             a["Year"],
                    "Opening Corpus":   fmt_full(round(a["Opening Corpus"])),
                    "Total Withdrawal": fmt_full(round(a["Total Withdrawal"])),
                    "Return %":         f"{annual_return:.1f}%",
                    "Gross Return":     fmt_full(round(a["Total Gross Return"])),
                    "Gain Portion":     fmt_full(round(a["Total Gain Portion"])),
                    "Tax Rate":         f"{(effective_tax or (asset_tax_rate(asset_class_for_tax) if st.session_state.get('apply_tax_drag') else 0.0))*100:.1f}%",
                    "Tax Paid":         fmt_full(round(a["Total Tax"])),
                    "Net Return":       fmt_full(round(a["Total Net Return"])),
                    "Net Gain":         fmt_full(round(a["Net Gain"])),
                    "Closing Corpus":   fmt_full(round(a["Closing Corpus"])),
                } for a, a in [(yr, data) for yr, data in annual.items()]]
                
                tot_a_with = sum(a["Total Withdrawal"] for a in annual.values())
                tot_a_gross = sum(a["Total Gross Return"] for a in annual.values())
                tot_a_gain = sum(a["Total Gain Portion"] for a in annual.values())
                tot_a_tax = sum(a["Total Tax"] for a in annual.values())
                tot_a_net_ret = sum(a["Total Net Return"] for a in annual.values())
                tot_a_net_gain = sum(a["Net Gain"] for a in annual.values())
                
                ann_rows.append({
                    "Year":             "TOTAL",
                    "Opening Corpus":   "",
                    "Total Withdrawal": fmt_full(round(tot_a_with)),
                    "Return %":         "",
                    "Gross Return":     fmt_full(round(tot_a_gross)),
                    "Gain Portion":     fmt_full(round(tot_a_gain)),
                    "Tax Rate":         "",
                    "Tax Paid":         fmt_full(round(tot_a_tax)),
                    "Net Return":       fmt_full(round(tot_a_net_ret)),
                    "Net Gain":         fmt_full(round(tot_a_net_gain)),
                    "Closing Corpus":   "",
                })
                
                display_styled_df(pd.DataFrame(ann_rows), height=450)

            st.caption(f"Corpus depleted after {total_years:.1f} years · Withdrawn: {fmt_full(total_withdrawn)} · Tax: {fmt_full(total_tax)}")
