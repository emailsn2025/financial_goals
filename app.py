import streamlit as st
import plotly.graph_objects as go
import json

# ─── Page config ───
st.set_page_config(
    page_title="Net Worth & Goal Planner",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 10px;
        padding: 12px 16px;
    }
    div[data-testid="stMetric"] label { font-size: 13px !important; }
    .badge-green { background: #059669; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; display: inline-block; }
    .badge-amber { background: #d97706; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; display: inline-block; }
    .badge-red { background: #dc2626; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; display: inline-block; }
</style>
""", unsafe_allow_html=True)

ASSET_CLASSES = ["Debt", "Equity", "Property", "Precious Metals", "Other"]
LINE_COLORS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#0d9488",
               "#e11d48", "#0891b2", "#ca8a04", "#6366f1", "#14b8a6"]

# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════

def indian_format(n):
    """Format a number with Indian comma grouping (lakhs/crores)."""
    n = int(round(n))
    negative = n < 0
    n = abs(n)
    s = str(n)
    if len(s) <= 3:
        return ("-" if negative else "") + s
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    for i, c in enumerate(reversed(rest)):
        if i > 0 and i % 2 == 0:
            parts.append(",")
        parts.append(c)
    formatted = "".join(reversed(parts)) + "," + last3
    return ("-" if negative else "") + formatted

def fmt(n):
    """Short format with lakhs/crores label."""
    n = round(n)
    if abs(n) >= 1e7:
        return f"₹{n/1e7:.2f} Cr"
    if abs(n) >= 1e5:
        return f"₹{n/1e5:.2f} L"
    return f"₹{indian_format(n)}"

def fmt_full(n):
    """Full format with Indian commas."""
    return f"₹{indian_format(n)}"

def parse_indian(s):
    """Parse a string with commas back to a number."""
    if not s or not s.strip():
        return 0
    cleaned = s.replace(",", "").replace("₹", "").replace(" ", "").strip()
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return 0

def compound(principal, rate_pct, years):
    return principal * (1 + rate_pct / 100) ** years

def currency_input(label, value, key, **kwargs):
    """Text input that displays and accepts Indian-formatted numbers."""
    display_val = indian_format(value) if value else ""
    raw = st.text_input(label, value=display_val, key=key, **kwargs)
    return parse_indian(raw)

# ═══════════════════════════════════════════════════
# SESSION STATE (empty defaults)
# ═══════════════════════════════════════════════════

if "income" not in st.session_state:
    st.session_state.income = []

if "expenses" not in st.session_state:
    st.session_state.expenses = []

if "goals" not in st.session_state:
    st.session_state.goals = []

if "assets" not in st.session_state:
    st.session_state.assets = []

if "projection_years" not in st.session_state:
    st.session_state.projection_years = 30

if "data_version" not in st.session_state:
    st.session_state.data_version = 0

if "show_todays_cost" not in st.session_state:
    st.session_state.show_todays_cost = False

_v = st.session_state.data_version

# ═══════════════════════════════════════════════════
# COMPUTED VALUES
# ═══════════════════════════════════════════════════

def total_monthly_income():
    return sum(e["monthly"] for e in st.session_state.income)

def total_monthly_expense():
    return sum(e["monthly"] for e in st.session_state.expenses)

def avg_inflation():
    tm = total_monthly_expense()
    if tm == 0:
        return 6.0
    return sum((e["monthly"] / tm) * e["inflation"] for e in st.session_state.expenses)

def total_net_worth():
    return sum(a["value"] for a in st.session_state.assets)

def weighted_cagr():
    tnw = total_net_worth()
    if tnw == 0:
        return 0.0
    return sum((a["value"] / tnw) * a["cagr"] for a in st.session_state.assets)

def portfolio_at_year(y):
    return sum(compound(a["value"], a["cagr"], y) for a in st.session_state.assets)

def risk_profile():
    tnw = total_net_worth()
    if tnw == 0:
        return "N/A"
    eq_pct = sum(a["value"] for a in st.session_state.assets if a["asset_class"] == "Equity") / tnw * 100
    debt_pct = sum(a["value"] for a in st.session_state.assets if a["asset_class"] in ["Debt", "Other"]) / tnw * 100
    if eq_pct > 70:
        return "Aggressive"
    if debt_pct > 60:
        return "Conservative"
    return "Balanced"

def goal_projections():
    sorted_goals = sorted(st.session_state.goals, key=lambda g: g["target_year"])
    return [
        {**g, "inflated_cost": compound(g["current_cost"], g["inflation"], g["target_year"])}
        for g in sorted_goals
    ]

def fifo_allocation():
    projections = goal_projections()
    results = []
    remaining = 0.0
    for i, g in enumerate(projections):
        cost = g["current_cost"] if st.session_state.show_todays_cost else g["inflated_cost"]
        if i == 0:
            pv = portfolio_at_year(g["target_year"])
            allocated = min(pv, cost)
            pct = min((pv / cost) * 100, 100) if cost > 0 else 0
            remaining = max(pv - cost, 0)
        else:
            gap = g["target_year"] - projections[i - 1]["target_year"]
            grown = compound(remaining, weighted_cagr(), gap)
            allocated = min(grown, cost)
            pct = min((grown / cost) * 100, 100) if cost > 0 else 0
            remaining = max(grown - cost, 0)
        status = "Fully Funded" if pct >= 100 else ("Partially Funded" if pct > 0 else "Unfunded")
        results.append({**g, "display_cost": cost, "allocated": allocated, "pct": round(pct), "status": status})
    return results

def monthly_surplus():
    return total_monthly_income() - total_monthly_expense()

def expense_coverage_years():
    """Find the year when projected expenses exceed projected income. Returns None if never."""
    if not st.session_state.income or not st.session_state.expenses:
        return None
    for y in range(1, 51):
        inc = sum(compound(e["monthly"], e.get("growth", 5.0), y) for e in st.session_state.income)
        exp = sum(compound(e["monthly"], e["inflation"], y) for e in st.session_state.expenses)
        if exp > inc:
            return y
    return None

def get_recommendations():
    recs = []
    alloc = fifo_allocation()
    avg_inf = avg_inflation()
    tnw = total_net_worth()

    shortfalls = [a for a in alloc if a["pct"] < 100]
    if shortfalls:
        g = shortfalls[0]
        gap_val = g["display_cost"] - g["allocated"]
        months = g["target_year"] * 12
        sip = gap_val / months if months > 0 else gap_val
        recs.append(("📊", "Cover Shortfall",
            f'"{g["name"]}" is {g["pct"]}% funded. Save ~{fmt(sip)}/month to close the {fmt(gap_val)} gap.'))

    for a in st.session_state.assets:
        if a["cagr"] < avg_inf and st.session_state.expenses:
            recs.append(("⚠️", "Inflation Warning",
                f'"{a["name"]}" returns {a["cagr"]}% — below your avg {avg_inf:.1f}% inflation.'))

    near_goals = [g for g in st.session_state.goals if g["target_year"] <= 3]
    eq_assets = [a for a in st.session_state.assets if a["asset_class"] == "Equity"]
    if near_goals and eq_assets:
        recs.append(("🔄", "Horizon Matching",
            "You have goals within 3 years. Consider shifting equity into debt for capital protection."))

    if tnw > 0:
        class_totals = {}
        for a in st.session_state.assets:
            class_totals[a["asset_class"]] = class_totals.get(a["asset_class"], 0) + a["value"]
        for cls, val in class_totals.items():
            if (val / tnw) * 100 > 60:
                recs.append(("⚖️", "Diversification Alert",
                    f"{cls} is {round((val/tnw)*100)}% of your portfolio. Consider diversifying."))

    tm = total_monthly_expense()
    if tm > 0:
        inflated_6mo = tm * 6 * (1 + avg_inf / 100)
        liquid = sum(a["value"] for a in st.session_state.assets if a["asset_class"] in ["Debt", "Other"])
        if liquid < inflated_6mo:
            recs.append(("🛡️", "Emergency Fund",
                f"Keep {fmt(inflated_6mo)} (6 months inflated expenses) in liquid assets. Current: {fmt(liquid)}."))

    crossover = expense_coverage_years()
    if crossover and crossover <= 20:
        recs.append(("📉", "Income Gap Ahead",
            f"Your expenses are projected to exceed your income by Year {crossover}. Plan for additional income or reduced spending."))

    return recs[:5]

# ═══════════════════════════════════════════════════
# CHARTS
# ═══════════════════════════════════════════════════

def expense_income_chart():
    years = list(range(st.session_state.projection_years + 1))
    fig = go.Figure()
    exp_totals = [0.0] * len(years)

    for i, e in enumerate(st.session_state.expenses):
        vals = [compound(e["monthly"], e["inflation"], y) for y in years]
        for j, v in enumerate(vals):
            exp_totals[j] += v
        fig.add_trace(go.Scatter(
            x=years, y=vals, name=e["name"] or f"Expense {i+1}",
            line=dict(color=LINE_COLORS[i % len(LINE_COLORS)], width=2),
            hovertemplate="₹%{y:,.0f}<extra>%{fullData.name}</extra>"
        ))

    if st.session_state.expenses:
        fig.add_trace(go.Scatter(
            x=years, y=exp_totals, name="Total Expenses",
            line=dict(color="#dc2626", width=3, dash="dash"),
            hovertemplate="₹%{y:,.0f}<extra>Total Expenses</extra>"
        ))

    if st.session_state.income:
        inc_totals = [sum(compound(e["monthly"], e.get("growth", 5.0), y) for e in st.session_state.income) for y in years]
        fig.add_trace(go.Scatter(
            x=years, y=inc_totals, name="Total Income",
            line=dict(color="#059669", width=3, dash="dot"),
            hovertemplate="₹%{y:,.0f}<extra>Total Income</extra>"
        ))

    fig.update_layout(
        title="Monthly Income vs Expenses Over Time",
        xaxis_title="Year", yaxis_title="₹ / month",
        hovermode="x unified", template=None,
        height=400, legend=dict(orientation="h", y=-0.15),
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig

def asset_chart():
    max_y = max(st.session_state.projection_years, max((g["target_year"] for g in st.session_state.goals), default=30))
    years = list(range(max_y + 1))
    fig = go.Figure()
    totals = [0.0] * len(years)

    for i, a in enumerate(st.session_state.assets):
        vals = [compound(a["value"], a["cagr"], y) for y in years]
        for j, v in enumerate(vals):
            totals[j] += v
        fig.add_trace(go.Scatter(
            x=years, y=vals, name=a["name"] or f"Asset {i+1}",
            line=dict(color=LINE_COLORS[i % len(LINE_COLORS)], width=2),
            hovertemplate="₹%{y:,.0f}<extra>%{fullData.name}</extra>"
        ))

    if st.session_state.assets:
        fig.add_trace(go.Scatter(
            x=years, y=totals, name="Total Portfolio",
            line=dict(color="#1e293b", width=3, dash="dash"),
            hovertemplate="₹%{y:,.0f}<extra>Total Portfolio</extra>"
        ))

    fig.update_layout(
        title="Asset Growth Projection by Holding",
        xaxis_title="Year", yaxis_title="₹",
        hovermode="x unified", template=None,
        height=400, legend=dict(orientation="h", y=-0.15),
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig

def allocation_pie_chart():
    class_totals = {}
    for a in st.session_state.assets:
        class_totals[a["asset_class"]] = class_totals.get(a["asset_class"], 0) + a["value"]
    labels = list(class_totals.keys())
    values = list(class_totals.values())
    if not values:
        return None
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.45,
        marker=dict(colors=LINE_COLORS[:len(labels)]),
        textinfo="label+percent", textposition="outside",
        hovertemplate="%{label}: ₹%{value:,.0f}<extra></extra>"
    ))
    fig.update_layout(title="Asset Allocation", template=None, height=350,
        margin=dict(l=20, r=20, t=50, b=20), showlegend=False)
    return fig

def nw_bar_chart():
    max_y = max(30, max((g["target_year"] for g in st.session_state.goals), default=30))
    years = list(range(0, max_y + 1, 5))
    vals = [portfolio_at_year(y) for y in years]
    fig = go.Figure(go.Bar(
        x=[f"Yr {y}" for y in years], y=vals,
        marker_color="#2563eb",
        hovertemplate="₹%{y:,.0f}<extra></extra>"
    ))
    fig.update_layout(title="Net Worth Projection", template=None, height=350,
        margin=dict(l=60, r=20, t=50, b=40), yaxis_title="₹")
    return fig


# ═══════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════

st.markdown("## 📊 Net Worth & Goal Planner")

# ─── Save / Load ───
with st.expander("💾 Save & Load Your Data", expanded=False):
    st.caption("Your data resets when you close this tab. Download your data to keep it safe.")
    save_col, load_col, reset_col = st.columns([1, 1, 1])

    with save_col:
        save_data = json.dumps({
            "income": st.session_state.income,
            "expenses": st.session_state.expenses,
            "projection_years": st.session_state.projection_years,
            "goals": st.session_state.goals,
            "assets": st.session_state.assets,
        }, indent=2)
        st.download_button("⬇️ Download My Data", data=save_data,
            file_name="financial_planner_data.json", mime="application/json",
            use_container_width=True)

    with load_col:
        uploaded = st.file_uploader("Load saved data", type=["json"], label_visibility="collapsed")
        if uploaded is not None:
            try:
                data = json.loads(uploaded.read().decode("utf-8"))
                st.session_state["_pending_load"] = data
                st.success(f"✓ File read — ready to apply")
            except Exception as e:
                st.error(f"Could not read file: {e}")
        if st.session_state.get("_pending_load"):
            if st.button("✅ Apply Loaded Data", use_container_width=True, type="primary"):
                data = st.session_state.pop("_pending_load")
                for key in ["income", "expenses", "goals", "assets", "projection_years"]:
                    if key in data:
                        st.session_state[key] = data[key]
                st.session_state.data_version += 1
                st.rerun()

    with reset_col:
        if st.button("🔄 Reset to Empty", use_container_width=True):
            st.session_state.income = []
            st.session_state.expenses = []
            st.session_state.goals = []
            st.session_state.assets = []
            st.session_state.projection_years = 30
            st.session_state.data_version += 1
            st.rerun()

st.caption("Project your finances · Track goals · Allocate assets")

tab_dash, tab_inc_exp, tab_goals, tab_assets = st.tabs(["Dashboard", "Income & Expenses", "Goals", "Assets"])


# ═══════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════
with tab_dash:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Net Worth", fmt(total_net_worth()))
    c2.metric("Monthly Income", fmt(total_monthly_income()))
    c3.metric("Monthly Expenses", fmt(total_monthly_expense()))
    surplus = monthly_surplus()
    c4.metric("Monthly Surplus", fmt(surplus), delta=None)

    # ── Income vs Expense coverage ──
    if st.session_state.income or st.session_state.expenses:
        st.markdown("### Monthly Cash Flow")
        inc = total_monthly_income()
        exp = total_monthly_expense()
        if exp > 0 and inc > 0:
            coverage_pct = round((inc / exp) * 100)
            if coverage_pct >= 100:
                st.markdown(f'<span class="badge-green">Expenses Covered ({coverage_pct}%)</span> — surplus of {fmt_full(surplus)}/month', unsafe_allow_html=True)
            else:
                st.markdown(f'<span class="badge-red">Shortfall ({coverage_pct}% covered)</span> — deficit of {fmt_full(abs(surplus))}/month', unsafe_allow_html=True)

            crossover = expense_coverage_years()
            if crossover:
                st.caption(f"⚠️ At current growth rates, your expenses will overtake your income in ~{crossover} years.")
            st.progress(min(coverage_pct, 100) / 100)
        elif exp > 0:
            st.markdown(f'<span class="badge-red">No income added</span> — add income sources in the Income & Expenses tab', unsafe_allow_html=True)
        elif inc > 0:
            st.markdown(f'<span class="badge-green">No expenses added yet</span>', unsafe_allow_html=True)

    # ── Goal allocation ──
    st.markdown("### Goal Coverage (FIFO Allocation)")
    cost_toggle_col, _ = st.columns([1, 3])
    with cost_toggle_col:
        st.session_state.show_todays_cost = st.toggle(
            "Show today's cost (before inflation)",
            value=st.session_state.show_todays_cost,
            key=f"v{_v}_cost_toggle_dash"
        )

    alloc = fifo_allocation()
    if not alloc:
        st.info("Add goals and assets to see allocation.")
    for g in alloc:
        col_info, col_bar = st.columns([1, 2])
        with col_info:
            css = "badge-green" if g["pct"] >= 100 else ("badge-amber" if g["pct"] > 50 else "badge-red")
            cost_label = "Today's cost" if st.session_state.show_todays_cost else "Inflated target"
            st.markdown(f'**{g["name"]}** · Year {g["target_year"]}')
            st.markdown(f'{cost_label}: {fmt(g["display_cost"])} · Allocated: {fmt(g["allocated"])}')
            st.markdown(f'<span class="{css}">{g["status"]} ({g["pct"]}%)</span>', unsafe_allow_html=True)
        with col_bar:
            st.progress(min(g["pct"], 100) / 100)

    # ── Charts ──
    if st.session_state.assets:
        chart_l, chart_r = st.columns(2)
        with chart_l:
            st.plotly_chart(nw_bar_chart(), width="stretch")
        with chart_r:
            pie = allocation_pie_chart()
            if pie:
                st.plotly_chart(pie, width="stretch")

    # ── Additional metrics ──
    if st.session_state.assets:
        st.markdown("### Portfolio Snapshot")
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Weighted CAGR", f"{weighted_cagr():.1f}%")
        mc2.metric("Risk Profile", risk_profile())
        mc3.metric("10-Year Projection", fmt(portfolio_at_year(10)))

    # ── Recommendations ──
    recs = get_recommendations()
    if recs:
        st.markdown("### Recommendations")
        for icon, title, text in recs:
            st.markdown(f"**{icon} {title}** — {text}")


# ═══════════════════════════════════════════════════
# INCOME & EXPENSES
# ═══════════════════════════════════════════════════
with tab_inc_exp:
    # Chart first (only if data exists)
    if st.session_state.expenses or st.session_state.income:
        st.plotly_chart(expense_income_chart(), width="stretch")

    # ── Income ──
    st.markdown("### 💰 Monthly Income Sources")
    st.caption(f"Total: {fmt_full(total_monthly_income())}/month")

    for i, inc in enumerate(st.session_state.income):
        cols = st.columns([3, 2, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Source", value=inc["name"], key=f"v{_v}_inc_name_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                placeholder="e.g. Salary, Freelance, Rental")
        with cols[1]:
            new_monthly = currency_input("Monthly ₹", inc["monthly"], key=f"v{_v}_inc_monthly_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_growth = st.number_input("Growth %/yr", value=inc.get("growth", 5.0),
                min_value=0.0, max_value=30.0, step=0.5,
                key=f"v{_v}_inc_growth_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"v{_v}_del_inc_{i}"):
                st.session_state.income.pop(i)
                st.rerun()

        st.session_state.income[i]["name"] = new_name
        st.session_state.income[i]["monthly"] = new_monthly
        st.session_state.income[i]["growth"] = new_growth

    if st.button("➕ Add Income Source", key=f"v{_v}_add_inc"):
        st.session_state.income.append({"name": "", "monthly": 0, "growth": 5.0})
        st.rerun()

    st.divider()

    # ── Expenses ──
    st.markdown("### 💸 Monthly Expenses")
    st.caption(f"Total: {fmt_full(total_monthly_expense())}/month · Avg inflation: {avg_inflation():.1f}%")

    for i, e in enumerate(st.session_state.expenses):
        cols = st.columns([3, 2, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Name", value=e["name"], key=f"v{_v}_exp_name_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                placeholder="e.g. Rent, Groceries")
        with cols[1]:
            new_monthly = currency_input("Monthly ₹", e["monthly"], key=f"v{_v}_exp_monthly_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_inf = st.number_input("Inflation %", value=e["inflation"],
                min_value=0.0, max_value=30.0, step=0.5,
                key=f"v{_v}_exp_inf_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"v{_v}_del_exp_{i}"):
                st.session_state.expenses.pop(i)
                st.rerun()

        st.session_state.expenses[i]["name"] = new_name
        st.session_state.expenses[i]["monthly"] = new_monthly
        st.session_state.expenses[i]["inflation"] = new_inf

    if st.button("➕ Add Expense", key=f"v{_v}_add_exp"):
        st.session_state.expenses.append({"name": "", "monthly": 0, "inflation": 6.0})
        st.rerun()

    st.divider()

    st.session_state.projection_years = st.number_input(
        "Projection Horizon (years)", min_value=1, max_value=50,
        value=st.session_state.projection_years, key=f"v{_v}_proj_yrs"
    )

    # Table
    if st.session_state.expenses:
        st.markdown("### Year-by-Year Expense Breakdown")
        table_data = []
        for y in [0, 1, 5, 10, 15, 20, 25, 30]:
            if y > st.session_state.projection_years:
                break
            row = {"Year": "Today" if y == 0 else f"Yr {y}"}
            total = 0
            for e in st.session_state.expenses:
                val = compound(e["monthly"], e["inflation"], y)
                row[e["name"] or "—"] = fmt_full(round(val))
                total += val
            row["Total"] = fmt_full(round(total))
            table_data.append(row)
        st.dataframe(table_data, width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════
# GOALS
# ═══════════════════════════════════════════════════
with tab_goals:
    st.markdown("### 🎯 Financial Goals")

    cost_toggle = st.toggle(
        "Show today's cost (before inflation)",
        value=st.session_state.show_todays_cost,
        key=f"v{_v}_cost_toggle_goals"
    )
    st.session_state.show_todays_cost = cost_toggle

    for i, g in enumerate(st.session_state.goals):
        cols = st.columns([3, 2, 1.5, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Goal Name", value=g["name"], key=f"v{_v}_goal_name_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                placeholder="e.g. Retirement, Home, Education")
        with cols[1]:
            new_cost = currency_input("Today's Cost ₹", g["current_cost"], key=f"v{_v}_goal_cost_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_inf = st.number_input("Inflation %", value=g["inflation"],
                min_value=0.0, max_value=30.0, step=0.5,
                key=f"v{_v}_goal_inf_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            new_yr = st.number_input("Target Year", value=g["target_year"],
                min_value=1, max_value=50,
                key=f"v{_v}_goal_yr_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[4]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"v{_v}_del_goal_{i}"):
                st.session_state.goals.pop(i)
                st.rerun()

        st.session_state.goals[i]["name"] = new_name
        st.session_state.goals[i]["current_cost"] = new_cost
        st.session_state.goals[i]["inflation"] = new_inf
        st.session_state.goals[i]["target_year"] = new_yr

    if st.button("➕ Add Goal", key=f"v{_v}_add_goal"):
        st.session_state.goals.append({"name": "", "current_cost": 0, "inflation": 6.0, "target_year": 5})
        st.rerun()

    if st.session_state.goals:
        st.markdown("### Projected Goal Costs (sorted by timeline)")
        proj = goal_projections()
        proj_table = []
        for g in proj:
            row = {
                "Goal": g["name"] or "(unnamed)",
                "Today's Cost": fmt_full(g["current_cost"]),
                "Inflation": f'{g["inflation"]}%',
                "Year": f'Yr {g["target_year"]}',
            }
            if st.session_state.show_todays_cost:
                row["Using Cost"] = fmt_full(g["current_cost"])
            else:
                row["Inflated Cost"] = fmt(g["inflated_cost"])
            proj_table.append(row)
        st.dataframe(proj_table, width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════
# ASSETS
# ═══════════════════════════════════════════════════
with tab_assets:
    if st.session_state.assets:
        st.plotly_chart(asset_chart(), width="stretch")

    st.markdown("### 📈 Asset Portfolio")
    st.caption(f"Total: {fmt_full(total_net_worth())} · Weighted CAGR: {weighted_cagr():.1f}%")

    for i, a in enumerate(st.session_state.assets):
        cols = st.columns([3, 2, 2, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Asset Name", value=a["name"], key=f"v{_v}_asset_name_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                placeholder="e.g. HDFC Equity Fund")
        with cols[1]:
            new_cls = st.selectbox("Class", ASSET_CLASSES,
                index=ASSET_CLASSES.index(a["asset_class"]) if a["asset_class"] in ASSET_CLASSES else 0,
                key=f"v{_v}_asset_cls_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_val = currency_input("Value ₹", a["value"], key=f"v{_v}_asset_val_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            new_cagr = st.number_input("CAGR %", value=a["cagr"],
                min_value=0.0, max_value=50.0, step=0.5,
                key=f"v{_v}_asset_cagr_{i}",
                label_visibility="collapsed" if i > 0 else "visible")
        with cols[4]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"v{_v}_del_asset_{i}"):
                st.session_state.assets.pop(i)
                st.rerun()

        st.session_state.assets[i]["name"] = new_name
        st.session_state.assets[i]["asset_class"] = new_cls
        st.session_state.assets[i]["value"] = new_val
        st.session_state.assets[i]["cagr"] = new_cagr

    if st.button("➕ Add Asset", key=f"v{_v}_add_asset"):
        st.session_state.assets.append({"name": "", "asset_class": "Equity", "value": 0, "cagr": 10.0})
        st.rerun()

    if st.session_state.assets:
        st.markdown("### Asset Growth Table")
        asset_table = []
        for a in st.session_state.assets:
            asset_table.append({
                "Asset": a["name"] or "(unnamed)",
                "Class": a["asset_class"],
                "Today": fmt_full(a["value"]),
                "CAGR": f'{a["cagr"]}%',
                "5 Yrs": fmt(compound(a["value"], a["cagr"], 5)),
                "10 Yrs": fmt(compound(a["value"], a["cagr"], 10)),
                "20 Yrs": fmt(compound(a["value"], a["cagr"], 20)),
            })
        asset_table.append({
            "Asset": "Portfolio Total", "Class": "",
            "Today": fmt_full(total_net_worth()),
            "CAGR": f"{weighted_cagr():.1f}%",
            "5 Yrs": fmt(portfolio_at_year(5)),
            "10 Yrs": fmt(portfolio_at_year(10)),
            "20 Yrs": fmt(portfolio_at_year(20)),
        })
        st.dataframe(asset_table, width="stretch", hide_index=True)
