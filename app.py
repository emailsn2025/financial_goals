import streamlit as st
import plotly.graph_objects as go
import json
import pandas as pd
from datetime import date, datetime

st.set_page_config(page_title="Net Worth & Goal Planner", page_icon="📊", layout="wide")

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
LINE_COLORS   = ["#2563eb","#059669","#d97706","#7c3aed","#0d9488","#e11d48","#0891b2","#ca8a04","#6366f1","#14b8a6"]
TAX_RATES     = {"Equity":0.125, "Precious Metals":0.125, "Debt":0.30, "Property":0.30, "Other":0.30}
TODAY         = date.today()

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def indian_format(n):
    n = int(round(n)); neg = n < 0; n = abs(n); s = str(n)
    if len(s) <= 3: return ("-" if neg else "") + s
    last3 = s[-3:]; rest = s[:-3]; parts = []
    for i, c in enumerate(reversed(rest)):
        if i > 0 and i % 2 == 0: parts.append(",")
        parts.append(c)
    return ("-" if neg else "") + "".join(reversed(parts)) + "," + last3

def fmt(n):
    n = round(n)
    if abs(n) >= 1e7: return f"₹{n/1e7:.2f} Cr"
    if abs(n) >= 1e5: return f"₹{n/1e5:.2f} L"
    return f"₹{indian_format(n)}"

def fmt_full(n): return f"₹{indian_format(n)}"

def parse_indian(s):
    if not s or not str(s).strip(): return 0
    c = str(s).replace(",","").replace("₹","").replace(" ","").strip()
    try: return float(c) if "." in c else int(c)
    except: return 0

def compound(principal, rate_pct, years):
    return principal * (1 + rate_pct / 100) ** years

def currency_input(label, value, key, **kwargs):
    parsed_val = int(round(value)) if value else 0
    display    = indian_format(parsed_val) if parsed_val else ""
    raw = st.text_input(label, value=display, key=key, placeholder="e.g. 18,00,000", **kwargs)
    result = parse_indian(raw)
    if result >= 100000:
        st.caption(f"= {fmt(result)}")
    return result

def parse_date(s):
    """Parse a date string to a date object; return TODAY if blank/invalid."""
    if not s: return TODAY
    if isinstance(s, date): return s
    for fmt_str in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try: return datetime.strptime(str(s).strip(), fmt_str).date()
        except: pass
    return TODAY

def years_between(d1, d2):
    """Fractional years between two dates."""
    delta = (d2 - d1).days
    return max(delta / 365.25, 0)

def calc_asset_cagr(invested, maturity_amt, purchase_date_str, maturity_date_str):
    """Auto-calculate CAGR from invested → maturity over the period."""
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
    """Net maturity after LTCG tax on gains."""
    gain = max(maturity_amt - invested, 0)
    tax  = gain * asset_tax_rate(asset_class)
    return maturity_amt - tax, tax

# ══════════════════════════════════════════════════════
# ASSET VALUE WITH SWP
# ══════════════════════════════════════════════════════

def asset_value_at_year(a, target_year, avg_inf=6.0):
    val          = float(a["value"])
    swp          = float(a.get("swp_monthly", 0) or 0)
    swp_start    = int(a.get("swp_start_year", 0) or 0)
    monthly_rate = (1 + a["cagr"] / 100) ** (1/12) - 1
    for yr in range(target_year):
        if swp > 0 and yr >= swp_start:
            monthly_withdrawal = swp * (1 + avg_inf / 100) ** (yr - swp_start)
        else:
            monthly_withdrawal = 0
        for _ in range(12):
            val = val * (1 + monthly_rate) - monthly_withdrawal
            if val < 0: val = 0; break
    return max(val, 0)

# ══════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════

