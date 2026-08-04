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
    
    .stTabs button p, .stTabs button span {
        font-size: 28px !important;
        font-weight: 700 !important;
    }
    div[data-testid="stTabs"] button {
        font-size: 28px !important;
        font-weight: 700 !important;
    }
    
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
    ("ret_annual_return", 9.0), ("ret_tax_class", "Equity"),
    ("ret_custom_tax", 20.0), ("ret_q_withdrawal", 0), ("ret_w_inflation", 7.0),
    ("proj_start_year", THIS_YEAR), ("proj_end_year", THIS_YEAR + 30),
    ("number_format", "Western"), ("apply_tax_drag", False),
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

def total_assets():       return sum(a["value"] for a in get_effective_assets())
def total_liabilities():  return sum(float(l.get("principal", 0)) for l in st.session_state.liabilities)
def total_net_worth():    return total_assets() - total_liabilities()
def monthly_surplus():    return total_monthly_income() - total_monthly_expense()

def liabilities_at_year(y):
    return sum(liability_value_at_year(l, y) for l in st.session_state.liabilities)

def weighted_cagr():
    ta = total_assets()
    if ta == 0: return 0.0
    return sum((a["value"]/ta) * get_asset_eff_cagr(a) for a in get_effective_assets())

def portfolio_at_year(y):
    ai = avg_inflation()
    return sum(asset_value_at_year(a, y, ai) for a in get_effective_assets())

def risk_profile():
    ta = total_assets()
    if ta == 0: return "N/A"
    eff_assets = get_effective_assets()
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

# ── Smart allocation: strictly bounds funding to physical assets ──
def smart_allocation():
    ai        = avg_inflation()
    wcagr_pct = weighted_cagr()
    projs     = goal_projections()
    results   = []

    eff_assets = get_effective_assets()
    asset_consumed_fv = {i: 0.0 for i in range(len(eff_assets))}
    prev_yr = {i: 0 for i in range(len(eff_assets))}

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
                    
                    gap = yr - prev_yr[i]
                    cagr_pct = get_asset_eff_cagr(a)
                    if gap > 0 and cagr_pct > 0:
                        asset_consumed_fv[i] *= ((1 + cagr_pct/100)**gap)
                    prev_yr[i] = yr
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = max(val_at_yr - asset_consumed_fv[i], 0)
                    
                    if avail_val <= 0: continue
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        asset_consumed_fv[i] += draw
                        remaining_need -= draw
                        allocated_fv += draw
                        
                        draw_today = draw / ((1 + cagr_pct/100)**yr) if cagr_pct > 0 and yr > 0 else draw
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
    asset_consumed_fv = {i: 0.0 for i in range(len(eff_assets))}
    prev_yr = {i: 0 for i in range(len(eff_assets))}
    
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
                    gap = yr - prev_yr[i]
                    cagr_pct = get_asset_eff_cagr(a)
                    if gap > 0 and cagr_pct > 0:
                        asset_consumed_fv[i] *= ((1 + cagr_pct/100)**gap)
                    prev_yr[i] = yr
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = max(val_at_yr - asset_consumed_fv[i], 0)
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        asset_consumed_fv[i] += draw
                        remaining_need -= draw

        process_assets_for_surplus(is_tagged_pass=True)
        process_assets_for_surplus(is_tagged_pass=False)
        
    surplus_today = 0.0
    for i, a in enumerate(eff_assets):
        cagr_pct = get_asset_eff_cagr(a)
        yr = prev_yr[i]
        consumed_today = asset_consumed_fv[i] / ((1 + cagr_pct/100)**yr) if cagr_pct > 0 and yr > 0 else asset_consumed_fv[i]
        
        if not a.get("is_virtual_surplus"):
            val_today = a.get("value", 0)
            surplus_today += max(val_today - consumed_today, 0)
            
    return surplus_today

