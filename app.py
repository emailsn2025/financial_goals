import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import json

# ─── Page config ───
st.set_page_config(
    page_title="Net Worth & Goal Planner",
    page_icon="📊",
    layout="wide",
)

# ─── Styling ───
st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 16px;
    }
    div[data-testid="stMetric"] label { font-size: 13px !important; }
    .status-full { background: #d1fae5; color: #059669; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; }
    .status-partial { background: #fef3c7; color: #d97706; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; }
    .status-unfunded { background: #fee2e2; color: #dc2626; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

ASSET_CLASSES = ["Debt", "Equity", "Property", "Precious Metals", "Other"]

# ─── Helpers ───
def fmt(n):
    """Format number in Indian notation (Lakhs/Crores)."""
    if n >= 1e7:
        return f"₹{n/1e7:.2f} Cr"
    if n >= 1e5:
        return f"₹{n/1e5:.2f} L"
    if n >= 1000:
        return f"₹{n/1000:.1f}K"
    return f"₹{round(n):,}"

def fmt_full(n):
    return f"₹{round(n):,}"

def compound(principal, rate_pct, years):
    return principal * (1 + rate_pct / 100) ** years

# ─── Session state defaults ───
if "expenses" not in st.session_state:
    st.session_state.expenses = [
        {"name": "Rent", "monthly": 20000, "inflation": 5.0},
        {"name": "Groceries & Food", "monthly": 12000, "inflation": 7.0},
        {"name": "Utilities & Bills", "monthly": 5000, "inflation": 6.0},
        {"name": "Transport", "monthly": 4000, "inflation": 5.0},
        {"name": "Other / Lifestyle", "monthly": 9000, "inflation": 6.0},
    ]

if "goals" not in st.session_state:
    st.session_state.goals = [
        {"name": "Child's Education", "current_cost": 2000000, "inflation": 8.0, "target_year": 10},
        {"name": "Home Purchase", "current_cost": 8000000, "inflation": 6.0, "target_year": 5},
        {"name": "Retirement Corpus", "current_cost": 30000000, "inflation": 7.0, "target_year": 25},
    ]

if "assets" not in st.session_state:
    st.session_state.assets = [
        {"name": "Equity MF Portfolio", "asset_class": "Equity", "value": 1500000, "cagr": 12.0},
        {"name": "Fixed Deposits", "asset_class": "Debt", "value": 800000, "cagr": 7.0},
        {"name": "Gold Holdings", "asset_class": "Precious Metals", "value": 500000, "cagr": 9.0},
        {"name": "Flat (Pune)", "asset_class": "Property", "value": 6000000, "cagr": 5.0},
    ]

if "projection_years" not in st.session_state:
    st.session_state.projection_years = 30


# ─── Computed values ───
def total_monthly():
    return sum(e["monthly"] for e in st.session_state.expenses)

def avg_inflation():
    tm = total_monthly()
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
        if i == 0:
            pv = portfolio_at_year(g["target_year"])
            allocated = min(pv, g["inflated_cost"])
            pct = min((pv / g["inflated_cost"]) * 100, 100) if g["inflated_cost"] > 0 else 0
            remaining = max(pv - g["inflated_cost"], 0)
        else:
            gap = g["target_year"] - projections[i - 1]["target_year"]
            grown = compound(remaining, weighted_cagr(), gap)
            allocated = min(grown, g["inflated_cost"])
            pct = min((grown / g["inflated_cost"]) * 100, 100) if g["inflated_cost"] > 0 else 0
            remaining = max(grown - g["inflated_cost"], 0)

        status = "Fully Funded" if pct >= 100 else ("Partially Funded" if pct > 0 else "Unfunded")
        results.append({**g, "allocated": allocated, "pct": round(pct), "status": status})

    return results

def get_recommendations():
    recs = []
    alloc = fifo_allocation()
    avg_inf = avg_inflation()
    tnw = total_net_worth()

    # 1. Shortfall
    shortfalls = [a for a in alloc if a["pct"] < 100]
    if shortfalls:
        g = shortfalls[0]
        gap = g["inflated_cost"] - g["allocated"]
        months = g["target_year"] * 12
        sip = gap / months if months > 0 else gap
        recs.append(("📊", "Cover Shortfall",
            f'"{g["name"]}" is {g["pct"]}% funded. Save ~{fmt(sip)}/month to close the {fmt(gap)} gap.'))

    # 2. Inflation warning
    for a in st.session_state.assets:
        if a["cagr"] < avg_inf:
            recs.append(("⚠️", "Inflation Warning",
                f'"{a["name"]}" returns {a["cagr"]}% — below your avg {avg_inf:.1f}% inflation.'))

    # 3. Horizon matching
    near_goals = [g for g in st.session_state.goals if g["target_year"] <= 3]
    eq_assets = [a for a in st.session_state.assets if a["asset_class"] == "Equity"]
    if near_goals and eq_assets:
        recs.append(("🔄", "Horizon Matching",
            "You have goals within 3 years. Consider shifting equity into debt for capital protection."))

    # 4. Diversification
    if tnw > 0:
        class_totals = {}
        for a in st.session_state.assets:
            class_totals[a["asset_class"]] = class_totals.get(a["asset_class"], 0) + a["value"]
        for cls, val in class_totals.items():
            if (val / tnw) * 100 > 60:
                recs.append(("⚖️", "Diversification Alert",
                    f"{cls} is {round((val/tnw)*100)}% of your portfolio. Consider diversifying."))

    # 5. Emergency fund
    inflated_6mo = total_monthly() * 6 * (1 + avg_inf / 100)
    liquid = sum(a["value"] for a in st.session_state.assets if a["asset_class"] in ["Debt", "Other"])
    if liquid < inflated_6mo:
        recs.append(("🛡️", "Emergency Fund",
            f"Keep {fmt(inflated_6mo)} (6 months inflated expenses) in liquid assets. Current: {fmt(liquid)}."))

    return recs[:5]


# ─── Charts ───
LINE_COLORS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#0d9488",
               "#e11d48", "#0891b2", "#ca8a04", "#6366f1", "#14b8a6"]

def expense_chart():
    years = list(range(st.session_state.projection_years + 1))
    fig = go.Figure()
    totals = [0.0] * len(years)

    for i, e in enumerate(st.session_state.expenses):
        vals = [compound(e["monthly"], e["inflation"], y) for y in years]
        for j, v in enumerate(vals):
            totals[j] += v
        fig.add_trace(go.Scatter(
            x=years, y=vals, name=e["name"] or f"Expense {i+1}",
            line=dict(color=LINE_COLORS[i % len(LINE_COLORS)], width=2),
            hovertemplate="%{y:,.0f}<extra>%{fullData.name}</extra>"
        ))

    fig.add_trace(go.Scatter(
        x=years, y=totals, name="Total",
        line=dict(color="#1e293b", width=3, dash="dash"),
        hovertemplate="%{y:,.0f}<extra>Total</extra>"
    ))

    fig.update_layout(
        title="Monthly Expense Projection by Item",
        xaxis_title="Year", yaxis_title="₹ / month",
        hovermode="x unified", template="plotly_white",
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

    fig.add_trace(go.Scatter(
        x=years, y=totals, name="Total Portfolio",
        line=dict(color="#1e293b", width=3, dash="dash"),
        hovertemplate="₹%{y:,.0f}<extra>Total Portfolio</extra>"
    ))

    fig.update_layout(
        title="Asset Growth Projection by Holding",
        xaxis_title="Year", yaxis_title="₹",
        hovermode="x unified", template="plotly_white",
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
    fig.update_layout(
        title="Asset Allocation", template="plotly_white",
        height=350, margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
    )
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
    fig.update_layout(
        title="Net Worth Projection", template="plotly_white",
        height=350, margin=dict(l=60, r=20, t=50, b=40),
        yaxis_title="₹",
    )
    return fig


# ═══════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════

st.markdown("## 📊 Net Worth & Goal Planner")
st.caption("Project your finances · Track goals · Allocate assets")

tab_dash, tab_exp, tab_goals, tab_assets = st.tabs(["Dashboard", "Expenses", "Goals", "Assets"])


# ═══════════════ DASHBOARD ═══════════════
with tab_dash:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Net Worth", fmt(total_net_worth()))
    c2.metric("Monthly Expenses", fmt(total_monthly()))
    c3.metric("Weighted CAGR", f"{weighted_cagr():.1f}%")
    c4.metric("Risk Profile", risk_profile())

    st.markdown("### Goal Coverage (FIFO Allocation)")
    alloc = fifo_allocation()
    if not alloc:
        st.info("Add goals and assets to see allocation.")
    for g in alloc:
        col_info, col_bar = st.columns([1, 2])
        with col_info:
            css_class = "status-full" if g["pct"] >= 100 else ("status-partial" if g["pct"] > 50 else "status-unfunded")
            st.markdown(f'**{g["name"]}** · Year {g["target_year"]}')
            st.markdown(f'Target: {fmt(g["inflated_cost"])} · Allocated: {fmt(g["allocated"])}')
            st.markdown(f'<span class="{css_class}">{g["status"]} ({g["pct"]}%)</span>', unsafe_allow_html=True)
        with col_bar:
            st.progress(min(g["pct"], 100) / 100)

    chart_l, chart_r = st.columns(2)
    with chart_l:
        st.plotly_chart(nw_bar_chart(), use_container_width=True)
    with chart_r:
        pie = allocation_pie_chart()
        if pie:
            st.plotly_chart(pie, use_container_width=True)
        else:
            st.info("No assets added yet.")

    # Recommendations
    recs = get_recommendations()
    if recs:
        st.markdown("### Recommendations")
        for icon, title, text in recs:
            st.markdown(f"**{icon} {title}** — {text}")


# ═══════════════ EXPENSES ═══════════════
with tab_exp:
    # Chart first
    st.plotly_chart(expense_chart(), use_container_width=True)

    st.markdown(f"### Monthly Expenses")
    st.caption(f"Total: {fmt_full(total_monthly())}/month · Avg inflation: {avg_inflation():.1f}%")

    st.session_state.projection_years = st.number_input(
        "Projection Horizon (years)", min_value=1, max_value=50,
        value=st.session_state.projection_years, key="proj_yrs_input"
    )

    # Editable expense rows
    for i, e in enumerate(st.session_state.expenses):
        cols = st.columns([3, 2, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Name", value=e["name"], key=f"exp_name_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[1]:
            new_monthly = st.number_input("Monthly ₹", value=e["monthly"], min_value=0, step=500, key=f"exp_monthly_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_inf = st.number_input("Inflation %", value=e["inflation"], min_value=0.0, max_value=30.0, step=0.5, key=f"exp_inf_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"del_exp_{i}"):
                st.session_state.expenses.pop(i)
                st.rerun()

        st.session_state.expenses[i]["name"] = new_name
        st.session_state.expenses[i]["monthly"] = new_monthly
        st.session_state.expenses[i]["inflation"] = new_inf

    if st.button("➕ Add Expense", key="add_exp"):
        st.session_state.expenses.append({"name": "", "monthly": 0, "inflation": 6.0})
        st.rerun()

    # Table
    st.markdown("### Year-by-Year Breakdown")
    table_data = []
    for y in range(0, st.session_state.projection_years + 1, 5):
        row = {"Year": f"Yr {y}" if y > 0 else "Today"}
        total = 0
        for e in st.session_state.expenses:
            val = compound(e["monthly"], e["inflation"], y)
            row[e["name"] or "—"] = fmt_full(round(val))
            total += val
        row["Total"] = fmt_full(round(total))
        table_data.append(row)
    st.dataframe(table_data, use_container_width=True, hide_index=True)


# ═══════════════ GOALS ═══════════════
with tab_goals:
    st.markdown("### Financial Goals")

    for i, g in enumerate(st.session_state.goals):
        cols = st.columns([3, 2, 1.5, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Goal Name", value=g["name"], key=f"goal_name_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[1]:
            new_cost = st.number_input("Today's Cost ₹", value=g["current_cost"], min_value=0, step=50000, key=f"goal_cost_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_inf = st.number_input("Inflation %", value=g["inflation"], min_value=0.0, max_value=30.0, step=0.5, key=f"goal_inf_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            new_yr = st.number_input("Target Year", value=g["target_year"], min_value=1, max_value=50, key=f"goal_yr_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[4]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"del_goal_{i}"):
                st.session_state.goals.pop(i)
                st.rerun()

        st.session_state.goals[i]["name"] = new_name
        st.session_state.goals[i]["current_cost"] = new_cost
        st.session_state.goals[i]["inflation"] = new_inf
        st.session_state.goals[i]["target_year"] = new_yr

    if st.button("➕ Add Goal", key="add_goal"):
        st.session_state.goals.append({"name": "", "current_cost": 0, "inflation": 6.0, "target_year": 5})
        st.rerun()

    # Projected costs table
    st.markdown("### Projected Goal Costs (sorted by timeline)")
    proj = goal_projections()
    proj_table = []
    for g in proj:
        proj_table.append({
            "Goal": g["name"] or "(unnamed)",
            "Today's Cost": fmt_full(g["current_cost"]),
            "Inflation": f'{g["inflation"]}%',
            "Year": f'Yr {g["target_year"]}',
            "Inflated Cost": fmt(g["inflated_cost"]),
        })
    st.dataframe(proj_table, use_container_width=True, hide_index=True)


# ═══════════════ ASSETS ═══════════════
with tab_assets:
    # Chart first
    st.plotly_chart(asset_chart(), use_container_width=True)

    st.markdown("### Asset Portfolio")
    st.caption(f"Total: {fmt_full(total_net_worth())} · Weighted CAGR: {weighted_cagr():.1f}%")

    for i, a in enumerate(st.session_state.assets):
        cols = st.columns([3, 2, 2, 1.5, 0.8])
        with cols[0]:
            new_name = st.text_input("Asset Name", value=a["name"], key=f"asset_name_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[1]:
            new_cls = st.selectbox("Class", ASSET_CLASSES, index=ASSET_CLASSES.index(a["asset_class"]), key=f"asset_cls_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[2]:
            new_val = st.number_input("Value ₹", value=a["value"], min_value=0, step=10000, key=f"asset_val_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[3]:
            new_cagr = st.number_input("CAGR %", value=a["cagr"], min_value=0.0, max_value=50.0, step=0.5, key=f"asset_cagr_{i}", label_visibility="collapsed" if i > 0 else "visible")
        with cols[4]:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️", key=f"del_asset_{i}"):
                st.session_state.assets.pop(i)
                st.rerun()

        st.session_state.assets[i]["name"] = new_name
        st.session_state.assets[i]["asset_class"] = new_cls
        st.session_state.assets[i]["value"] = new_val
        st.session_state.assets[i]["cagr"] = new_cagr

    if st.button("➕ Add Asset", key="add_asset"):
        st.session_state.assets.append({"name": "", "asset_class": "Equity", "value": 0, "cagr": 10.0})
        st.rerun()

    # Growth table
    st.markdown("### Asset Growth Table")
    asset_table = []
    for a in st.session_state.assets:
        asset_table.append({
            "Asset": a["name"] or "(unnamed)",
            "Class": a["asset_class"],
            "Today": fmt(a["value"]),
            "CAGR": f'{a["cagr"]}%',
            "5 Yrs": fmt(compound(a["value"], a["cagr"], 5)),
            "10 Yrs": fmt(compound(a["value"], a["cagr"], 10)),
            "20 Yrs": fmt(compound(a["value"], a["cagr"], 20)),
        })
    # Totals row
    asset_table.append({
        "Asset": "Portfolio Total",
        "Class": "",
        "Today": fmt(total_net_worth()),
        "CAGR": f"{weighted_cagr():.1f}%",
        "5 Yrs": fmt(portfolio_at_year(5)),
        "10 Yrs": fmt(portfolio_at_year(10)),
        "20 Yrs": fmt(portfolio_at_year(20)),
    })
    st.dataframe(asset_table, use_container_width=True, hide_index=True)