for key, default in [
    ("income", []), ("expenses", []), ("goals", []), ("assets", []),
    ("projection_years", 30), ("data_version", 0),
    ("ret_opening_corpus", 0), ("ret_goal_name", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

_v = st.session_state.data_version

# ══════════════════════════════════════════════════════
# COMPUTED VALUES
# ══════════════════════════════════════════════════════

def total_monthly_income():  return sum(e["monthly"] for e in st.session_state.income)
def total_monthly_expense(): return sum(e["monthly"] for e in st.session_state.expenses)

def avg_inflation():
    tm = total_monthly_expense()
    if tm == 0: return 6.0
    return sum((e["monthly"]/tm)*e["inflation"] for e in st.session_state.expenses)

def total_net_worth():  return sum(a["value"] for a in st.session_state.assets)
def monthly_surplus():  return total_monthly_income() - total_monthly_expense()

def weighted_cagr():
    tnw = total_net_worth()
    if tnw == 0: return 0.0
    return sum((a["value"]/tnw)*a["cagr"] for a in st.session_state.assets)

def portfolio_at_year(y):
    ai = avg_inflation()
    return sum(asset_value_at_year(a, y, ai) for a in st.session_state.assets)

def risk_profile():
    tnw = total_net_worth()
    if tnw == 0: return "N/A"
    eq   = sum(a["value"] for a in st.session_state.assets if a["asset_class"]=="Equity")/tnw*100
    debt = sum(a["value"] for a in st.session_state.assets if a["asset_class"] in ["Debt","Other"])/tnw*100
    if eq   > 70: return "Aggressive"
    if debt > 60: return "Conservative"
    return "Balanced"

def goal_names():
    return [g["name"] or f"Goal {i+1}" for i, g in enumerate(st.session_state.goals)]

def goal_projections():
    sorted_goals = sorted(st.session_state.goals, key=lambda g: g["target_year"])
    out = []
    for g in sorted_goals:
        inflated   = compound(g["current_cost"], g["inflation"], g["target_year"])
        cumulative = sum(compound(g["current_cost"], g["inflation"], y) for y in range(g["target_year"]+1))
        out.append({**g, "inflated_cost": inflated, "cumulative_cost": cumulative})
    return out

# ── Smart allocation: tagged assets first + retirement corpus as virtual asset ──
def smart_allocation():
    ai    = avg_inflation()
    projs = goal_projections()
    results = []

    # Retirement corpus from retirement tab counts as a virtual tagged asset
    ret_corpus     = float(st.session_state.get("ret_opening_corpus", 0) or 0)
    ret_goal_name  = st.session_state.get("ret_goal_name", "")

    for g in projs:
        gname   = g["name"] or ""
        use_cum = g.get("cumulative", False)
        cost    = g["cumulative_cost"] if use_cum else g["inflated_cost"]
        yr      = g["target_year"]

        tagged   = [a for a in st.session_state.assets if gname and gname in (a.get("tagged_goals") or [])]
        untagged = [a for a in st.session_state.assets if not (a.get("tagged_goals") or [])]

        tagged_val   = sum(asset_value_at_year(a, yr, ai) for a in tagged)
        untagged_val = sum(asset_value_at_year(a, yr, ai) for a in untagged)

        # Add retirement corpus if this goal is the retirement goal
        if gname and gname == ret_goal_name and ret_corpus > 0:
            tagged_val += ret_corpus

        gap_after_tagged = max(cost - tagged_val, 0)
        filler           = min(untagged_val, gap_after_tagged)
        allocated        = min(tagged_val, cost) + filler
        pct              = min((allocated / cost) * 100, 100) if cost > 0 else 0

        tagged_names = [a["name"] or "?" for a in tagged]
        if gname == ret_goal_name and ret_corpus > 0:
            tagged_names.append(f"Retirement corpus ({fmt(ret_corpus)})")

        status = "Fully Funded" if pct >= 100 else ("Partially Funded" if pct > 0 else "Unfunded")
        results.append({
            **g,
            "display_cost":     cost,
            "allocated":        allocated,
            "tagged_contrib":   min(tagged_val, cost),
            "untagged_contrib": filler,
            "tagged_assets":    tagged_names,
            "pct":              round(pct),
            "status":           status,
        })
    return results

def expense_coverage_years():
    if not st.session_state.income or not st.session_state.expenses: return None
    for y in range(1, 51):
        inc = sum(compound(e["monthly"], e.get("growth",5.0), y) for e in st.session_state.income)
        exp = sum(compound(e["monthly"], e["inflation"], y) for e in st.session_state.expenses)
        if exp > inc: return y
    return None

def get_recommendations():
    recs  = []
    alloc = smart_allocation()
    ai    = avg_inflation()
    tnw   = total_net_worth()

    shortfalls = [a for a in alloc if a["pct"] < 100]
    if shortfalls:
        g   = shortfalls[0]
        gap = g["display_cost"] - g["allocated"]
        sip = gap / (g["target_year"]*12) if g["target_year"] > 0 else gap
        recs.append(("📊","Cover Shortfall",
            f'"{g["name"]}" is {g["pct"]}% funded. Save ~{fmt(sip)}/month to close the {fmt(gap)} gap.'))

    for a in st.session_state.assets:
        if a["cagr"] < ai and st.session_state.expenses:
            recs.append(("⚠️","Inflation Warning",
                f'"{a["name"]}" returns {a["cagr"]}% — below avg inflation {ai:.1f}%.'))

    if any(g["target_year"]<=3 for g in st.session_state.goals) and \
       any(a["asset_class"]=="Equity" for a in st.session_state.assets):
        recs.append(("🔄","Horizon Matching",
            "Goals within 3 years detected. Consider shifting equity into debt for capital protection."))

    if tnw > 0:
        ct = {}
        for a in st.session_state.assets: ct[a["asset_class"]] = ct.get(a["asset_class"],0)+a["value"]
        for cls, val in ct.items():
            if (val/tnw)*100 > 60:
                recs.append(("⚖️","Diversification Alert", f"{cls} is {round((val/tnw)*100)}% of portfolio."))

    tm = total_monthly_expense()
    if tm > 0:
        liq = sum(a["value"] for a in st.session_state.assets if a["asset_class"] in ["Debt","Other"])
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
    """
    Expected columns (case-insensitive):
    Goal Name | Today's Cost | Inflation % | Target Year | Cumulative
    """
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":        ["goal name","name","goal"],
            "current_cost":["today's cost","cost","amount","current cost"],
            "inflation":   ["inflation %","inflation","inflation rate"],
            "target_year": ["target year","year","years"],
            "cumulative":  ["cumulative","cum"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None

        new_goals = []
        for _, row in df.iterrows():
            g = {"name":"","current_cost":0,"inflation":6.0,"target_year":5,"cumulative":False}
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field == "current_cost": g[field] = parse_indian(str(val))
                    elif field in ("inflation",): g[field] = float(str(val).replace("%","").strip() or 6)
                    elif field == "target_year":
                        raw_yr = int(float(str(val).strip() or 5))
                        # If value looks like a calendar year (e.g. 2035), convert to years from now
                        if raw_yr > 100:
                            raw_yr = max(raw_yr - TODAY.year, 1)
                        g[field] = min(max(raw_yr, 1), 100)
                    elif field == "cumulative":  g[field] = str(val).strip().lower() in ("true","yes","1","y")
                    else: g[field] = str(val).strip()
            new_goals.append(g)
        return new_goals, None
    except Exception as e:
        return [], str(e)

def import_assets_from_excel(uploaded_file):
    """
    Expected columns (case-insensitive):
    Asset Name | Class | Purchase Date | Invested Amount | Current Value |
    Maturity Amount | Maturity Date | CAGR % | Tag Goals | SWP ₹/mo | SWP Start Yr
    """
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [c.strip().lower() for c in df.columns]
        col_map = {
            "name":           ["asset name","name","asset"],
            "asset_class":    ["class","asset class","type"],
            "purchase_date":  ["purchase date","buy date","date of purchase","start date"],
            "invested":       ["invested amount","invested","cost","purchase price","buy price"],
            "value":          ["current value","value","current","market value"],
            "maturity_amt":   ["maturity amount","maturity","maturity value","fv","future value"],
            "maturity_date":  ["maturity date","due date","end date"],
            "cagr":           ["cagr %","cagr","return %","expected return","return"],
            "tagged_goals":   ["tag goals","goals","tagged goals","goal"],
            "swp_monthly":    ["swp ₹/mo","swp","swp amount","monthly swp","swp monthly"],
            "swp_start_year": ["swp start yr","swp start year","swp year","swp from"],
        }
        def find_col(df, options):
            for o in options:
                if o in df.columns: return o
            return None

        new_assets = []
        for _, row in df.iterrows():
            a = {
                "name":"","asset_class":"Equity","purchase_date":"","invested":0,
                "value":0,"maturity_amt":0,"maturity_date":"","cagr":0.0,
                "tagged_goals":[],"swp_monthly":0,"swp_start_year":0,
            }
            for field, options in col_map.items():
                c = find_col(df, options)
                if c and pd.notna(row[c]):
                    val = row[c]
                    if field in ("invested","value","maturity_amt","swp_monthly"):
                        a[field] = parse_indian(str(val))
                    elif field == "cagr":
                        a[field] = float(str(val).replace("%","").strip() or 0)
                    elif field == "swp_start_year":
                        a[field] = int(float(str(val).strip() or 0))
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

            # Auto-calc CAGR if maturity info present and CAGR not specified
            if a["maturity_amt"] > 0 and a["cagr"] == 0.0 and a["invested"] > 0:
                a["cagr"] = round(calc_asset_cagr(
                    a["invested"], a["maturity_amt"],
                    a["purchase_date"], a["maturity_date"]), 2)

            new_assets.append(a)
        return new_assets, None
    except Exception as e:
        return [], str(e)

# ══════════════════════════════════════════════════════
# CHARTS
# ══════════════════════════════════════════════════════

def expense_income_chart():
    years = list(range(st.session_state.projection_years+1))
    fig   = go.Figure()
    exp_totals = [0.0]*len(years)
    for i, e in enumerate(st.session_state.expenses):
        monthly_vals = [compound(e["monthly"], e["inflation"], y) for y in years]
        if e.get("cumulative", False):
            vals=[]; running=0
            for v in monthly_vals: running+=v*12; vals.append(running)
        else:
            vals = monthly_vals
        for j,v in enumerate(vals): exp_totals[j]+=v
        fig.add_trace(go.Scatter(x=years, y=vals, name=e["name"] or f"Expense {i+1}",
            line=dict(color=LINE_COLORS[i%len(LINE_COLORS)], width=2),
            hovertemplate="₹%{y:,.0f}<extra>%{fullData.name}</extra>"))
    if st.session_state.expenses:
        fig.add_trace(go.Scatter(x=years, y=exp_totals, name="Total Expenses",
            line=dict(color="#dc2626", width=3, dash="dash"),
            hovertemplate="₹%{y:,.0f}<extra>Total Expenses</extra>"))
    if st.session_state.income:
        inc = [sum(compound(e["monthly"],e.get("growth",5.0),y) for e in st.session_state.income) for y in years]
        fig.add_trace(go.Scatter(x=years, y=inc, name="Total Income",
            line=dict(color="#059669", width=3, dash="dot"),
            hovertemplate="₹%{y:,.0f}<extra>Total Income</extra>"))
    fig.update_layout(title="Monthly Income vs Expenses", xaxis_title="Year", yaxis_title="₹",
        hovermode="x unified", template=None, height=400,
        legend=dict(orientation="h", y=-0.15), margin=dict(l=60,r=20,t=50,b=60))
    return fig

def asset_chart():
    ai    = avg_inflation()
    max_y = max(st.session_state.projection_years, max((g["target_year"] for g in st.session_state.goals), default=30))
    years = list(range(max_y+1))
    fig   = go.Figure(); totals=[0.0]*len(years)
    for i, a in enumerate(st.session_state.assets):
        vals = [asset_value_at_year(a, y, ai) for y in years]
        for j,v in enumerate(vals): totals[j]+=v
        swp_amt = a.get("swp_monthly",0) or 0
        swp_yr  = a.get("swp_start_year",0) or 0
        name    = a["name"] or f"Asset {i+1}"
        label   = f"{name} (SWP {fmt(swp_amt)}/mo Yr{swp_yr}+)" if swp_amt else name
        fig.add_trace(go.Scatter(x=years, y=vals, name=label,
            line=dict(color=LINE_COLORS[i%len(LINE_COLORS)], width=2),
            hovertemplate="₹%{y:,.0f}<extra>%{fullData.name}</extra>"))
    if st.session_state.assets:
        fig.add_trace(go.Scatter(x=years, y=totals, name="Total Portfolio",
            line=dict(color="#1e293b", width=3, dash="dash"),
            hovertemplate="₹%{y:,.0f}<extra>Total Portfolio</extra>"))
    fig.update_layout(title="Asset Growth Projection (net of SWP)", xaxis_title="Year", yaxis_title="₹",
        hovermode="x unified", template=None, height=400,
        legend=dict(orientation="h", y=-0.2), margin=dict(l=60,r=20,t=50,b=80))
    return fig

def allocation_pie_chart():
    ct = {}
    for a in st.session_state.assets: ct[a["asset_class"]] = ct.get(a["asset_class"],0)+a["value"]
    labels,values = list(ct.keys()), list(ct.values())
    if not values: return None
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.45,
        marker=dict(colors=LINE_COLORS[:len(labels)]),
        textinfo="label+percent", textposition="outside",
        hovertemplate="%{label}: ₹%{value:,.0f}<extra></extra>"))
    fig.update_layout(title="Asset Allocation", template=None, height=350,
        margin=dict(l=20,r=20,t=50,b=20), showlegend=False)
    return fig

def nw_bar_chart():
    max_y = max(30, max((g["target_year"] for g in st.session_state.goals), default=30))
    years = list(range(0, max_y+1, 5))
    vals  = [portfolio_at_year(y) for y in years]
    fig   = go.Figure(go.Bar(x=[f"Yr {y}" for y in years], y=vals,
        marker_color="#2563eb", hovertemplate="₹%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Net Worth Projection (net of SWP)", template=None, height=350,
        margin=dict(l=60,r=20,t=50,b=40), yaxis_title="₹")
    return fig

# ══════════════════════════════════════════════════════
# RETIREMENT SIMULATION
# ══════════════════════════════════════════════════════

def retirement_simulation(opening_corpus, annual_return_pct, asset_class,
                           quarterly_withdrawal, withdrawal_inflation_pct,
                           tax_rate_override=None):
    tax_rate      = tax_rate_override if tax_rate_override is not None else TAX_RATES.get(asset_class, 0.30)
    quarterly_ret = (1 + annual_return_pct / 100) ** 0.25 - 1
    corpus        = float(opening_corpus)
    total_invested= float(opening_corpus)
    total_withdrawn = 0.0
    rows = []; quarter = 0

    while corpus > 0:
        quarter += 1
        year    = (quarter-1)//4+1
        q_label = f"Y{year} Q{(quarter-1)%4+1}"
        inflation_factor = (1 + withdrawal_inflation_pct/100) ** ((quarter-1)//4)
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
# LAYOUT
# ══════════════════════════════════════════════════════

st.markdown("## 📊 Net Worth & Goal Planner")

with st.expander("💾 Save & Load Your Data", expanded=False):
    st.caption("Your data resets when you close this tab. Download to keep it safe.")
    sc, lc, rc = st.columns(3)
    with sc:
        st.download_button("⬇️ Download My Data",
            data=json.dumps({"income":st.session_state.income,"expenses":st.session_state.expenses,
                "projection_years":st.session_state.projection_years,
                "goals":st.session_state.goals,"assets":st.session_state.assets}, indent=2),
            file_name="financial_planner_data.json", mime="application/json", use_container_width=True)
    with lc:
        up = st.file_uploader("Load", type=["json"], label_visibility="collapsed")
        if up:
            try:
                st.session_state["_pending_load"] = json.loads(up.read().decode())
                st.success("✓ File read — ready to apply")
            except Exception as e: st.error(str(e))
        if st.session_state.get("_pending_load"):
            if st.button("✅ Apply Loaded Data", use_container_width=True, type="primary"):
                d = st.session_state.pop("_pending_load")
                for k in ["income","expenses","goals","assets","projection_years"]:
                    if k in d: st.session_state[k] = d[k]
                st.session_state.data_version += 1; st.rerun()
    with rc:
        if st.button("🔄 Reset to Empty", use_container_width=True):
            for k in ["income","expenses","goals","assets"]: st.session_state[k] = []
            st.session_state.projection_years = 30
            st.session_state.data_version += 1; st.rerun()

st.caption("Project your finances · Track goals · Allocate assets")
tab_dash, tab_inc_exp, tab_goals, tab_assets, tab_retire = st.tabs(
    ["Dashboard","Income & Expenses","Goals","Assets","🏖️ Retirement"])

# ══════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════
with tab_dash:
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total Net Worth",  fmt(total_net_worth()))
    c2.metric("Monthly Income",   fmt(total_monthly_income()))
    c3.metric("Monthly Expenses", fmt(total_monthly_expense()))
    c4.metric("Monthly Surplus",  fmt(monthly_surplus()))

    if st.session_state.income or st.session_state.expenses:
        st.markdown("### Monthly Cash Flow")
        inc = total_monthly_income(); exp = total_monthly_expense()
        if exp > 0 and inc > 0:
            pct = round((inc/exp)*100)
            css = "badge-green" if pct>=100 else "badge-red"
            label = f"Expenses Covered ({pct}%) — surplus {fmt_full(inc-exp)}/mo" if pct>=100 \
                else f"Shortfall ({pct}% covered) — deficit {fmt_full(exp-inc)}/mo"
            st.markdown(f'<span class="{css}">{label}</span>', unsafe_allow_html=True)
            cross = expense_coverage_years()
            if cross: st.caption(f"⚠️ Expenses will overtake income ~Year {cross} at current growth rates.")
            st.progress(min(pct,100)/100)

    st.markdown("### Goal Coverage")
    alloc = smart_allocation()
    if not alloc:
        st.info("Add goals and assets to see allocation.")
    for g in alloc:
        col_info, col_bar = st.columns([1,2])
        with col_info:
            css = "badge-green" if g["pct"]>=100 else ("badge-amber" if g["pct"]>50 else "badge-red")
            cost_label = "Cumulative cost" if g.get("cumulative") else "Inflated target"
            st.markdown(f'**{g["name"]}** · Year {g["target_year"]}')
            st.markdown(f'{cost_label}: {fmt(g["display_cost"])} · Allocated: {fmt(g["allocated"])}')
            if g["tagged_assets"]:
                st.caption(f'🏷️ {", ".join(g["tagged_assets"])} → {fmt(g["tagged_contrib"])} + untagged: {fmt(g["untagged_contrib"])}')
            st.markdown(f'<span class="{css}">{g["status"]} ({g["pct"]}%)</span>', unsafe_allow_html=True)
        with col_bar:
            st.progress(min(g["pct"],100)/100)

    if st.session_state.assets:
        cl, cr = st.columns(2)
        with cl: st.plotly_chart(nw_bar_chart(), width="stretch")
        with cr:
            pie = allocation_pie_chart()
            if pie: st.plotly_chart(pie, width="stretch")
        mc1,mc2,mc3 = st.columns(3)
        mc1.metric("Weighted CAGR",     f"{weighted_cagr():.1f}%")
        mc2.metric("Risk Profile",      risk_profile())
        mc3.metric("10-Year Projection",fmt(portfolio_at_year(10)))

    recs = get_recommendations()
    if recs:
        st.markdown("### Recommendations")
        for icon,title,text in recs:
            st.markdown(f"**{icon} {title}** — {text}")

# ══════════════════════════════════════════════════════
# INCOME & EXPENSES
# ══════════════════════════════════════════════════════
with tab_inc_exp:
    if st.session_state.expenses or st.session_state.income:
        st.plotly_chart(expense_income_chart(), width="stretch")

    st.markdown("### 💰 Monthly Income Sources")
    st.caption(f"Total: {fmt_full(total_monthly_income())}/month")
    if st.session_state.income:
        hc = st.columns([3,2,1.5,0.8])
        for h,lbl in zip(hc,["Source","Monthly ₹","Growth %/yr",""]): h.caption(lbl)
    for i, inc in enumerate(st.session_state.income):
        cols = st.columns([3,2,1.5,0.8])
        with cols[0]: nn = st.text_input("Source", value=inc["name"], key=f"v{_v}_inc_name_{i}", label_visibility="collapsed", placeholder="e.g. Salary")
        with cols[1]: nm = currency_input("₹", inc["monthly"], key=f"v{_v}_inc_monthly_{i}", label_visibility="collapsed")
        with cols[2]: ng = st.number_input("Growth%", value=inc.get("growth",5.0), min_value=0.0, max_value=30.0, step=0.5, key=f"v{_v}_inc_growth_{i}", label_visibility="collapsed")
        with cols[3]:
            if st.button("🗑️", key=f"v{_v}_del_inc_{i}"): st.session_state.income.pop(i); st.rerun()
        st.session_state.income[i].update({"name":nn,"monthly":nm,"growth":ng})
    if st.button("➕ Add Income Source", key=f"v{_v}_add_inc"):
        st.session_state.income.append({"name":"","monthly":0,"growth":5.0}); st.rerun()

    st.divider()
    st.markdown("### 💸 Monthly Expenses")
    st.caption(f"Total: {fmt_full(total_monthly_expense())}/month · Avg inflation: {avg_inflation():.1f}%")
    if st.session_state.expenses:
        hc = st.columns([3,2,1.5,1.5,0.8])
        for h,lbl in zip(hc,["Name","Monthly ₹","Inflation %","Cumulative",""]): h.caption(lbl)
    for i, e in enumerate(st.session_state.expenses):
        cols = st.columns([3,2,1.5,1.5,0.8])
        with cols[0]: nn = st.text_input("Name", value=e["name"], key=f"v{_v}_exp_name_{i}", label_visibility="collapsed", placeholder="e.g. Rent")
        with cols[1]: nm = currency_input("₹", e["monthly"], key=f"v{_v}_exp_monthly_{i}", label_visibility="collapsed")
        with cols[2]: ni = st.number_input("Inf%", value=e["inflation"], min_value=0.0, max_value=30.0, step=0.5, key=f"v{_v}_exp_inf_{i}", label_visibility="collapsed")
        with cols[3]: nc = st.checkbox("Cum", value=e.get("cumulative",False), key=f"v{_v}_exp_cum_{i}", label_visibility="collapsed")
        with cols[4]:
            if st.button("🗑️", key=f"v{_v}_del_exp_{i}"): st.session_state.expenses.pop(i); st.rerun()
        st.session_state.expenses[i].update({"name":nn,"monthly":nm,"inflation":ni,"cumulative":nc})
    if st.button("➕ Add Expense", key=f"v{_v}_add_exp"):
        st.session_state.expenses.append({"name":"","monthly":0,"inflation":6.0}); st.rerun()

    st.divider()
    st.session_state.projection_years = st.number_input(
        "Projection Horizon (years)", min_value=1, max_value=50,
        value=st.session_state.projection_years, key=f"v{_v}_proj_yrs")

    if st.session_state.expenses:
        st.markdown("### Year-by-Year Expense Breakdown")
        cum_track = {(e["name"] or f"e{i}"): 0.0 for i,e in enumerate(st.session_state.expenses)}
        table_data = []
        for y in [0,1,5,10,15,20,25,30]:
            if y > st.session_state.projection_years: break
            row = {"Year":"Today" if y==0 else f"Yr {y}"}; total=0
            for i,e in enumerate(st.session_state.expenses):
                k = e["name"] or f"e{i}"
                if e.get("cumulative"):
                    prev=[0,1,5,10,15,20,25,30]; idx=prev.index(y)
                    start=prev[idx-1]+1 if idx>0 else 0
                    for yr in range(start,y+1): cum_track[k]+=compound(e["monthly"],e["inflation"],yr)*12
                    row[e["name"] or "—"]=fmt(cum_track[k]); total+=cum_track[k]
                else:
                    v=compound(e["monthly"],e["inflation"],y)
                    row[e["name"] or "—"]=fmt_full(round(v)); total+=v
            row["Total"]=fmt(total); table_data.append(row)
        st.dataframe(table_data, width="stretch", hide_index=True)

# ══════════════════════════════════════════════════════
# GOALS
# ══════════════════════════════════════════════════════
with tab_goals:
    st.markdown("### 🎯 Financial Goals")

    # Excel import
    with st.expander("📥 Import Goals from Excel", expanded=False):
        st.caption("Upload an .xlsx file with columns: Goal Name, Today's Cost, Inflation %, Target Year, Cumulative")
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
                        st.session_state.data_version += 1; st.rerun()
                with col_b:
                    if st.button("Append to existing", key=f"v{_v}_goal_append"):
                        st.session_state.goals.extend(new_goals)
                        st.session_state.data_version += 1; st.rerun()

    if st.session_state.goals:
        hc = st.columns([3,2,1.5,1.5,1.5,0.8])
        for h,lbl in zip(hc,["Goal Name","Today's Cost ₹/yr","Inflation %","Target Year","Cumulative",""]): h.caption(lbl)
    for i, g in enumerate(st.session_state.goals):
        cols = st.columns([3,2,1.5,1.5,1.5,0.8])
        with cols[0]: nn  = st.text_input("Name",  value=g["name"],        key=f"v{_v}_goal_name_{i}", label_visibility="collapsed", placeholder="e.g. Retirement")
        with cols[1]: nc  = currency_input("Cost",  g["current_cost"],      key=f"v{_v}_goal_cost_{i}", label_visibility="collapsed")
        with cols[2]: ni  = st.number_input("Inf%", value=g["inflation"],   key=f"v{_v}_goal_inf_{i}",  min_value=0.0, max_value=30.0, step=0.5, label_visibility="collapsed")
        with cols[3]: ny  = st.number_input("Yr",   value=min(int(g["target_year"]), 100), key=f"v{_v}_goal_yr_{i}",   min_value=1, max_value=100, label_visibility="collapsed")
        with cols[4]: ncu = st.checkbox("Cum",      value=g.get("cumulative",False), key=f"v{_v}_goal_cum_{i}", label_visibility="collapsed")
        with cols[5]:
            if st.button("🗑️", key=f"v{_v}_del_goal_{i}"): st.session_state.goals.pop(i); st.rerun()
        st.session_state.goals[i].update({"name":nn,"current_cost":nc,"inflation":ni,"target_year":ny,"cumulative":ncu})
    if st.button("➕ Add Goal", key=f"v{_v}_add_goal"):
        st.session_state.goals.append({"name":"","current_cost":0,"inflation":6.0,"target_year":5,"cumulative":False}); st.rerun()

    if st.session_state.goals:
        st.markdown("### Projected Goal Costs")
        proj=goal_projections(); rows=[]
        for g in proj:
            row={"Goal":g["name"] or "(unnamed)","Today's Cost":fmt_full(g["current_cost"]),
                 "Inflation":f'{g["inflation"]}%',"Year":f'Yr {g["target_year"]}',
                 "At Target Year":fmt(g["inflated_cost"])}
            if g.get("cumulative"): row["Cumulative Total"]=fmt(g["cumulative_cost"])
            rows.append(row)
        st.dataframe(rows, width="stretch", hide_index=True)

# ══════════════════════════════════════════════════════
# ASSETS
# ══════════════════════════════════════════════════════
with tab_assets:
    if st.session_state.assets:
        st.plotly_chart(asset_chart(), width="stretch")

    st.markdown("### 📈 Asset Portfolio")
    st.caption(f"Total: {fmt_full(total_net_worth())} · Weighted CAGR: {weighted_cagr():.1f}%")

    # Excel import
    with st.expander("📥 Import Assets from Excel", expanded=False):
        st.caption(
            "Upload an .xlsx with columns: Asset Name, Class, Purchase Date, Invested Amount, "
            "Current Value, Maturity Amount, Maturity Date, CAGR %, Tag Goals, SWP ₹/mo, SWP Start Yr"
        )
        asset_file = st.file_uploader("Upload Assets Excel", type=["xlsx","xls"], key=f"v{_v}_asset_upload")
        if asset_file:
            new_assets, err = import_assets_from_excel(asset_file)
            if err:
                st.error(f"Error reading file: {err}")
            else:
                st.success(f"✓ Found {len(new_assets)} assets. Choose action:")
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Replace all assets", key=f"v{_v}_asset_replace"):
                        st.session_state.assets = new_assets
                        st.session_state.data_version += 1; st.rerun()
                with col_b:
                    if st.button("Append to existing", key=f"v{_v}_asset_append"):
                        st.session_state.assets.extend(new_assets)
                        st.session_state.data_version += 1; st.rerun()

    gnames = goal_names()

    # Column headers
    if st.session_state.assets:
        hc = st.columns([2,1.2,1.2,1.4,1.4,1.4,1.2,1.8,1.2,1.2,0.5])
        for h,lbl in zip(hc,["Asset Name","Class","Purchase Date","Invested ₹","Current Value ₹",
                               "Maturity ₹","Maturity Date","Tag Goals","SWP ₹/mo","SWP Start Yr",""]):
            h.caption(lbl)

    for i, a in enumerate(st.session_state.assets):
        cols = st.columns([2,1.2,1.2,1.4,1.4,1.4,1.2,1.8,1.2,1.2,0.5])

        with cols[0]:
            nn = st.text_input("Name", value=a["name"], key=f"v{_v}_asset_name_{i}",
                label_visibility="collapsed", placeholder="e.g. HDFC FD")
        with cols[1]:
            nc = st.selectbox("Class", ASSET_CLASSES,
                index=ASSET_CLASSES.index(a["asset_class"]) if a["asset_class"] in ASSET_CLASSES else 0,
                key=f"v{_v}_asset_cls_{i}", label_visibility="collapsed")
        with cols[2]:
            pd_val = a.get("purchase_date","") or ""
            npd = st.text_input("Purchase Date", value=pd_val, key=f"v{_v}_asset_pd_{i}",
                label_visibility="collapsed", placeholder="DD/MM/YYYY")
        with cols[3]:
            ninv = currency_input("Invested", a.get("invested",0) or 0,
                key=f"v{_v}_asset_inv_{i}", label_visibility="collapsed")
        with cols[4]:
            nv = currency_input("Current ₹", a["value"], key=f"v{_v}_asset_val_{i}",
                label_visibility="collapsed")
        with cols[5]:
            nmat = currency_input("Maturity ₹", a.get("maturity_amt",0) or 0,
                key=f"v{_v}_asset_mat_{i}", label_visibility="collapsed")
        with cols[6]:
            md_val = a.get("maturity_date","") or ""
            nmd = st.text_input("Maturity Date", value=md_val, key=f"v{_v}_asset_md_{i}",
                label_visibility="collapsed", placeholder="DD/MM/YYYY")
        with cols[7]:
            current_tags = [t for t in (a.get("tagged_goals") or []) if t in gnames]
            nt = st.multiselect("Goals", options=gnames, default=current_tags,
                key=f"v{_v}_asset_tags_{i}", label_visibility="collapsed", placeholder="Tag goals…")
        with cols[8]:
            ns = currency_input("SWP", a.get("swp_monthly",0) or 0,
                key=f"v{_v}_asset_swp_{i}", label_visibility="collapsed")
        with cols[9]:
            nsy = st.number_input("SWP Yr", value=int(a.get("swp_start_year",0) or 0),
                min_value=0, max_value=100, key=f"v{_v}_asset_swpyr_{i}", label_visibility="collapsed")
        with cols[10]:
            if st.button("🗑️", key=f"v{_v}_del_asset_{i}"): st.session_state.assets.pop(i); st.rerun()

        # Auto-calc CAGR from maturity info if available; else keep manual entry
        if nmat > 0 and ninv > 0 and npd and nmd:
            auto_cagr = round(calc_asset_cagr(ninv, nmat, npd, nmd), 2)
        elif nmat > 0 and ninv > 0 and nmd:
            # Use today as purchase date
            auto_cagr = round(calc_asset_cagr(ninv, nmat, str(TODAY), nmd), 2)
        else:
            auto_cagr = a.get("cagr", 0.0) or 0.0

        # Show computed CAGR and post-tax maturity
        info_parts = []
        if auto_cagr > 0:
            info_parts.append(f"CAGR: **{auto_cagr:.2f}%**")
        if nmat > 0 and ninv > 0:
            inv_for_tax = ninv if ninv > 0 else a.get("invested", 0) or 0
            net_mat, tax_amt = asset_net_maturity(inv_for_tax, nmat, nc)
            tax_rate_pct = asset_tax_rate(nc) * 100
            info_parts.append(f"Tax ({tax_rate_pct:.0f}% on gains): {fmt(tax_amt)} · **Net Maturity: {fmt(net_mat)}**")
        if info_parts:
            st.caption("  ↳ " + "  ·  ".join(info_parts))

        if ns > 0:
            ai = avg_inflation()
            val_with_swp = asset_value_at_year({**a,"swp_monthly":ns,"swp_start_year":nsy,"cagr":auto_cagr,"value":nv}, nsy+10, ai)
            val_no_swp   = compound(nv, auto_cagr, nsy+10)
            st.caption(f"  ↳ SWP {fmt(ns)}/mo from Yr {nsy} → value at Yr {nsy+10}: {fmt(val_with_swp)} (vs {fmt(val_no_swp)} without SWP)")

        st.session_state.assets[i].update({
            "name":nn,"asset_class":nc,"purchase_date":npd,"invested":ninv,
            "value":nv,"maturity_amt":nmat,"maturity_date":nmd,
            "cagr":auto_cagr,"tagged_goals":nt,"swp_monthly":ns,"swp_start_year":nsy,
        })

    if st.button("➕ Add Asset", key=f"v{_v}_add_asset"):
        st.session_state.assets.append({
            "name":"","asset_class":"Equity","purchase_date":"","invested":0,
            "value":0,"maturity_amt":0,"maturity_date":"","cagr":0.0,
            "tagged_goals":[],"swp_monthly":0,"swp_start_year":0,
        }); st.rerun()

    if st.session_state.assets:
        st.markdown("### Asset Summary Table")
        ai = avg_inflation(); rows=[]
        for a in st.session_state.assets:
            tags   = ", ".join(a.get("tagged_goals") or []) or "—"
            swp    = f'{fmt(a.get("swp_monthly",0) or 0)}/mo Yr{a.get("swp_start_year",0) or 0}+' \
                     if (a.get("swp_monthly") or 0) > 0 else "—"
            inv    = a.get("invested",0) or 0
            mat    = a.get("maturity_amt",0) or 0
            net_m, tax_m = asset_net_maturity(inv, mat, a["asset_class"]) if (mat>0 and inv>0) else (0,0)
            rows.append({
                "Asset":         a["name"] or "(unnamed)",
                "Class":         a["asset_class"],
                "Purchase Date": a.get("purchase_date","") or "—",
                "Invested":      fmt_full(inv) if inv else "—",
                "Current Value": fmt_full(a["value"]),
                "Maturity Amt":  fmt(mat) if mat else "—",
                "Maturity Date": a.get("maturity_date","") or "—",
                "CAGR":          f'{a["cagr"]:.2f}%',
                "Tax on Gains":  fmt(tax_m) if tax_m else "—",
                "Net Maturity":  fmt(net_m) if net_m else "—",
                "Tagged Goals":  tags,
                "SWP":           swp,
                "5 Yrs":         fmt(asset_value_at_year(a, 5, ai)),
                "10 Yrs":        fmt(asset_value_at_year(a,10, ai)),
                "20 Yrs":        fmt(asset_value_at_year(a,20, ai)),
            })
        rows.append({
            "Asset":"Portfolio Total","Class":"","Purchase Date":"","Invested":"",
            "Current Value":fmt_full(total_net_worth()),"Maturity Amt":"","Maturity Date":"",
            "CAGR":f"{weighted_cagr():.1f}%","Tax on Gains":"","Net Maturity":"","Tagged Goals":"","SWP":"",
            "5 Yrs":fmt(portfolio_at_year(5)),"10 Yrs":fmt(portfolio_at_year(10)),"20 Yrs":fmt(portfolio_at_year(20)),
        })
        st.dataframe(rows, width="stretch", hide_index=True)

# ══════════════════════════════════════════════════════
# RETIREMENT TAB
# ══════════════════════════════════════════════════════
with tab_retire:
    st.markdown("### 🏖️ Retirement Corpus Drawdown Planner")
    st.caption("Model how long your retirement corpus lasts under quarterly SWP with tax-adjusted returns.")

    all_goals   = st.session_state.goals
    goal_options= [g["name"] or f"Goal {i+1}" for i,g in enumerate(all_goals)]
    retire_goals= [g for g in all_goals if "retire" in g.get("name","").lower() or "pension" in g.get("name","").lower()]

    col_cfg, col_info = st.columns([1,1])

    with col_cfg:
        st.markdown("#### Configuration")

        if not goal_options:
            st.warning("Add a goal in the Goals tab first.")
            st.stop()

        default_idx = 0
        if retire_goals:
            names = [g["name"] for g in all_goals]
            default_idx = names.index(retire_goals[0]["name"]) if retire_goals[0]["name"] in names else 0

        selected_goal_name = st.selectbox("Select Goal", goal_options,
            index=default_idx, key=f"v{_v}_ret_goal")

        # Push selected goal name into session state for dashboard
        st.session_state.ret_goal_name = selected_goal_name

        tagged_assets  = [a for a in st.session_state.assets if selected_goal_name in (a.get("tagged_goals") or [])]
        selected_goal  = next((g for g in all_goals if (g["name"] or f"Goal {all_goals.index(g)+1}") == selected_goal_name), None)
        goal_year      = selected_goal["target_year"] if selected_goal else 0
        ai             = avg_inflation()

        if tagged_assets:
            projected_corpus = sum(asset_value_at_year(a, goal_year, ai) for a in tagged_assets)
            dominant_class   = max(set(a["asset_class"] for a in tagged_assets),
                key=lambda c: sum(a["value"] for a in tagged_assets if a["asset_class"]==c))
            st.caption(f"🏷️ {len(tagged_assets)} asset(s) tagged · projected at Yr {goal_year}: **{fmt(projected_corpus)}** · class: **{dominant_class}**")
        else:
            projected_corpus = 0.0
            dominant_class   = "Equity"
            st.caption("No assets tagged to this goal. Enter corpus manually below.")

        opening_corpus = currency_input("Opening Corpus ₹ (at retirement)",
            int(projected_corpus) if projected_corpus > 0 else 0,
            key=f"v{_v}_ret_corpus")

        # Push corpus into session state for dashboard allocation
        st.session_state.ret_opening_corpus = opening_corpus

        if tagged_assets:
            total_val      = sum(a["value"] for a in tagged_assets)
            suggested_cagr = sum((a["value"]/total_val)*a["cagr"] for a in tagged_assets) if total_val > 0 else 8.0
        else:
            suggested_cagr = 8.0

        annual_return = st.number_input("Expected Annual Return %",
            value=round(suggested_cagr,1), min_value=0.0, max_value=30.0, step=0.5,
            key=f"v{_v}_ret_return")

        asset_class_for_tax = st.selectbox("Asset Class (for LTCG tax rate)", ASSET_CLASSES,
            index=ASSET_CLASSES.index(dominant_class) if dominant_class in ASSET_CLASSES else 1,
            key=f"v{_v}_ret_cls")

        tax_rate_display = TAX_RATES.get(asset_class_for_tax, 0.30)
        st.caption(f"LTCG tax rate: **{tax_rate_display*100:.1f}%** — on gain portion only")

        custom_tax = st.number_input("Override Tax Rate % (0 = use default)",
            value=0.0, min_value=0.0, max_value=50.0, step=0.5, key=f"v{_v}_ret_tax")
        effective_tax = (custom_tax/100) if custom_tax > 0 else None

        st.divider()
        st.markdown("**Quarterly Withdrawal**")
        monthly_exp = total_monthly_expense()
        suggested_qw = monthly_exp * 3 * (1 + ai/100) ** goal_year

        q_withdrawal = currency_input(
            "Quarterly Withdrawal ₹ (inflates annually)",
            int(suggested_qw) if suggested_qw > 0 else 0,
            key=f"v{_v}_ret_qwd")
        if monthly_exp > 0:
            st.caption(f"Suggested: {fmt(suggested_qw)} (3× monthly expenses inflated to Yr {goal_year})")

        withdrawal_inflation = st.number_input("Withdrawal Inflation Rate %/yr",
            value=round(ai,1), min_value=0.0, max_value=20.0, step=0.5, key=f"v{_v}_ret_winf")

    with col_info:
        st.markdown("#### How This Works")
        st.markdown("""
**Each quarter:**
1. Withdrawal taken from corpus **at the start** (before returns)
2. Remaining corpus earns the quarterly return
3. Tax on **gain portion only**: `withdrawal × (1 − cost basis %)`
4. Tax deducted from corpus alongside withdrawal

**Formula:**
```
Opening Corpus
− Quarterly Withdrawal
− Tax on Gain Portion
+ Return on Remainder
= Closing Corpus
```
**Tax rates:** Equity / Precious Metals: 12.5% · Debt / Property / Other: 30%

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
            q_withdrawal, withdrawal_inflation, effective_tax)

        total_quarters = len(rows)
        total_years    = total_quarters / 4
        total_tax      = sum(r["Tax Amount"] for r in rows)
        total_return   = sum(r["Gross Return"] for r in rows)

        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Corpus Lasts",        f"{total_years:.1f} yrs ({total_quarters} qtrs)")
        m2.metric("Total Withdrawn",     fmt(total_withdrawn))
        m3.metric("Total Tax Paid",      fmt(total_tax))
        m4.metric("Total Returns Earned",fmt(total_return))

        quarters_label  = [r["Quarter"] for r in rows]
        corpus_vals     = [r["Opening Corpus"] for r in rows]
        withdrawal_vals = [r["Withdrawal"] for r in rows]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=quarters_label, y=corpus_vals, name="Corpus",
            fill="tozeroy", fillcolor="rgba(37,99,235,0.1)",
            line=dict(color="#2563eb", width=2),
            hovertemplate="₹%{y:,.0f}<extra>Corpus</extra>"))
        fig.add_trace(go.Bar(x=quarters_label, y=withdrawal_vals, name="Quarterly Withdrawal",
            marker_color="rgba(220,38,38,0.5)", yaxis="y2",
            hovertemplate="₹%{y:,.0f}<extra>Withdrawal</extra>"))
        fig.update_layout(
            title="Corpus Drawdown Over Time",
            xaxis=dict(title="Quarter", tickangle=-45,
                tickvals=quarters_label[::4],
                ticktext=[quarters_label[i] for i in range(0,len(quarters_label),4)]),
            yaxis=dict(title="Corpus ₹", tickformat=","),
            yaxis2=dict(title="Withdrawal ₹", overlaying="y", side="right", showgrid=False),
            hovermode="x unified", template=None, height=420,
            legend=dict(orientation="h", y=-0.25), margin=dict(l=60,r=60,t=50,b=80))
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
            st.dataframe(display_rows, width="stretch", hide_index=True, height=450)
        else:
            annual = {}
            for r in rows:
                yr = r["Quarter"].split(" ")[0]
                if yr not in annual:
                    annual[yr] = {"Year":yr.replace("Y","Year "),"Opening Corpus":r["Opening Corpus"],
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
                "Tax Rate":         f"{(effective_tax or tax_rate_display)*100:.1f}%",
                "Tax Paid":         fmt_full(round(a["Total Tax"])),
                "Net Return":       fmt_full(round(a["Total Net Return"])),
                "Net Gain":         fmt_full(round(a["Net Gain"])),
                "Closing Corpus":   fmt_full(round(a["Closing Corpus"])),
            } for a, a in [(yr, data) for yr, data in annual.items()]]
            st.dataframe(ann_rows, width="stretch", hide_index=True, height=450)

        st.caption(f"Corpus depleted after {total_years:.1f} years · Withdrawn: {fmt(total_withdrawn)} · Tax: {fmt(total_tax)}")