def compute_granular_asset_allocation():
    """Generates the asset-level granular allocation table in strict Current Value terms."""
    ai        = avg_inflation()
    wcagr_pct = weighted_cagr()
    projs     = goal_projections()
    
    eff_assets = get_effective_assets()
    asset_consumed_fv = {i: 0.0 for i in range(len(eff_assets))}
    prev_yr = {i: 0 for i in range(len(eff_assets))}
    
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
                    gap = yr - prev_yr[i]
                    cagr_pct = get_asset_eff_cagr(a)
                    if gap > 0 and cagr_pct > 0:
                        asset_consumed_fv[i] *= ((1 + cagr_pct/100)**gap)
                    prev_yr[i] = yr
                    
                    val_at_yr = asset_value_at_year(a, yr, ai)
                    avail_val = max(val_at_yr - asset_consumed_fv[i], 0)
                    
                    if avail_val <= 0: continue
                    
                    draw = min(remaining_need, avail_val)
                    if draw > 0:
                        asset_consumed_fv[i] += draw
                        remaining_need -= draw
                        
                        draw_today = draw / ((1 + cagr_pct/100)**yr) if cagr_pct > 0 and yr > 0 else draw
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
        cagr_pct = get_asset_eff_cagr(a)
        yr = prev_yr[i]
        consumed_today = asset_consumed_fv[i] / ((1 + cagr_pct/100)**yr) if cagr_pct > 0 and yr > 0 else asset_consumed_fv[i]
        
        if a.get("is_virtual_surplus"):
            continue # Virtual surplus has 0 value today, show in surplus metrics but omit from today's static asset table
            
        val_today = a.get("value", 0)
        surplus_today = max(val_today - consumed_today, 0)
        
        if surplus_today > 1.0:
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
    eff_assets = get_effective_assets()

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
        vals = [asset_value_at_year(a, y, ai) for y in years]
        for j,v in enumerate(vals): totals[j]+=v
        swp_amt = a.get("swp_monthly",0) or 0
        swp_yr  = asset_swp_start_display(a)
        name    = a["name"] or f"Asset {i+1}"
        label   = f"{name} (SWP {fmt_full(swp_amt)}/mo from {swp_yr})" if swp_amt else name
        fig.add_trace(go.Scatter(x=years, y=vals, name=label,
            line=dict(color=LINE_COLORS[i%len(LINE_COLORS)], width=2),
            hovertemplate="%{y:,.0f}<extra>%{fullData.name}</extra>"))
    if get_effective_assets():
        fig.add_trace(go.Scatter(x=years, y=totals, name="Total Portfolio",
            line=dict(color="#1e293b", width=3, dash="dash"),
            hovertemplate="%{y:,.0f}<extra>Total Portfolio</extra>"))
    fig.update_layout(title="Asset Growth Projection (net of SWP)", xaxis_title="Year", yaxis_title="Amount",
        hovermode="x unified", template=None, height=400,
        legend=dict(orientation="h", y=-0.2), margin=dict(l=60,r=20,t=50,b=80))
    return fig

def allocation_pie_chart():
    ct = {}
    for a in get_effective_assets(): ct[a["asset_class"]] = ct.get(a["asset_class"],0)+a["value"]
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
    title_style = ParagraphStyle('T', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#1e293b'))
    heading_style = ParagraphStyle('H', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor('#2563eb'), spaceBefore=10, spaceAfter=5)
    sub_style = ParagraphStyle('S', parent=styles['Heading3'], fontSize=10, textColor=colors.HexColor('#334155'), spaceBefore=6, spaceAfter=3)
    normal_style = ParagraphStyle('N', parent=styles['Normal'], fontSize=9, leading=13)
    caption_style = ParagraphStyle('C', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#64748b'))

    story = []
    chart_errors = []

    story.append(Paragraph("Net Worth &amp; Goal Planner — Full Report", title_style))
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
    
    if total_goals == 0:
        status_text = "No Goals"
    elif fully_funded == total_goals:
        status_text = "All Met!"
    elif funding_ratio >= 75 or fully_funded > 0:
        status_text = "Nearly Met"
    else:
        status_text = "Not Met"

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
    if get_effective_assets():
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
        headers = ["Asset","Type","Class","Current Value","CAGR","Tagged Goals","SWP","5 Yrs","10 Yrs","20 Yrs"]
        rows = []
        for a in eff_assets:
            tags = ", ".join(a.get("tagged_goals") or []) or "—"
            swp  = f'{fmt_full(a.get("swp_monthly",0) or 0)}/mo from {asset_swp_start_display(a)}' \
                   if (a.get("swp_monthly") or 0) > 0 else "—"
            
            inv = a.get("invested",0) or 0
            val = a.get("value",0) or 0
            mat = a.get("maturity_amt",0) or 0
            cost_basis = inv if inv > 0 else val
            net_m, tax_m = asset_net_maturity(cost_basis, mat, a["asset_class"]) if mat > 0 else (0,0)
            
            tax_disp = fmt_full(tax_m) if (tax_m > 0 and st.session_state.get("apply_tax_drag")) else "—"
            net_disp = fmt_full(net_m) if (net_m > 0 and st.session_state.get("apply_tax_drag")) else (fmt_full(mat) if mat else "—")
            
            rows.append([
                a["name"] or "—", a.get("asset_type","") or "—", a["asset_class"], fmt_full(a["value"]) if not a.get("is_virtual_surplus") else "—", f'{get_asset_eff_cagr(a):.2f}%',
                tags, swp,
                fmt_full(asset_value_at_year(a,5,ai)), fmt_full(asset_value_at_year(a,10,ai)), fmt_full(asset_value_at_year(a,20,ai)),
            ])
        rows.append(["TOTAL","", "—", fmt_full(total_assets()), f"{weighted_cagr():.1f}%", "", "",
                      fmt_full(portfolio_at_year(5)), fmt_full(portfolio_at_year(10)), fmt_full(portfolio_at_year(20))])
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
    ret_goal   = st.session_state.get("ret_goal_name", "")
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
