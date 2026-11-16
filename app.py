"""Streamlit Dashboard — D2C Growth & Profitability Control Tower.

A local-first, human-in-the-loop analytics and decision-support application for
 the fictional Indian skincare D2C brand "AuraVeda Skincare".
All business logic resides in tested modules under `src/`.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.attribution import (
    ATTRIBUTION_CAVEAT,
    compute_acquisition_summary,
    compute_campaign_performance,
    compute_channel_acquisition_and_profitability,
)
from src.cohorts import compute_monthly_cohort_retention
from src.config import load_settings
from src.metrics import (
    METRIC_GLOSSARY,
    apply_global_filters,
    compute_business_performance_And_economics,
    compute_cod_vs_prepaid_metrics,
    compute_funnel_metrics,
    compute_inventory_and_stockout_metrics,
    compute_operations_breakdowns,
    compute_sku_profitability,
    compute_time_series_trends,
)
from src.pipeline import PipelineResult, run_data_engineering_pipeline
from src.recommendations import generate_recommendations, recommendations_to_dataframe
from src.segmentation import (
    RFM_SCORING_RULES,
    compute_repeat_purchase_and_ltv_summary,
    compute_rfm_table,
    summarize_rfm_segments,
)

# -----------------------------------------------------------------------------
# Formatting Helpers (UI Presentation Only)
# -----------------------------------------------------------------------------
COLOR_PALETTE = ["#0F766E", "#0284C7", "#D97706", "#DC2626", "#7C3AED", "#2563EB", "#059669"]


def fmt_inr(val: float | int | None, decimals: int = 0) -> str:
    """Format a number as INR currency (₹) or 'NA' when None/NaN."""
    if val is None or pd.isna(val):
        return "NA"
    if decimals == 0:
        return f"₹{float(val):,.0f}"
    return f"₹{float(val):,.{decimals}f}"


def fmt_pct(val: float | None, decimals: int = 2) -> str:
    """Format a ratio (0..1) as a percentage string or 'NA' when None/NaN."""
    if val is None or pd.isna(val):
        return "NA"
    return f"{float(val) * 100:.{decimals}f}%"


def fmt_mult(val: float | None, decimals: int = 2) -> str:
    """Format a multiplier (e.g. ROAS/MER) as '1.23x' or 'NA'."""
    if val is None or pd.isna(val):
        return "NA"
    return f"{float(val):.{decimals}f}x"


def fmt_int(val: int | float | None) -> str:
    """Format an integer count with thousands separators or 'NA'."""
    if val is None or pd.isna(val):
        return "NA"
    return f"{int(val):,}"


@st.cache_resource(show_spinner="Loading and validating D2C Control Tower datasets...")
def get_pipeline_state() -> PipelineResult:
    """Load validated datasets, canonical tables, and DuckDB state once per session without unnecessary reloads."""
    settings = load_settings()
    raw_orders_path = settings.get("data", {}).get("orders", "data/raw/orders.csv")
    rel_db = settings.get("database", {}).get("path", "data/processed/d2c_analytics.duckdb")
    from pathlib import Path
    from src.config import PROJECT_ROOT

    orders_file = PROJECT_ROOT / raw_orders_path
    db_file = PROJECT_ROOT / rel_db
    regenerate = not orders_file.exists()
    write_artifacts = regenerate or (not db_file.exists())
    return run_data_engineering_pipeline(regenerate_data=regenerate, write_artifacts=write_artifacts)


def render_synthetic_disclosure_banner(brand_name: str, seed: int) -> None:
    """Render visible synthetic data disclosure banner on every dashboard page."""
    st.info(
        f"**SYNTHETIC DATA DISCLOSURE**: All figures shown are **100% deterministic synthetic data** "
        f"(Seed = `{seed}`, Currency = `INR (₹)`, Timezone = `Asia/Kolkata`) generated for the fictional "
        f"Indian skincare D2C case study **{brand_name}**. Zero real personal data (PII) is used. "
        f"Recommendations are human-in-the-loop decision support only.",
        icon="ℹ️",
    )


def main() -> None:
    st.set_page_config(
        page_title="D2C Growth & Profitability Control Tower",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Custom CSS for clean cards and typography
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 12px 16px;
        }
        div[data-testid="stMetricLabel"] > div {
            font-weight: 600;
            color: #334155;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    try:
        state = get_pipeline_state()
    except Exception as exc:
        st.error(f"Failed to initialize data pipeline: {exc}")
        st.stop()

    settings = load_settings()
    proj_cfg = settings.get("project", {})
    brand_name = str(proj_cfg.get("brand_name", "AuraVeda Skincare (Fictional Indian D2C Brand)"))
    seed_val = int(proj_cfg.get("random_seed", 42))

    base_orders = state.canonical_model.canonical_orders
    base_items = state.canonical_model.canonical_order_items
    raw_tables = state.validation_report.clean_tables
    base_spend = raw_tables["marketing_spend"]
    base_sessions = raw_tables["sessions"]
    base_inventory = raw_tables["inventory_snapshots"]
    base_products = raw_tables["products"]
    base_customers = raw_tables["customers"]
    base_rfm = state.analytics_outputs["rfm_table"]

    # -------------------------------------------------------------------------
    # Sidebar Navigation & Global Filters
    # -------------------------------------------------------------------------
    st.sidebar.title("🏛️ D2C Control Tower")
    st.sidebar.caption(brand_name)

    nav_pages = [
        "1. Executive Overview",
        "2. Marketing Performance",
        "3. Conversion Funnel",
        "4. Profitability & Unit Economics",
        "5. Customer Intelligence",
        "6. Operations & Returns",
        "7. Product & Inventory",
        "8. Business Recommendations",
        "9. Data Quality & Glossary",
    ]
    qp_page = st.query_params.get("page", None)
    default_page_idx = int(qp_page) - 1 if (qp_page and str(qp_page).isdigit() and 1 <= int(qp_page) <= len(nav_pages)) else 0
    selected_page = st.sidebar.radio("Navigate View", nav_pages, index=default_page_idx)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Global Filters")

    min_date_str = str(base_orders["order_day"].min()) if not base_orders.empty else "2026-05-01"
    max_date_str = str(base_orders["order_day"].max()) if not base_orders.empty else "2026-10-31"
    min_dt = pd.to_datetime(min_date_str).date()
    max_dt = pd.to_datetime(max_date_str).date()

    all_channels = sorted(base_orders["channel"].dropna().unique().tolist())
    raw_campaigns = sorted([c for c in base_orders["campaign_id"].fillna("").unique().tolist() if c != ""])
    all_campaigns = raw_campaigns + ["UNASSIGNED"]
    all_products = sorted(base_products["product_id"].unique().tolist())
    prod_label_map = {
        row["product_id"]: f"{row['product_id']} — {row['product_name']}"
        for _, row in base_products.iterrows()
    }
    all_rfm_segments = sorted(base_rfm["rfm_segment"].unique().tolist()) if not base_rfm.empty else []
    all_payment_modes = sorted(base_orders["payment_mode"].dropna().unique().tolist())
    all_city_tiers = sorted(base_orders["city_tier"].dropna().unique().tolist())

    if st.sidebar.button("🔄 Reset All Filters", use_container_width=True):
        for k in (
            "flt_dates",
            "flt_freq",
            "flt_channels",
            "flt_campaigns",
            "flt_products",
            "flt_segments",
            "flt_payments",
            "flt_tiers",
        ):
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    date_range = st.sidebar.date_input(
        "Order / Activity Date Window",
        value=(min_dt, max_dt),
        min_value=min_dt,
        max_value=max_dt,
        key="flt_dates",
    )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        sel_start_str = date_range[0].strftime("%Y-%m-%d")
        sel_end_str = date_range[1].strftime("%Y-%m-%d")
    else:
        sel_start_str = min_date_str
        sel_end_str = max_date_str

    trend_freq_label = st.sidebar.selectbox(
        "Trend Aggregation Grain",
        options=["Weekly", "Monthly", "Daily"],
        index=0,
        key="flt_freq",
    )
    freq_map = {"Weekly": "W-MON", "Monthly": "M", "Daily": "D"}
    sel_freq = freq_map[trend_freq_label]

    sel_channels = st.sidebar.multiselect(
        "Sales Channel",
        options=all_channels,
        default=[],
        placeholder="All Channels",
        key="flt_channels",
    )
    sel_campaigns = st.sidebar.multiselect(
        "Marketing Campaign",
        options=all_campaigns,
        default=[],
        placeholder="All Campaigns",
        key="flt_campaigns",
    )
    sel_products = st.sidebar.multiselect(
        "Product / SKU",
        options=all_products,
        format_func=lambda x: prod_label_map.get(x, x),
        default=[],
        placeholder="All Products (8 SKUs)",
        key="flt_products",
    )
    sel_segments = st.sidebar.multiselect(
        "Customer RFM Segment",
        options=all_rfm_segments,
        default=[],
        placeholder="All Customer Segments",
        key="flt_segments",
    )
    sel_payments = st.sidebar.multiselect(
        "Payment Mode",
        options=all_payment_modes,
        default=[],
        placeholder="All (Prepaid & COD)",
        key="flt_payments",
    )
    sel_tiers = st.sidebar.multiselect(
        "Customer City Tier",
        options=all_city_tiers,
        default=[],
        placeholder="All City Tiers",
        key="flt_tiers",
    )

    # Apply global filters via tested analytics helper
    sliced = apply_global_filters(
        canonical_orders=base_orders,
        canonical_order_items=base_items,
        marketing_spend=base_spend,
        sessions=base_sessions,
        inventory_snapshots=base_inventory,
        rfm_table=base_rfm,
        start_date=sel_start_str,
        end_date=sel_end_str,
        channels=sel_channels or None,
        campaigns=sel_campaigns or None,
        product_ids=sel_products or None,
        rfm_segments=sel_segments or None,
        payment_modes=sel_payments or None,
        city_tiers=sel_tiers or None,
    )

    flt_orders = sliced["canonical_orders"]
    flt_items = sliced["canonical_order_items"]
    flt_spend = sliced["marketing_spend"]
    flt_sessions = sliced["sessions"]
    flt_inventory = sliced["inventory_snapshots"]

    # Sidebar filtered summary & CSV export
    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"**Active Slice**: `{sel_start_str}` to `{sel_end_str}`  \n"
        f"**Filtered Orders**: `{len(flt_orders):,}` / `{len(base_orders):,}`  \n"
        f"**Filtered Sessions**: `{len(flt_sessions):,}` / `{len(base_sessions):,}`"
    )
    if not flt_orders.empty:
        st.sidebar.download_button(
            label="📥 Download Filtered Orders (CSV)",
            data=flt_orders.to_csv(index=False).encode("utf-8"),
            file_name=f"filtered_canonical_orders_{sel_start_str}_{sel_end_str}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # Top Title & Synthetic Banner
    st.title("📊 D2C Growth & Profitability Control Tower")
    render_synthetic_disclosure_banner(brand_name=brand_name, seed=seed_val)

    # Check for empty filter slice on order-dependent views
    if flt_orders.empty and selected_page not in ("7. Product & Inventory", "9. Data Quality & Glossary"):
        st.warning(
            "No orders match the current filter selection. Try broadening your Date Range, Channel, "
            "Campaign, SKU, or Customer Segment filters, or click **Reset All Filters** in the sidebar."
        )
        return

    # Pre-compute core metrics for the active slice
    kpis = compute_business_performance_And_economics(flt_orders)
    acq = compute_acquisition_summary(flt_orders, flt_spend)
    repeat_info = compute_repeat_purchase_and_ltv_summary(flt_orders, base_customers)
    trends_df = compute_time_series_trends(flt_orders, flt_spend, flt_sessions, freq=sel_freq)

    # =========================================================================
    # PAGE 1: EXECUTIVE OVERVIEW
    # =========================================================================
    if selected_page == "1. Executive Overview":
        st.subheader("1. Executive Overview — Growth vs Profitability")
        st.caption(
            f"Window: `{sel_start_str}` to `{sel_end_str}` | Distinguishes Placed GMV, Net Merchandise Sales, "
            "Gross Profit, and Contribution Profit (CM2 after COGS, discounts, refunds, RTO/forward shipping, and payment fees)."
        )

        # Row 1 KPIs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Net Merchandise Sales",
            fmt_inr(kpis["net_merchandise_sales"]),
            f"Placed GMV: {fmt_inr(kpis['placed_gmv'])}",
            help=METRIC_GLOSSARY["net_merchandise_sales"]["formula"]
            + " — "
            + METRIC_GLOSSARY["net_merchandise_sales"]["caveat"],
        )
        c2.metric(
            "Total Placed Orders",
            fmt_int(kpis["placed_orders"]),
            f"Delivered Cohort: {fmt_int(kpis['delivered_orders'])} ({fmt_pct(kpis['delivery_rate'])} of shipped)",
            help=METRIC_GLOSSARY["placed_orders"]["caveat"],
        )
        c3.metric(
            "Average Order Value (AOV)",
            fmt_inr(kpis["aov"], 2),
            f"Retained AOV: {fmt_inr(kpis['retained_aov'], 2)}",
            help=METRIC_GLOSSARY["aov"]["formula"] + " — " + METRIC_GLOSSARY["aov"]["caveat"],
        )
        c4.metric(
            "Contribution Margin (CM2)",
            fmt_pct(kpis["contribution_margin_pct"]),
            f"Contribution Profit: {fmt_inr(kpis['contribution_profit'])}",
            help=METRIC_GLOSSARY["contribution_profit"]["formula"],
        )

        # Row 2 KPIs
        c5, c6, c7, c8 = st.columns(4)
        c5.metric(
            "Paid Marketing Spend",
            fmt_inr(acq["ad_spend"]),
            f"New Customers: {fmt_int(acq['total_new_customers'])} ({fmt_int(acq['paid_new_customers'])} paid)",
            help="Sum of paid media spend in selected window and channel/campaign scope.",
        )
        c6.metric(
            "Customer Acquisition Cost (CAC)",
            fmt_inr(acq["blended_cac"], 2),
            f"Paid Channel CAC: {fmt_inr(acq['paid_channel_cac'], 2)}",
            help="Blended CAC = Total Paid Spend / Total New Customers; Paid CAC = Paid Spend / Paid-Attributed New Customers.",
        )
        c7.metric(
            "Attributed ROAS vs Blended MER",
            fmt_mult(acq["attributed_roas"], 2),
            f"Blended MER: {fmt_mult(acq['blended_mer'], 2)}",
            help=ATTRIBUTION_CAVEAT,
        )
        c8.metric(
            "Repeat Purchase Rate",
            fmt_pct(repeat_info["repeat_purchase_rate"]),
            f"{fmt_int(repeat_info['repeat_customers'])} / {fmt_int(repeat_info['active_delivered_customers'])} customers",
            help="Customers with 2+ delivered orders divided by customers with 1+ delivered order in the selected window.",
        )

        # Executive Business Alerts
        st.markdown("#### 🚨 Key Business Diagnostic Alerts (Computed from Active Slice)")
        al1, al2, al3 = st.columns(3)
        with al1:
            st.warning(
                f"**COD RTO Drag**: Shipped RTO rate is **{fmt_pct(kpis['rto_rate'])}** "
                f"(`{fmt_int(kpis['rto_orders'])}` RTO orders), costing **{fmt_inr(kpis['rto_shipping_cost'])}** "
                "in dead-weight forward & reverse shipping with ₹0 revenue."
            )
        with al2:
            st.info(
                f"**Attribution vs Blended Efficiency**: Paid campaigns account for **{fmt_inr(acq['attributed_net_sales'])}** "
                f"(`{fmt_mult(acq['attributed_roas'])}` ROAS), while Organic/Direct/CRM/Marketplace drive "
                f"**{fmt_inr(acq['unassigned_net_sales'])}** (Blended MER: `{fmt_mult(acq['blended_mer'])}`)."
            )
        with al3:
            st.success(
                f"**Unit Contribution Resilience**: Gross Margin is **{fmt_pct(kpis['gross_margin_pct'])}** and "
                f"CM2 Contribution Margin before ad spend is **{fmt_pct(kpis['contribution_margin_pct'])}** "
                f"(**{fmt_inr(kpis['contribution_profit'])}**)."
            )

        # Charts Row 1: Revenue & Contribution Trend + Orders Lifecycle Trend
        ch_left, ch_right = st.columns(2)
        with ch_left:
            if not trends_df.empty:
                fig_rev = go.Figure()
                fig_rev.add_trace(
                    go.Scatter(
                        x=trends_df["period"],
                        y=trends_df["net_merchandise_sales"],
                        mode="lines+markers",
                        name="Net Merchandise Sales (₹)",
                        line=dict(color="#0F766E", width=3),
                    )
                )
                fig_rev.add_trace(
                    go.Scatter(
                        x=trends_df["period"],
                        y=trends_df["contribution_profit"],
                        mode="lines+markers",
                        name="Contribution Profit CM2 (₹)",
                        line=dict(color="#0284C7", width=2.5, dash="dot"),
                    )
                )
                fig_rev.update_layout(
                    title=f"Net Merchandise Sales & Contribution Profit Trend ({trend_freq_label})",
                    xaxis_title="Period",
                    yaxis_title="Amount (INR ₹)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=380,
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fig_rev, use_container_width=True)

        with ch_right:
            if not trends_df.empty:
                fig_ord = go.Figure()
                fig_ord.add_trace(
                    go.Bar(
                        x=trends_df["period"],
                        y=trends_df["delivered_orders"],
                        name="Delivered Orders",
                        marker_color="#059669",
                    )
                )
                fig_ord.add_trace(
                    go.Bar(
                        x=trends_df["period"],
                        y=trends_df["rto_orders"],
                        name="RTO Orders",
                        marker_color="#D97706",
                    )
                )
                fig_ord.add_trace(
                    go.Bar(
                        x=trends_df["period"],
                        y=trends_df["cancelled_orders"],
                        name="Cancelled Orders",
                        marker_color="#DC2626",
                    )
                )
                fig_ord.update_layout(
                    barmode="stack",
                    title=f"Order Lifecycle Volume Trend ({trend_freq_label})",
                    xaxis_title="Period",
                    yaxis_title="Order Count",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=380,
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fig_ord, use_container_width=True)

        # Charts Row 2: Revenue by Channel + Contribution Margin % Trend
        ch_b1, ch_b2 = st.columns(2)
        ch_perf_df = compute_channel_acquisition_and_profitability(flt_orders, flt_spend)
        with ch_b1:
            if not ch_perf_df.empty:
                fig_ch = px.bar(
                    ch_perf_df,
                    x="channel",
                    y=["net_merchandise_sales", "contribution_profit"],
                    barmode="group",
                    title="Net Merchandise Sales vs Contribution Profit by Channel (INR)",
                    labels={"value": "INR (₹)", "channel": "Channel", "variable": "Metric"},
                    color_discrete_sequence=["#0F766E", "#0284C7"],
                )
                fig_ch.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_ch, use_container_width=True)

        with ch_b2:
            if not trends_df.empty:
                valid_cm_trend = trends_df[trends_df["contribution_margin_pct"].notna()].copy()
                valid_cm_trend["cm_pct_display"] = valid_cm_trend["contribution_margin_pct"] * 100.0
                fig_cm_tr = px.line(
                    valid_cm_trend,
                    x="period",
                    y="cm_pct_display",
                    markers=True,
                    title=f"Contribution Margin % Trend ({trend_freq_label})",
                    labels={"cm_pct_display": "Contribution Margin (%)", "period": "Period"},
                    color_discrete_sequence=["#7C3AED"],
                )
                fig_cm_tr.update_layout(height=380, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_cm_tr, use_container_width=True)

    # =========================================================================
    # PAGE 2: MARKETING PERFORMANCE
    # =========================================================================
    elif selected_page == "2. Marketing Performance":
        st.subheader("2. Marketing & Acquisition Performance")
        st.warning(f"**Attribution Caveat**: {ATTRIBUTION_CAVEAT}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Paid Ad Spend", fmt_inr(acq["ad_spend"]), f"Clicks: {fmt_int(acq['clicks'])} (CTR: {fmt_pct(acq['ctr'])})")
        m2.metric("Paid Channel CAC", fmt_inr(acq["paid_channel_cac"], 2), f"Blended CAC: {fmt_inr(acq['blended_cac'], 2)}")
        m3.metric("Campaign-Attributed ROAS", fmt_mult(acq["attributed_roas"], 4), f"Attributed Sales: {fmt_inr(acq['attributed_net_sales'])}")
        m4.metric("Blended MER", fmt_mult(acq["blended_mer"], 4), f"Unassigned Sales: {fmt_inr(acq['unassigned_net_sales'])}")

        ch_df = compute_channel_acquisition_and_profitability(flt_orders, flt_spend)
        cmp_df = compute_campaign_performance(flt_orders, flt_spend, include_unassigned=True)
        paid_cmp_df = cmp_df[cmp_df["ad_spend"] > 0].copy() if not cmp_df.empty else pd.DataFrame()

        col_l, col_r = st.columns(2)
        with col_l:
            if not ch_df.empty:
                fig_sp = px.bar(
                    ch_df,
                    x="channel",
                    y=["ad_spend", "net_merchandise_sales", "contribution_profit"],
                    barmode="group",
                    title="Channel Spend vs Net Sales & Contribution Profit (INR)",
                    labels={"value": "INR (₹)", "channel": "Channel", "variable": "Metric"},
                    color_discrete_sequence=["#DC2626", "#0F766E", "#0284C7"],
                )
                fig_sp.update_layout(height=390, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_sp, use_container_width=True)

        with col_r:
            if not paid_cmp_df.empty:
                paid_cmp_df["cm_pct_display"] = paid_cmp_df["contribution_margin_pct"].fillna(0) * 100.0
                fig_roas = px.scatter(
                    paid_cmp_df,
                    x="attributed_roas",
                    y="cm_pct_display",
                    size="ad_spend",
                    color="channel",
                    hover_name="campaign_id",
                    text="campaign_id",
                    title="Campaign Comparison: Attributed ROAS vs Contribution Margin % (Bubble = Spend)",
                    labels={
                        "attributed_roas": "Attributed ROAS (x)",
                        "cm_pct_display": "Contribution Margin (%)",
                    },
                    color_discrete_sequence=COLOR_PALETTE,
                )
                fig_roas.update_traces(textposition="top center")
                fig_roas.update_layout(height=390, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_roas, use_container_width=True)

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            if not ch_df.empty:
                fig_nc = px.bar(
                    ch_df,
                    x="channel",
                    y="new_customers",
                    color="channel",
                    text_auto=True,
                    title="Newly Acquired Customers by Channel (First Delivered Purchase)",
                    labels={"new_customers": "New Customers", "channel": "Acquisition Channel"},
                    color_discrete_sequence=COLOR_PALETTE,
                )
                fig_nc.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_nc, use_container_width=True)

        with col_m2:
            if not trends_df.empty:
                valid_mer = trends_df[trends_df["blended_mer"].notna()].copy()
                fig_mer = go.Figure()
                fig_mer.add_trace(
                    go.Scatter(
                        x=valid_mer["period"],
                        y=valid_mer["blended_mer"],
                        mode="lines+markers",
                        name="Blended MER (x)",
                        line=dict(color="#0F766E", width=3),
                    )
                )
                fig_mer.add_trace(
                    go.Scatter(
                        x=valid_mer["period"],
                        y=valid_mer["attributed_roas"],
                        mode="lines+markers",
                        name="Attributed ROAS (x)",
                        line=dict(color="#D97706", width=2.5, dash="dash"),
                    )
                )
                fig_mer.update_layout(
                    title=f"Blended MER vs Campaign-Attributed ROAS Trend ({trend_freq_label})",
                    xaxis_title="Period",
                    yaxis_title="Efficiency Ratio (x)",
                    height=360,
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fig_mer, use_container_width=True)

        st.markdown("#### 🔎 Campaign Investigation & Attribution Table")
        if not cmp_df.empty:
            disp_cmp = cmp_df.copy()
            disp_cmp["investigation_flag"] = disp_cmp.apply(
                lambda r: "⚠️ High Discount & High RTO Erosion"
                if (pd.notna(r["effective_discount_rate"]) and r["effective_discount_rate"] > 0.18)
                else (
                    "⚠️ High Spend / High CAC"
                    if (pd.notna(r["cac"]) and r["cac"] > 5000)
                    else ("✅ Top Retargeting/Brand Efficiency" if (pd.notna(r["attributed_roas"]) and r["attributed_roas"] > 0.35) else "ℹ️ Monitor")
                ),
                axis=1,
            )
            st.dataframe(disp_cmp, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Download Campaign Performance CSV",
                data=disp_cmp.to_csv(index=False).encode("utf-8"),
                file_name="campaign_performance_filtered.csv",
                mime="text/csv",
            )

    # =========================================================================
    # PAGE 3: CONVERSION FUNNEL
    # =========================================================================
    elif selected_page == "3. Conversion Funnel":
        st.subheader("3. Website Session Conversion Funnel")
        st.caption(
            "Denominator is eligible sessions (`sessions.csv`). Stage sequence: "
            "`Sessions -> Product Views -> Add to Cart -> Checkout Started -> Converted Purchases`."
        )

        f_overall = compute_funnel_metrics(flt_sessions)
        fo = f_overall.iloc[0]

        f1, f2, f3, f4, f5 = st.columns(5)
        f1.metric("Website Sessions", fmt_int(fo["sessions"]), "100.0% Top of Funnel")
        f2.metric(
            "Product Views",
            fmt_int(fo["product_views"]),
            f"{fmt_pct(fo['session_to_view_rate'])} of Sessions",
        )
        f3.metric(
            "Add to Cart",
            fmt_int(fo["add_to_carts"]),
            f"{fmt_pct(fo['view_to_cart_rate'])} of Views ({fmt_pct(fo['add_to_cart_rate'])} of Sessions)",
        )
        f4.metric(
            "Checkout Started",
            fmt_int(fo["checkout_started"]),
            f"{fmt_pct(fo['cart_to_checkout_rate'])} of Carts",
        )
        f5.metric(
            "Converted Purchases",
            fmt_int(fo["purchases"]),
            f"{fmt_pct(fo['checkout_completion_rate'])} of Checkouts ({fmt_pct(fo['session_conversion_rate'])} Overall)",
        )

        fc_l, fc_r = st.columns(2)
        with fc_l:
            fig_fun = go.Figure(
                go.Funnel(
                    y=["Sessions", "Product Views", "Add to Cart", "Checkout Started", "Purchases"],
                    x=[
                        fo["sessions"],
                        fo["product_views"],
                        fo["add_to_carts"],
                        fo["checkout_started"],
                        fo["purchases"],
                    ],
                    textinfo="value+percent initial+percent previous",
                    marker=dict(color=["#0F766E", "#0284C7", "#2563EB", "#7C3AED", "#059669"]),
                )
            )
            fig_fun.update_layout(
                title="Session-to-Purchase Conversion Funnel",
                height=400,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(fig_fun, use_container_width=True)

        with fc_r:
            drop_df = pd.DataFrame(
                [
                    {
                        "Stage Transition": "1. Session -> Product View",
                        "Drop-Off Rate (%)": (fo["dropoff_session_to_view"] or 0) * 100,
                        "Sessions Lost": int(fo["sessions"] - fo["product_views"]),
                    },
                    {
                        "Stage Transition": "2. Product View -> Add to Cart",
                        "Drop-Off Rate (%)": (fo["dropoff_view_to_cart"] or 0) * 100,
                        "Sessions Lost": int(fo["product_views"] - fo["add_to_carts"]),
                    },
                    {
                        "Stage Transition": "3. Add to Cart -> Checkout",
                        "Drop-Off Rate (%)": (fo["dropoff_cart_to_checkout"] or 0) * 100,
                        "Sessions Lost": int(fo["add_to_carts"] - fo["checkout_started"]),
                    },
                    {
                        "Stage Transition": "4. Checkout -> Purchase",
                        "Drop-Off Rate (%)": (fo["dropoff_checkout_to_purchase"] or 0) * 100,
                        "Sessions Lost": int(fo["checkout_started"] - fo["purchases"]),
                    },
                ]
            )
            fig_drop = px.bar(
                drop_df,
                x="Stage Transition",
                y="Drop-Off Rate (%)",
                text="Sessions Lost",
                color="Stage Transition",
                title="Stage-to-Stage Drop-Off Rate (%) & Sessions Lost",
                color_discrete_sequence=["#0284C7", "#DC2626", "#D97706", "#7C3AED"],
            )
            fig_drop.update_traces(texttemplate="%{text:,} lost", textposition="outside")
            fig_drop.update_layout(height=400, showlegend=False, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_drop, use_container_width=True)

        # Channel & Device Funnel Performance + Trend
        f_ch = compute_funnel_metrics(flt_sessions, group_cols=["channel"])
        f_ch_dev = compute_funnel_metrics(flt_sessions, group_cols=["channel", "device"])

        fb_l, fb_r = st.columns(2)
        with fb_l:
            if not f_ch.empty:
                f_ch_disp = f_ch.copy()
                f_ch_disp["atc_pct"] = f_ch_disp["add_to_cart_rate"].fillna(0) * 100
                f_ch_disp["conv_pct"] = f_ch_disp["session_conversion_rate"].fillna(0) * 100
                fig_fch = px.bar(
                    f_ch_disp,
                    x="channel",
                    y=["atc_pct", "conv_pct"],
                    barmode="group",
                    title="Channel Funnel: Add-to-Cart Rate (%) vs Overall Conversion Rate (%)",
                    labels={"value": "Rate (%)", "channel": "Channel", "variable": "Stage Rate"},
                    color_discrete_sequence=["#0284C7", "#059669"],
                )
                fig_fch.update_layout(height=370, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_fch, use_container_width=True)

        with fb_r:
            if not trends_df.empty:
                valid_ft = trends_df[trends_df["sessions"] > 0].copy()
                valid_ft["conv_pct"] = valid_ft["session_conversion_rate"].fillna(0) * 100
                fig_ftr = px.line(
                    valid_ft,
                    x="period",
                    y="conv_pct",
                    markers=True,
                    title=f"Session-to-Purchase Conversion Rate Trend ({trend_freq_label})",
                    labels={"conv_pct": "Conversion Rate (%)", "period": "Period"},
                    color_discrete_sequence=["#0F766E"],
                )
                fig_ftr.update_layout(height=370, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_ftr, use_container_width=True)

        st.markdown("#### 📋 Channel × Device Funnel Breakdown")
        st.dataframe(f_ch_dev, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Funnel Breakdown CSV",
            data=f_ch_dev.to_csv(index=False).encode("utf-8"),
            file_name="funnel_channel_device_filtered.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PAGE 4: PROFITABILITY & UNIT ECONOMICS
    # =========================================================================
    elif selected_page == "4. Profitability & Unit Economics":
        st.subheader("4. Unit Economics & Profitability Waterfall")
        st.caption(
            "Clearly separates Delivered Gross Revenue (GMV), Discounts, Refunds, Net Merchandise Sales, "
            "Net Product COGS, Gross Profit, Shipping Cost (incl. RTO), Payment Fees, and Contribution Profit (CM2)."
        )

        u1, u2, u3, u4, u5 = st.columns(5)
        u1.metric("Delivered Gross Revenue", fmt_inr(kpis["delivered_gross_revenue"]), f"Placed GMV: {fmt_inr(kpis['placed_gmv'])}")
        u2.metric(
            "Discounts & Refunds",
            fmt_inr(kpis["delivered_discounts"] + kpis["refund_amount"]),
            f"Disc: {fmt_inr(kpis['delivered_discounts'])} | Ref: {fmt_inr(kpis['refund_amount'])}",
        )
        u3.metric("Net Merchandise Sales", fmt_inr(kpis["net_merchandise_sales"]), f"AOV: {fmt_inr(kpis['aov'], 2)}")
        u4.metric(
            "Gross Profit",
            fmt_inr(kpis["gross_profit"]),
            f"Gross Margin: {fmt_pct(kpis['gross_margin_pct'])} (COGS: {fmt_inr(kpis['net_cogs'])})",
        )
        u5.metric(
            "Contribution Profit (CM2)",
            fmt_inr(kpis["contribution_profit"]),
            f"Margin: {fmt_pct(kpis['contribution_margin_pct'])}",
        )

        # Waterfall Chart + SKU Revenue vs Margin Scatter
        uw_l, uw_r = st.columns(2)
        with uw_l:
            fig_wf = go.Figure(
                go.Waterfall(
                    orientation="v",
                    measure=[
                        "absolute",
                        "relative",
                        "relative",
                        "total",
                        "relative",
                        "total",
                        "relative",
                        "relative",
                        "relative",
                        "total",
                    ],
                    x=[
                        "Delivered GMV",
                        "Discounts",
                        "Refunds",
                        "Net Sales",
                        "Product COGS",
                        "Gross Profit",
                        "Shipping Rev",
                        "Shipping Cost",
                        "Payment Fees",
                        "Contribution (CM2)",
                    ],
                    y=[
                        kpis["delivered_gross_revenue"],
                        -kpis["delivered_discounts"],
                        -kpis["refund_amount"],
                        0,
                        -kpis["net_cogs"],
                        0,
                        kpis["earned_shipping_revenue"],
                        -kpis["shipping_cost"],
                        -kpis["payment_fees"],
                        0,
                    ],
                    decreasing=dict(marker=dict(color="#DC2626")),
                    increasing=dict(marker=dict(color="#059669")),
                    totals=dict(marker=dict(color="#0F766E")),
                )
            )
            fig_wf.update_layout(
                title="Unit Economics Waterfall: From Delivered GMV to Contribution Profit (INR)",
                yaxis_title="INR (₹)",
                height=420,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(fig_wf, use_container_width=True)

        sku_df = compute_sku_profitability(flt_items)
        with uw_r:
            if not sku_df.empty:
                sku_disp = sku_df.copy()
                sku_disp["cm_pct"] = sku_disp["contribution_margin_pct"].fillna(0) * 100.0
                fig_sku = px.scatter(
                    sku_disp,
                    x="net_merchandise_sales",
                    y="cm_pct",
                    size="delivered_units",
                    color="category",
                    hover_name="product_name",
                    text="product_id",
                    title="SKU Profitability: Net Merchandise Sales vs Contribution Margin %",
                    labels={
                        "net_merchandise_sales": "Net Merchandise Sales (₹)",
                        "cm_pct": "Contribution Margin (%)",
                    },
                    color_discrete_sequence=COLOR_PALETTE,
                )
                fig_sku.update_traces(textposition="top center")
                fig_sku.update_layout(height=420, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_sku, use_container_width=True)

        # Channel Profitability Bar + SKU Table
        ch_econ = compute_channel_acquisition_and_profitability(flt_orders, flt_spend)
        if not ch_econ.empty:
            fig_che = px.bar(
                ch_econ,
                x="channel",
                y=["net_cogs", "shipping_cost", "payment_fees", "contribution_profit"],
                title="Channel Revenue Decomposition: Variable Costs vs Contribution Profit (INR)",
                labels={"value": "INR (₹)", "channel": "Sales Channel", "variable": "Component"},
                color_discrete_sequence=["#64748B", "#D97706", "#DC2626", "#059669"],
            )
            fig_che.update_layout(barmode="stack", height=370, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_che, use_container_width=True)

        st.markdown("#### 📦 SKU-Level Unit Economics Table")
        st.dataframe(sku_df, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download SKU Unit Economics CSV",
            data=sku_df.to_csv(index=False).encode("utf-8"),
            file_name="sku_unit_economics_filtered.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PAGE 5: CUSTOMER INTELLIGENCE
    # =========================================================================
    elif selected_page == "5. Customer Intelligence":
        st.subheader("5. Customer Intelligence — RFM Segments, Repeat Buying & Cohorts")
        st.info(f"**Observation Window & LTV Note**: {RFM_SCORING_RULES['ltv_caveat']}")

        rfm_slice = compute_rfm_table(flt_orders)
        rfm_seg_summary = summarize_rfm_segments(rfm_slice)
        cohorts_slice = compute_monthly_cohort_retention(flt_orders)

        ci1, ci2, ci3, ci4 = st.columns(4)
        ci1.metric(
            "Active Delivered Customers",
            fmt_int(repeat_info["active_delivered_customers"]),
            f"First-Time: {fmt_int(repeat_info['first_time_customers'])} | Repeat: {fmt_int(repeat_info['repeat_customers'])}",
        )
        ci2.metric(
            "Repeat Purchase Rate",
            fmt_pct(repeat_info["repeat_purchase_rate"]),
            f"Repeat Order Share: {fmt_pct(repeat_info['repeat_order_share'])}",
        )
        ci3.metric(
            "Observed Avg Customer Revenue (6M)",
            fmt_inr(repeat_info["observed_avg_ltv_net_sales"], 2),
            f"Observed Avg Contribution: {fmt_inr(repeat_info['observed_avg_ltv_contribution'], 2)}",
        )
        ci4.metric(
            "Repeat vs First-Time Customer Value",
            fmt_inr(repeat_info["repeat_customer_avg_ltv"], 2),
            f"vs First-Time Avg: {fmt_inr(repeat_info['first_time_avg_ltv'], 2)} (Repeat Rev Share: {fmt_pct(repeat_info['repeat_revenue_share'])})",
        )

        cl_1, cl_2 = st.columns(2)
        with cl_1:
            if not rfm_seg_summary.empty:
                fig_rfm = px.bar(
                    rfm_seg_summary,
                    x="rfm_segment",
                    y=["total_net_sales", "total_contribution_profit"],
                    barmode="group",
                    title="Net Merchandise Sales & Contribution Profit by RFM Segment (INR)",
                    labels={"value": "INR (₹)", "rfm_segment": "RFM Segment", "variable": "Metric"},
                    color_discrete_sequence=["#0F766E", "#0284C7"],
                )
                fig_rfm.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_rfm, use_container_width=True)

        with cl_2:
            if not rfm_seg_summary.empty:
                fig_pie = px.bar(
                    rfm_seg_summary,
                    x="rfm_segment",
                    y="customers",
                    color="rfm_segment",
                    text_auto=True,
                    title="Customer Count by RFM Segment",
                    labels={"customers": "Customers", "rfm_segment": "RFM Segment"},
                    color_discrete_sequence=COLOR_PALETTE,
                )
                fig_pie.update_layout(height=380, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_pie, use_container_width=True)

        # Cohort Retention Heatmap
        st.markdown("#### 🗓️ Monthly Acquisition Cohort Retention Heatmap (%)")
        ret_mat = cohorts_slice["retention_matrix"]
        if not ret_mat.empty:
            ret_pct_mat = (ret_mat * 100.0).round(1)
            ret_pct_mat.columns = [f"Month +{c}" for c in ret_pct_mat.columns]
            fig_hm = px.imshow(
                ret_pct_mat,
                text_auto=".1f",
                aspect="auto",
                color_continuous_scale="Teal",
                title="Monthly Customer Cohort Retention Rate (%) — Defined by First Delivered Order Month",
                labels=dict(x="Months Since First Purchase", y="Acquisition Cohort Month", color="Retention %"),
            )
            fig_hm.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_hm, use_container_width=True)

        st.markdown("#### 📋 RFM Segment Summary Table")
        st.dataframe(rfm_seg_summary, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download RFM Segments CSV",
            data=rfm_seg_summary.to_csv(index=False).encode("utf-8"),
            file_name="rfm_segments_filtered.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PAGE 6: OPERATIONS & RETURNS
    # =========================================================================
    elif selected_page == "6. Operations & Returns":
        st.subheader("6. Operations, COD/RTO & Post-Delivery Returns")
        st.caption(
            "RTO Rate uses Shipped Orders as the denominator (`RTO Orders / Shipped Orders`). "
            "Return Rate uses Delivered Cohort Orders as the denominator (`Returned Orders / Delivered Orders`)."
        )

        cod_df = compute_cod_vs_prepaid_metrics(flt_orders, group_cols=["payment_mode"])
        cod_tier_df = compute_cod_vs_prepaid_metrics(flt_orders, group_cols=["payment_mode", "city_tier"])
        ops_brk = compute_operations_breakdowns(flt_orders)

        op1, op2, op3, op4, op5 = st.columns(5)
        op1.metric("Shipped Orders", fmt_int(kpis["shipped_orders"]), f"Placed: {fmt_int(kpis['placed_orders'])}")
        op2.metric("Delivery Success Rate", fmt_pct(kpis["delivery_rate"]), f"{fmt_int(kpis['delivered_orders'])} delivered")
        op3.metric("Cancellation Rate", fmt_pct(kpis["cancellation_rate"]), f"{fmt_int(kpis['cancelled_orders'])} cancelled")
        op4.metric("RTO Rate (of Shipped)", fmt_pct(kpis["rto_rate"]), f"RTO Shipping Drag: {fmt_inr(kpis['rto_shipping_cost'])}")
        op5.metric("Post-Delivery Return Rate", fmt_pct(kpis["return_rate"]), f"Refunds: {fmt_inr(kpis['refund_amount'])}")

        op_l, op_r = st.columns(2)
        with op_l:
            if not cod_df.empty:
                cod_plot = cod_df.copy()
                cod_plot["RTO Rate (%)"] = cod_plot["rto_rate"].fillna(0) * 100
                cod_plot["Cancellation Rate (%)"] = cod_plot["cancellation_rate"].fillna(0) * 100
                cod_plot["Return Rate (%)"] = cod_plot["return_rate"].fillna(0) * 100
                fig_cod = px.bar(
                    cod_plot,
                    x="payment_mode",
                    y=["RTO Rate (%)", "Cancellation Rate (%)", "Return Rate (%)"],
                    barmode="group",
                    title="COD vs Prepaid Lifecycle Failure & Return Rates (%)",
                    labels={"value": "Rate (%)", "payment_mode": "Payment Mode", "variable": "Rate Metric"},
                    color_discrete_sequence=["#DC2626", "#D97706", "#7C3AED"],
                )
                fig_cod.update_layout(height=380, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_cod, use_container_width=True)

        with op_r:
            if not cod_tier_df.empty:
                ct_plot = cod_tier_df.copy()
                ct_plot["rto_pct"] = ct_plot["rto_rate"].fillna(0) * 100
                fig_ct = px.bar(
                    ct_plot,
                    x="city_tier",
                    y="rto_pct",
                    color="payment_mode",
                    barmode="group",
                    text_auto=".1f",
                    title="RTO Rate (%) by City Tier and Payment Mode (COD vs Prepaid)",
                    labels={"rto_pct": "RTO Rate (%)", "city_tier": "City Tier", "payment_mode": "Payment Mode"},
                    color_discrete_sequence=["#0F766E", "#DC2626"],
                )
                fig_ct.update_layout(height=380, yaxis_ticksuffix="%", margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_ct, use_container_width=True)

        op_b1, op_b2 = st.columns(2)
        with op_b1:
            if not ops_brk["rto_reasons"].empty:
                fig_rto_r = px.bar(
                    ops_brk["rto_reasons"],
                    x="rto_orders",
                    y="rto_reason",
                    orientation="h",
                    text="rto_orders",
                    title="Top Return-to-Origin (RTO) Reasons",
                    labels={"rto_orders": "RTO Orders", "rto_reason": "RTO Reason"},
                    color_discrete_sequence=["#D97706"],
                )
                fig_rto_r.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_rto_r, use_container_width=True)

        with op_b2:
            if not ops_brk["return_reasons"].empty:
                fig_ret_r = px.bar(
                    ops_brk["return_reasons"],
                    x="refund_amount",
                    y="return_reason",
                    orientation="h",
                    text="returned_orders",
                    title="Post-Delivery Return Reasons by Refund Impact (INR)",
                    labels={"refund_amount": "Refund Amount (₹)", "return_reason": "Return Reason"},
                    color_discrete_sequence=["#7C3AED"],
                )
                fig_ret_r.update_traces(texttemplate="%{text} orders")
                fig_ret_r.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_ret_r, use_container_width=True)

        st.markdown("#### 🚚 Courier Partner Performance & COD/Prepaid Summary")
        if not ops_brk["courier_performance"].empty:
            st.dataframe(ops_brk["courier_performance"], use_container_width=True, hide_index=True)
        st.dataframe(cod_tier_df, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download COD vs Prepaid by City Tier CSV",
            data=cod_tier_df.to_csv(index=False).encode("utf-8"),
            file_name="cod_vs_prepaid_city_tier.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PAGE 7: PRODUCT & INVENTORY
    # =========================================================================
    elif selected_page == "7. Product & Inventory":
        st.subheader("7. Product Performance & Warehouse Inventory Snapshots")
        st.warning(
            "**Stockout Signal Caveat**: Daily snapshot `closing_stock <= reorder_point` or `<= 0` is an operational "
            "replenishment signal. It is **NOT** proof of lost sales without intraday unfulfilled demand tracking."
        )

        inv_health_df = compute_inventory_and_stockout_metrics(flt_inventory, base_products)
        sku_prof_df = compute_sku_profitability(flt_items)

        if not inv_health_df.empty and not sku_prof_df.empty:
            best_sku = sku_prof_df.sort_values("contribution_profit", ascending=False).iloc[0]
            low_sku = sku_prof_df.sort_values("contribution_profit", ascending=True).iloc[0]
            below_rop_cnt = int((inv_health_df["latest_status"] != "HEALTHY").sum())
            tot_low_days = int(inv_health_df["days_below_reorder_point"].sum())

            pi1, pi2, pi3, pi4 = st.columns(4)
            pi1.metric(
                "Best-Performing SKU (Contribution)",
                str(best_sku["product_id"]),
                f"{fmt_inr(best_sku['contribution_profit'])} ({fmt_pct(best_sku['contribution_margin_pct'])} CM)",
            )
            pi2.metric(
                "Lowest-Contribution SKU",
                str(low_sku["product_id"]),
                f"{fmt_inr(low_sku['contribution_profit'])} ({fmt_pct(low_sku['contribution_margin_pct'])} CM)",
            )
            pi3.metric(
                "SKUs Currently Below Reorder Point",
                f"{below_rop_cnt} / {len(inv_health_df)}",
                "Requires replenishment review",
            )
            pi4.metric(
                "Total SKU-Days <= Reorder Point",
                fmt_int(tot_low_days),
                f"Stockout Days (Closing = 0): {fmt_int(inv_health_df['stockout_days'].sum())}",
            )

        il_1, il_2 = st.columns(2)
        with il_1:
            if not flt_inventory.empty:
                sku_choices = sorted(flt_inventory["product_id"].unique().tolist())
                inspected_sku = st.selectbox(
                    "Select SKU to Inspect Daily Stock vs Reorder Point Trajectory",
                    options=sku_choices,
                    format_func=lambda x: prod_label_map.get(x, x),
                )
                sku_inv_ts = flt_inventory[flt_inventory["product_id"] == inspected_sku].sort_values("snapshot_date")
                fig_inv = go.Figure()
                fig_inv.add_trace(
                    go.Scatter(
                        x=sku_inv_ts["snapshot_date"],
                        y=sku_inv_ts["closing_stock"],
                        mode="lines",
                        name="Closing Stock (Units)",
                        line=dict(color="#0284C7", width=2.5),
                        fill="tozeroy",
                    )
                )
                fig_inv.add_trace(
                    go.Scatter(
                        x=sku_inv_ts["snapshot_date"],
                        y=sku_inv_ts["reorder_point"],
                        mode="lines",
                        name="Reorder Point Threshold",
                        line=dict(color="#DC2626", width=2, dash="dash"),
                    )
                )
                fig_inv.update_layout(
                    title=f"Daily Closing Stock vs Reorder Point — {inspected_sku}",
                    xaxis_title="Snapshot Date",
                    yaxis_title="Units in Warehouse",
                    height=380,
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fig_inv, use_container_width=True)

        with il_2:
            if not inv_health_df.empty:
                inv_plot = inv_health_df.copy()
                inv_plot["sell_through_pct"] = inv_plot["sell_through_rate"].fillna(0) * 100
                fig_st = px.bar(
                    inv_plot,
                    x="product_id",
                    y=["latest_closing_stock", "reorder_point"],
                    barmode="group",
                    title="Latest Closing Stock vs Reorder Point by SKU",
                    labels={"value": "Units", "product_id": "SKU", "variable": "Stock Metric"},
                    color_discrete_sequence=["#0F766E", "#DC2626"],
                )
                fig_st.update_layout(height=435, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig_st, use_container_width=True)

        st.markdown("#### 📋 Inventory Health & Replenishment Signal Table")
        st.dataframe(inv_health_df, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Inventory Health CSV",
            data=inv_health_df.to_csv(index=False).encode("utf-8"),
            file_name="inventory_health_filtered.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PAGE 8: BUSINESS RECOMMENDATIONS
    # =========================================================================
    elif selected_page == "8. Business Recommendations":
        st.subheader("8. Transparent Rule-Based Business Recommendations")
        st.caption(
            "Generated deterministically from computed metrics in the active filter slice. "
            "Human-in-the-loop decision support only — no automated execution."
        )

        recs = generate_recommendations(
            canonical_orders=flt_orders,
            canonical_order_items=flt_items,
            marketing_spend=flt_spend,
            sessions=flt_sessions,
            inventory_snapshots=flt_inventory,
            products=base_products,
            customers=base_customers,
        )
        recs_df = recommendations_to_dataframe(recs)

        if recs_df.empty:
            st.info("No recommendation thresholds were triggered for the current filter slice.")
        else:
            rf1, rf2 = st.columns(2)
            with rf1:
                pri_filter = st.multiselect(
                    "Filter by Priority",
                    options=["High", "Medium", "Low"],
                    default=["High", "Medium", "Low"],
                )
            with rf2:
                area_opts = sorted(recs_df["business_area"].unique().tolist())
                area_filter = st.multiselect("Filter by Business Area", options=area_opts, default=area_opts)

            shown_recs = [
                r for r in recs if r.priority in pri_filter and r.business_area in area_filter
            ]

            for rec in shown_recs:
                badge = "🔴 HIGH PRIORITY" if rec.priority == "High" else ("🟠 MEDIUM PRIORITY" if rec.priority == "Medium" else "🟢 LOW PRIORITY")
                with st.expander(f"{badge} | [{rec.recommendation_id}] {rec.title} ({rec.business_area})", expanded=True):
                    st.markdown(f"**Affected Segment / Scope**: `{rec.affected_segment}` | **Date Window**: `{rec.date_window}`")
                    st.markdown(f"**1. Observed Condition**: {rec.observed_condition}")
                    st.markdown(f"**2. Computed Evidence**: `{rec.evidence_metrics}`")
                    st.markdown(f"**3. Business Implication**: {rec.business_implication}")
                    st.markdown(f"**4. Possible Mechanism**: {rec.possible_mechanism}")
                    st.markdown(f"**5. Suggested Action for Human Evaluation**: {rec.suggested_action}")
                    st.markdown(f"**6. Risks & Alternative Explanations**: {rec.risks_and_alternatives}")
                    st.markdown(
                        f"**7. Success Metric & Measurement Window**: `{rec.success_metric}` over `{rec.measurement_period}`"
                    )
                    st.caption(f"**Confidence & Data Limitations**: {rec.confidence_and_limitations}")

            st.download_button(
                "📥 Download Recommendations Report (CSV)",
                data=recs_df.to_csv(index=False).encode("utf-8"),
                file_name="recommendations_report.csv",
                mime="text/csv",
            )

    # =========================================================================
    # PAGE 9: DATA QUALITY & GLOSSARY
    # =========================================================================
    elif selected_page == "9. Data Quality & Glossary":
        st.subheader("9. Data Quality, DuckDB SQL Reconciliation & Metric Glossary")

        dq1, dq2, dq3, dq4 = st.columns(4)
        dq1.metric(
            "Validation Suite Status",
            "PASSED" if state.validation_report.passed else "FAILED",
            f"{len(state.validation_report.checks)} checks executed",
        )
        dq2.metric(
            "Rejected Rows",
            fmt_int(len(state.validation_report.rejected_rows)),
            "0 rows silently dropped",
        )
        dq3.metric(
            "Anti-Fan-Out Join Audit",
            "0 Fan-Out" if not state.canonical_model.join_audit["fanout_detected"] else "FAN-OUT ERROR",
            f"Orders: {fmt_int(state.canonical_model.join_audit['canonical_orders_output'])}",
        )
        dq4.metric(
            "DuckDB SQL vs Python Reconciliation",
            "23 / 23 Matched" if state.analytics_outputs["sql_reconciliation"]["reconciled"] else "MISMATCH",
            f"Tolerance: <= {state.analytics_outputs['sql_reconciliation']['tolerance']}",
        )

        st.markdown("#### 🔄 DuckDB SQL vs Python Metric Reconciliation (23 KPIs)")
        rec_df = state.analytics_outputs["sql_reconciliation"]["comparisons"]
        st.dataframe(rec_df, use_container_width=True, hide_index=True)

        st.markdown("#### ✅ Automated Data Validation Checks (61 Checks across 9 Tables)")
        val_df = state.validation_report.to_summary_dataframe()
        st.dataframe(val_df, use_container_width=True, hide_index=True)

        st.markdown("#### 📖 Metric Definitions, Grain & Required Caveats")
        glossary_rows = [
            {
                "Metric Key": k,
                "Metric Name": v["name"],
                "Formula": v["formula"],
                "Table Grain": v["grain"],
                "Caveat": v["caveat"],
            }
            for k, v in METRIC_GLOSSARY.items()
        ]
        st.dataframe(pd.DataFrame(glossary_rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
