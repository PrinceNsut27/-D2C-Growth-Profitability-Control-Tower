"""Core business performance, unit economics, funnel, operations, and inventory metrics.

All functions are pure Python/Pandas, independent of Streamlit, and return None (NA)
for undefined ratios with zero denominators. Includes metric metadata and caveats
for full traceability.
"""

from __future__ import annotations

from typing import Any
import duckdb
import numpy as np
import pandas as pd


def safe_divide(numerator: float | int | None, denominator: float | int | None, round_digits: int = 4) -> float | None:
    """Return numerator / denominator rounded, or None (NA) when denominator is 0 or null."""
    if numerator is None or denominator is None:
        return None
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0.0:
        return None
    return round(float(numerator) / float(denominator), round_digits)


METRIC_GLOSSARY: dict[str, dict[str, str]] = {
    "placed_orders": {
        "name": "Placed Orders",
        "formula": "COUNT(DISTINCT order_id)",
        "grain": "Order header (orders)",
        "caveat": "Operational order volume across all statuses; not completed revenue.",
    },
    "delivered_orders": {
        "name": "Delivered Orders (Cohort)",
        "formula": "COUNT(DISTINCT order_id) WHERE order_status IN ('delivered', 'partially_refunded', 'returned')",
        "grain": "Order header (canonical_orders)",
        "caveat": "Orders that reached physical delivery; excludes cancelled, RTO, and in-transit orders.",
    },
    "retained_delivered_orders": {
        "name": "Retained Delivered Orders",
        "formula": "COUNT(DISTINCT order_id) WHERE order_status IN ('delivered', 'partially_refunded')",
        "grain": "Order header (canonical_orders)",
        "caveat": "Delivered orders excluding full post-delivery returns.",
    },
    "net_merchandise_sales": {
        "name": "Net Merchandise Sales (INR)",
        "formula": "SUM(gross_item_revenue - discount_amount - effective_refund_amount) FOR delivered orders",
        "grain": "Order / Order Line",
        "caveat": "Excludes GST tax and shipping revenue; 0 for cancelled, RTO, and fully returned orders.",
    },
    "aov": {
        "name": "Average Order Value (AOV)",
        "formula": "Net Merchandise Sales / Delivered Orders",
        "grain": "Order header",
        "caveat": "Denominator is eligible delivered cohort orders; returns NA if delivered orders = 0.",
    },
    "gross_profit": {
        "name": "Gross Profit (INR)",
        "formula": "Net Merchandise Sales - Net Retained Product COGS",
        "grain": "Order / SKU",
        "caveat": "Before logistics, payment gateway fees, and marketing spend.",
    },
    "contribution_profit": {
        "name": "Contribution Profit (CM2, INR)",
        "formula": "Net Merchandise Sales + Earned Shipping Revenue - Net COGS - Total Shipping Cost (incl. RTO) - Payment Fees",
        "grain": "Order / SKU / Channel",
        "caveat": "Includes forward and reverse RTO courier costs; before fixed overhead and ad spend (CM2).",
    },
    "contribution_margin_pct": {
        "name": "Contribution Margin %",
        "formula": "Contribution Profit / Net Merchandise Sales",
        "grain": "Order / SKU / Channel",
        "caveat": "Returns NA when Net Merchandise Sales <= 0.",
    },
    "cancellation_rate": {
        "name": "Order Cancellation Rate",
        "formula": "Cancelled Orders / Placed Orders",
        "grain": "Order header",
        "caveat": "Pre-shipment cancellations divided by total placed orders.",
    },
    "rto_rate": {
        "name": "RTO Rate (Return-to-Origin)",
        "formula": "RTO Orders / Shipped Orders",
        "grain": "Shipped orders",
        "caveat": "Divided by shipped orders (never all placed orders).",
    },
    "return_rate": {
        "name": "Post-Delivery Return Rate",
        "formula": "(Returned + Partially Refunded Orders) / Delivered Orders",
        "grain": "Delivered orders",
        "caveat": "Includes both full and partial post-delivery returns.",
    },
    "session_conversion_rate": {
        "name": "Session Conversion Rate",
        "formula": "Converted Sessions / Total Eligible Sessions",
        "grain": "Session (sessions)",
        "caveat": "Session-level denominator, not unique visitor denominator.",
    },
    "sell_through_rate": {
        "name": "Inventory Sell-Through Rate",
        "formula": "Total Units Sold / (Initial Opening Stock + Total Units Received)",
        "grain": "SKU across period (inventory_snapshots)",
        "caveat": "Snapshot-based physical stock turnover.",
    },
}


def filter_canonical_orders(
    canonical_orders: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    channels: list[str] | None = None,
    campaigns: list[str] | None = None,
    payment_modes: list[str] | None = None,
    city_tiers: list[str] | None = None,
) -> pd.DataFrame:
    """Filter canonical_orders by date window and dimension slices."""
    if canonical_orders.empty:
        return canonical_orders.copy()

    df = canonical_orders.copy()
    if start_date:
        df = df[df["order_day"] >= str(start_date)]
    if end_date:
        df = df[df["order_day"] <= str(end_date)]
    if channels:
        df = df[df["channel"].isin(channels)]
    if campaigns:
        df = df[df["campaign_id"].isin(campaigns)]
    if payment_modes:
        df = df[df["payment_mode"].isin(payment_modes)]
    if city_tiers:
        df = df[df["city_tier"].isin(city_tiers)]
    return df.reset_index(drop=True)


def compute_business_performance_And_economics(
    canonical_orders: pd.DataFrame,
) -> dict[str, Any]:
    """Compute executive business performance, order lifecycle, and unit economics KPIs."""
    if canonical_orders.empty:
        return {
            "placed_orders": 0,
            "shipped_orders": 0,
            "delivered_orders": 0,
            "retained_delivered_orders": 0,
            "pure_delivered_orders": 0,
            "cancelled_orders": 0,
            "rto_orders": 0,
            "returned_orders": 0,
            "placed_units": 0,
            "delivered_units": 0,
            "placed_gmv": 0.0,
            "delivered_gross_revenue": 0.0,
            "total_discounts": 0.0,
            "delivered_discounts": 0.0,
            "refund_amount": 0.0,
            "net_merchandise_sales": 0.0,
            "earned_shipping_revenue": 0.0,
            "net_cogs": 0.0,
            "gross_profit": 0.0,
            "gross_margin_pct": None,
            "shipping_cost": 0.0,
            "rto_shipping_cost": 0.0,
            "payment_fees": 0.0,
            "contribution_profit": 0.0,
            "contribution_margin_pct": None,
            "aov": None,
            "retained_aov": None,
            "cancellation_rate": None,
            "rto_rate": None,
            "delivery_rate": None,
            "return_rate": None,
        }

    df = canonical_orders
    placed_orders = int(df["order_id"].nunique())
    shipped_mask = df["is_shipped"].astype(bool)
    deliv_mask = df["is_delivered"].astype(bool)
    ret_deliv_mask = df["is_retained_delivered"].astype(bool)
    pure_deliv_mask = df["order_status"] == "delivered"
    cancel_mask = df["is_cancelled"].astype(bool)
    rto_mask = df["is_rto"].astype(bool)
    returned_mask = df["is_returned_any"].astype(bool)

    shipped_orders = int(df.loc[shipped_mask, "order_id"].nunique())
    delivered_orders = int(df.loc[deliv_mask, "order_id"].nunique())
    retained_delivered_orders = int(df.loc[ret_deliv_mask, "order_id"].nunique())
    pure_delivered_orders = int(df.loc[pure_deliv_mask, "order_id"].nunique())
    cancelled_orders = int(df.loc[cancel_mask, "order_id"].nunique())
    rto_orders = int(df.loc[rto_mask, "order_id"].nunique())
    returned_orders = int(df.loc[returned_mask, "order_id"].nunique())

    placed_units = int(df["total_units"].sum())
    delivered_units = int(df.loc[deliv_mask, "total_units"].sum())

    placed_gmv = round(float(df["gross_item_revenue"].sum()), 2)
    delivered_gross_revenue = round(float(df.loc[deliv_mask, "gross_item_revenue"].sum()), 2)
    total_discounts = round(float(df["discount_amount"].sum()), 2)
    delivered_discounts = round(float(df.loc[deliv_mask, "discount_amount"].sum()), 2)
    refund_amount = round(float(df.loc[deliv_mask, "effective_refund_amount"].sum()), 2)
    net_merchandise_sales = round(float(df["net_merchandise_sales"].sum()), 2)
    earned_shipping_revenue = round(float(df["earned_shipping_revenue"].sum()), 2)

    net_cogs = round(float(df["net_cogs"].sum()), 2)
    gross_profit = round(net_merchandise_sales - net_cogs, 2)
    gross_margin_pct = safe_divide(gross_profit, net_merchandise_sales, 4) if net_merchandise_sales > 0 else None

    shipping_cost = round(float(df["shipping_cost"].sum()), 2)
    rto_shipping_cost = round(float(df.loc[rto_mask, "shipping_cost"].sum()), 2)
    payment_fees = round(float(df["payment_fee"].sum()), 2)
    contribution_profit = round(float(df["contribution_profit"].sum()), 2)
    contribution_margin_pct = (
        safe_divide(contribution_profit, net_merchandise_sales, 4) if net_merchandise_sales > 0 else None
    )

    aov = safe_divide(net_merchandise_sales, delivered_orders, 2)
    retained_aov = safe_divide(net_merchandise_sales, retained_delivered_orders, 2)
    cancellation_rate = safe_divide(cancelled_orders, placed_orders, 4)
    rto_rate = safe_divide(rto_orders, shipped_orders, 4)
    delivery_rate = safe_divide(delivered_orders, shipped_orders, 4)
    return_rate = safe_divide(returned_orders, delivered_orders, 4)

    return {
        "placed_orders": placed_orders,
        "shipped_orders": shipped_orders,
        "delivered_orders": delivered_orders,
        "retained_delivered_orders": retained_delivered_orders,
        "pure_delivered_orders": pure_delivered_orders,
        "cancelled_orders": cancelled_orders,
        "rto_orders": rto_orders,
        "returned_orders": returned_orders,
        "placed_units": placed_units,
        "delivered_units": delivered_units,
        "placed_gmv": placed_gmv,
        "delivered_gross_revenue": delivered_gross_revenue,
        "total_discounts": total_discounts,
        "delivered_discounts": delivered_discounts,
        "refund_amount": refund_amount,
        "net_merchandise_sales": net_merchandise_sales,
        "earned_shipping_revenue": earned_shipping_revenue,
        "net_cogs": net_cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "shipping_cost": shipping_cost,
        "rto_shipping_cost": rto_shipping_cost,
        "payment_fees": payment_fees,
        "contribution_profit": contribution_profit,
        "contribution_margin_pct": contribution_margin_pct,
        "aov": aov,
        "retained_aov": retained_aov,
        "cancellation_rate": cancellation_rate,
        "rto_rate": rto_rate,
        "delivery_rate": delivery_rate,
        "return_rate": return_rate,
    }


def compute_unit_economics_by_dimension(
    canonical_orders: pd.DataFrame,
    group_col: str = "channel",
) -> pd.DataFrame:
    """Compute revenue, gross profit, variable costs, and contribution margin grouped by a dimension."""
    if canonical_orders.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for dim_val, grp in canonical_orders.groupby(group_col, dropna=False):
        label = str(dim_val) if str(dim_val).strip() != "" else "Unassigned / Direct"
        kpis = compute_business_performance_And_economics(grp)
        kpis[group_col] = label
        rows.append(kpis)

    out = pd.DataFrame(rows)
    cols = [group_col] + [c for c in out.columns if c != group_col]
    return out[cols].sort_values("net_merchandise_sales", ascending=False).reset_index(drop=True)


def compute_sku_profitability(
    canonical_order_items: pd.DataFrame,
) -> pd.DataFrame:
    """Compute SKU-level revenue, discounts, refunds, COGS, gross profit, and contribution margin."""
    if canonical_order_items.empty:
        return pd.DataFrame(
            columns=[
                "product_id",
                "product_name",
                "category",
                "orders_count",
                "delivered_orders_count",
                "placed_units",
                "delivered_units",
                "gross_merchandise_value",
                "delivered_gross_revenue",
                "delivered_discounts",
                "refund_amount",
                "net_merchandise_sales",
                "net_cogs",
                "gross_profit",
                "gross_margin_pct",
                "allocated_shipping_revenue",
                "allocated_shipping_cost",
                "allocated_payment_fee",
                "contribution_profit",
                "contribution_margin_pct",
                "return_incidence_rate",
            ]
        )

    df = canonical_order_items.copy()
    rows: list[dict[str, Any]] = []

    for (pid, pname, cat), grp in df.groupby(["product_id", "product_name", "category"], as_index=False):
        deliv = grp[grp["is_delivered"].astype(bool)]
        orders_cnt = int(grp["order_id"].nunique())
        deliv_orders_cnt = int(deliv["order_id"].nunique())
        placed_u = int(grp["quantity"].sum())
        deliv_u = int(deliv["quantity"].sum())

        gmv_all = round(float(grp["gross_line_revenue"].sum()), 2)
        deliv_gmv = round(float(deliv["gross_line_revenue"].sum()), 2)
        deliv_disc = round(float(deliv["line_discount_amount"].sum()), 2)
        ref_amt = round(float(deliv["line_refund_amount"].sum()), 2)
        net_sales = round(float(grp["line_net_merchandise_sales"].sum()), 2)
        net_cogs = round(float(grp["line_net_cogs"].sum()), 2)
        gross_prof = round(net_sales - net_cogs, 2)
        gross_margin = safe_divide(gross_prof, net_sales, 4) if net_sales > 0 else None

        alloc_ship_rev = round(float(grp["allocated_shipping_revenue"].sum()), 2)
        alloc_ship_cost = round(float(grp["allocated_shipping_cost"].sum()), 2)
        alloc_pay_fee = round(float(grp["allocated_payment_fee"].sum()), 2)
        contrib = round(float(grp["line_contribution_profit"].sum()), 2)
        contrib_margin = safe_divide(contrib, net_sales, 4) if net_sales > 0 else None

        ret_lines = int((deliv["line_refund_amount"] > 0).sum())
        deliv_lines = len(deliv)
        ret_rate = safe_divide(ret_lines, deliv_lines, 4)

        rows.append(
            {
                "product_id": str(pid),
                "product_name": str(pname),
                "category": str(cat),
                "orders_count": orders_cnt,
                "delivered_orders_count": deliv_orders_cnt,
                "placed_units": placed_u,
                "delivered_units": deliv_u,
                "gross_merchandise_value": gmv_all,
                "delivered_gross_revenue": deliv_gmv,
                "delivered_discounts": deliv_disc,
                "refund_amount": ref_amt,
                "net_merchandise_sales": net_sales,
                "net_cogs": net_cogs,
                "gross_profit": gross_prof,
                "gross_margin_pct": gross_margin,
                "allocated_shipping_revenue": alloc_ship_rev,
                "allocated_shipping_cost": alloc_ship_cost,
                "allocated_payment_fee": alloc_pay_fee,
                "contribution_profit": contrib,
                "contribution_margin_pct": contrib_margin,
                "return_incidence_rate": ret_rate,
            }
        )

    return pd.DataFrame(rows).sort_values("net_merchandise_sales", ascending=False).reset_index(drop=True)


def compute_funnel_metrics(
    sessions: pd.DataFrame,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Compute session conversion funnel volumes, stage-to-stage rates, and drop-off rates."""
    cols_out = (group_cols or []) + [
        "sessions",
        "product_views",
        "add_to_carts",
        "checkout_started",
        "purchases",
        "session_to_view_rate",
        "view_to_cart_rate",
        "add_to_cart_rate",
        "cart_to_checkout_rate",
        "checkout_completion_rate",
        "session_conversion_rate",
        "dropoff_session_to_view",
        "dropoff_view_to_cart",
        "dropoff_cart_to_checkout",
        "dropoff_checkout_to_purchase",
    ]
    if sessions.empty:
        if not group_cols:
            return pd.DataFrame(
                [
                    {
                        "sessions": 0,
                        "product_views": 0,
                        "add_to_carts": 0,
                        "checkout_started": 0,
                        "purchases": 0,
                        "session_to_view_rate": None,
                        "view_to_cart_rate": None,
                        "add_to_cart_rate": None,
                        "cart_to_checkout_rate": None,
                        "checkout_completion_rate": None,
                        "session_conversion_rate": None,
                        "dropoff_session_to_view": None,
                        "dropoff_view_to_cart": None,
                        "dropoff_cart_to_checkout": None,
                        "dropoff_checkout_to_purchase": None,
                    }
                ]
            )
        return pd.DataFrame(columns=cols_out)

    df = sessions.copy()
    for gc in group_cols or []:
        df[gc] = df[gc].fillna("").astype(str).replace("", "Unassigned / Direct")

    groups = [((), df)] if not group_cols else list(df.groupby(group_cols, dropna=False))
    rows: list[dict[str, Any]] = []

    for g_key, grp in groups:
        rec: dict[str, Any] = {}
        if group_cols:
            if len(group_cols) == 1:
                rec[group_cols[0]] = g_key if not isinstance(g_key, tuple) else g_key[0]
            else:
                for k_name, k_val in zip(group_cols, g_key):
                    rec[k_name] = k_val

        n_sess = int(grp["session_id"].nunique())
        n_pv = int(grp["product_view"].astype(bool).sum())
        n_atc = int(grp["add_to_cart"].astype(bool).sum())
        n_chk = int(grp["checkout_started"].astype(bool).sum())
        n_conv = int(grp["converted"].astype(bool).sum())

        s2v = safe_divide(n_pv, n_sess, 4)
        v2c = safe_divide(n_atc, n_pv, 4)
        atc_rate = safe_divide(n_atc, n_sess, 4)
        c2chk = safe_divide(n_chk, n_atc, 4)
        chk2p = safe_divide(n_conv, n_chk, 4)
        conv_rate = safe_divide(n_conv, n_sess, 4)

        rec.update(
            {
                "sessions": n_sess,
                "product_views": n_pv,
                "add_to_carts": n_atc,
                "checkout_started": n_chk,
                "purchases": n_conv,
                "session_to_view_rate": s2v,
                "view_to_cart_rate": v2c,
                "add_to_cart_rate": atc_rate,
                "cart_to_checkout_rate": c2chk,
                "checkout_completion_rate": chk2p,
                "session_conversion_rate": conv_rate,
                "dropoff_session_to_view": round(1.0 - s2v, 4) if s2v is not None else None,
                "dropoff_view_to_cart": round(1.0 - v2c, 4) if v2c is not None else None,
                "dropoff_cart_to_checkout": round(1.0 - c2chk, 4) if c2chk is not None else None,
                "dropoff_checkout_to_purchase": round(1.0 - chk2p, 4) if chk2p is not None else None,
            }
        )
        rows.append(rec)

    out = pd.DataFrame(rows)
    return out.sort_values("sessions", ascending=False).reset_index(drop=True)


def compute_cod_vs_prepaid_metrics(
    canonical_orders: pd.DataFrame,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Compare COD and Prepaid delivery, cancellation, RTO, return, and contribution outcomes."""
    g_cols = group_cols if group_cols is not None else ["payment_mode"]
    if canonical_orders.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for g_key, grp in canonical_orders.groupby(g_cols, dropna=False):
        rec: dict[str, Any] = {}
        if len(g_cols) == 1:
            rec[g_cols[0]] = g_key if not isinstance(g_key, tuple) else g_key[0]
        else:
            for col_name, val in zip(g_cols, g_key):
                rec[col_name] = val
        rec.update(compute_business_performance_And_economics(grp))
        rows.append(rec)

    return pd.DataFrame(rows).sort_values("placed_orders", ascending=False).reset_index(drop=True)


def compute_inventory_and_stockout_metrics(
    inventory_snapshots: pd.DataFrame,
    products: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Analyze SKU stock movements, sell-through rates, low-stock days, and stockout signals.

    Caveat: Snapshot closing_stock <= 0 or <= reorder_point is a stockout/reorder signal,
    NOT proof of lost sales without intraday unfulfilled demand records.
    """
    if inventory_snapshots.empty:
        return pd.DataFrame(
            columns=[
                "product_id",
                "product_name",
                "category",
                "snapshot_days",
                "initial_opening_stock",
                "total_units_received",
                "total_units_sold",
                "latest_closing_stock",
                "reorder_point",
                "sell_through_rate",
                "days_below_reorder_point",
                "stockout_days",
                "pct_days_below_rop",
                "latest_status",
            ]
        )

    inv = inventory_snapshots.copy().sort_values(["product_id", "snapshot_date"])
    rows: list[dict[str, Any]] = []

    for pid, grp in inv.groupby("product_id", as_index=False):
        n_days = len(grp)
        init_open = int(grp.iloc[0]["opening_stock"])
        tot_rec = int(grp["units_received"].sum())
        tot_sold = int(grp["units_sold"].sum())
        latest_close = int(grp.iloc[-1]["closing_stock"])
        rop = int(grp.iloc[-1]["reorder_point"])

        available_pool = init_open + tot_rec
        sell_through = safe_divide(tot_sold, available_pool, 4)

        below_rop_days = int((grp["closing_stock"] <= grp["reorder_point"]).sum())
        stockout_days = int((grp["closing_stock"] <= 0).sum())
        pct_below_rop = safe_divide(below_rop_days, n_days, 4)

        if latest_close <= 0:
            status = "STOCKOUT_SIGNAL"
        elif latest_close <= rop:
            status = "BELOW_REORDER_POINT"
        else:
            status = "HEALTHY"

        rows.append(
            {
                "product_id": str(pid),
                "snapshot_days": n_days,
                "initial_opening_stock": init_open,
                "total_units_received": tot_rec,
                "total_units_sold": tot_sold,
                "latest_closing_stock": latest_close,
                "reorder_point": rop,
                "sell_through_rate": sell_through,
                "days_below_reorder_point": below_rop_days,
                "stockout_days": stockout_days,
                "pct_days_below_rop": pct_below_rop,
                "latest_status": status,
            }
        )

    out = pd.DataFrame(rows)
    if products is not None and not products.empty:
        out = products[["product_id", "product_name", "category"]].merge(out, on="product_id", how="right")
    return out.sort_values(["days_below_reorder_point", "total_units_sold"], ascending=[False, False]).reset_index(
        drop=True
    )


def reconcile_sql_and_python_metrics(
    db_path: str,
    canonical_orders: pd.DataFrame,
    marketing_spend: pd.DataFrame,
    sessions: pd.DataFrame,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """Execute SQL KPI queries in DuckDB and reconcile against Python metric calculations."""
    py_perf = compute_business_performance_And_economics(canonical_orders)
    py_funnel = compute_funnel_metrics(sessions).iloc[0].to_dict()
    py_spend = round(float(marketing_spend["spend"].sum()), 2) if not marketing_spend.empty else 0.0
    py_mer = safe_divide(py_perf["net_merchandise_sales"], py_spend, 4)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        sql_orders_row = con.execute(
            """
            SELECT
                COUNT(DISTINCT order_id) AS placed_orders,
                COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) AS shipped_orders,
                COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) AS delivered_orders,
                COUNT(DISTINCT CASE WHEN is_retained_delivered THEN order_id END) AS retained_delivered_orders,
                COUNT(DISTINCT CASE WHEN is_cancelled THEN order_id END) AS cancelled_orders,
                COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS rto_orders,
                COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS returned_orders,
                COALESCE(ROUND(SUM(gross_item_revenue), 2), 0.0) AS placed_gmv,
                COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN gross_item_revenue ELSE 0 END), 2), 0.0) AS delivered_gross_revenue,
                COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN discount_amount ELSE 0 END), 2), 0.0) AS delivered_discounts,
                COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN effective_refund_amount ELSE 0 END), 2), 0.0) AS refund_amount,
                COALESCE(ROUND(SUM(net_merchandise_sales), 2), 0.0) AS net_merchandise_sales,
                COALESCE(ROUND(SUM(net_cogs), 2), 0.0) AS net_cogs,
                COALESCE(ROUND(SUM(net_merchandise_sales - net_cogs), 2), 0.0) AS gross_profit,
                COALESCE(ROUND(SUM(shipping_cost), 2), 0.0) AS shipping_cost,
                COALESCE(ROUND(SUM(payment_fee), 2), 0.0) AS payment_fees,
                COALESCE(ROUND(SUM(contribution_profit), 2), 0.0) AS contribution_profit,
                CASE WHEN COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) > 0
                     THEN ROUND(SUM(net_merchandise_sales) / COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END), 2)
                     ELSE NULL END AS aov,
                CASE WHEN COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) > 0
                     THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS DOUBLE)
                          / COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END), 4)
                     ELSE NULL END AS rto_rate,
                CASE WHEN COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) > 0
                     THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS DOUBLE)
                          / COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END), 4)
                     ELSE NULL END AS return_rate
            FROM canonical_orders
            """
        ).fetchdf().iloc[0].to_dict()

        sql_spend_val = con.execute("SELECT COALESCE(ROUND(SUM(spend), 2), 0.0) FROM marketing_spend").fetchone()[0]
        sql_spend = float(sql_spend_val)
        sql_mer = safe_divide(float(sql_orders_row["net_merchandise_sales"]), sql_spend, 4)

        sql_funnel_row = con.execute(
            """
            SELECT
                COUNT(DISTINCT session_id) AS sessions,
                SUM(CASE WHEN product_view THEN 1 ELSE 0 END) AS product_views,
                SUM(CASE WHEN add_to_cart THEN 1 ELSE 0 END) AS add_to_carts,
                SUM(CASE WHEN checkout_started THEN 1 ELSE 0 END) AS checkout_started,
                SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS purchases
            FROM sessions
            """
        ).fetchdf().iloc[0].to_dict()
    finally:
        con.close()

    comparisons: list[dict[str, Any]] = []
    metric_pairs = [
        ("placed_orders", py_perf["placed_orders"], sql_orders_row["placed_orders"]),
        ("shipped_orders", py_perf["shipped_orders"], sql_orders_row["shipped_orders"]),
        ("delivered_orders", py_perf["delivered_orders"], sql_orders_row["delivered_orders"]),
        ("cancelled_orders", py_perf["cancelled_orders"], sql_orders_row["cancelled_orders"]),
        ("rto_orders", py_perf["rto_orders"], sql_orders_row["rto_orders"]),
        ("returned_orders", py_perf["returned_orders"], sql_orders_row["returned_orders"]),
        ("placed_gmv", py_perf["placed_gmv"], sql_orders_row["placed_gmv"]),
        ("delivered_gross_revenue", py_perf["delivered_gross_revenue"], sql_orders_row["delivered_gross_revenue"]),
        ("delivered_discounts", py_perf["delivered_discounts"], sql_orders_row["delivered_discounts"]),
        ("refund_amount", py_perf["refund_amount"], sql_orders_row["refund_amount"]),
        ("net_merchandise_sales", py_perf["net_merchandise_sales"], sql_orders_row["net_merchandise_sales"]),
        ("net_cogs", py_perf["net_cogs"], sql_orders_row["net_cogs"]),
        ("gross_profit", py_perf["gross_profit"], sql_orders_row["gross_profit"]),
        ("shipping_cost", py_perf["shipping_cost"], sql_orders_row["shipping_cost"]),
        ("payment_fees", py_perf["payment_fees"], sql_orders_row["payment_fees"]),
        ("contribution_profit", py_perf["contribution_profit"], sql_orders_row["contribution_profit"]),
        ("aov", py_perf["aov"], sql_orders_row["aov"]),
        ("rto_rate", py_perf["rto_rate"], sql_orders_row["rto_rate"]),
        ("return_rate", py_perf["return_rate"], sql_orders_row["return_rate"]),
        ("ad_spend", py_spend, sql_spend),
        ("blended_mer", py_mer, sql_mer),
        ("sessions", py_funnel["sessions"], sql_funnel_row["sessions"]),
        ("purchases", py_funnel["purchases"], sql_funnel_row["purchases"]),
    ]

    all_reconciled = True
    for m_name, py_val, sql_val in metric_pairs:
        if py_val is None and (sql_val is None or pd.isna(sql_val)):
            diff = 0.0
            matched = True
        elif py_val is None or sql_val is None or pd.isna(sql_val):
            diff = None
            matched = False
        else:
            diff = round(abs(float(py_val) - float(sql_val)), 6)
            matched = diff <= tolerance
        if not matched:
            all_reconciled = False
        comparisons.append(
            {
                "metric": m_name,
                "python_value": py_val,
                "sql_value": float(sql_val) if sql_val is not None and not pd.isna(sql_val) else None,
                "abs_diff": diff,
                "reconciled": matched,
            }
        )

    return {
        "reconciled": all_reconciled,
        "tolerance": tolerance,
        "comparisons": pd.DataFrame(comparisons),
    }


def apply_global_filters(
    canonical_orders: pd.DataFrame,
    canonical_order_items: pd.DataFrame,
    marketing_spend: pd.DataFrame,
    sessions: pd.DataFrame,
    inventory_snapshots: pd.DataFrame,
    rfm_table: pd.DataFrame | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    channels: list[str] | None = None,
    campaigns: list[str] | None = None,
    product_ids: list[str] | None = None,
    rfm_segments: list[str] | None = None,
    payment_modes: list[str] | None = None,
    city_tiers: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Filter all canonical and source analytical tables consistently across global filter selections."""
    can_orders = canonical_orders.copy()
    can_items = canonical_order_items.copy()
    spend = marketing_spend.copy()
    sess = sessions.copy()
    inv = inventory_snapshots.copy()

    # Date filter
    if start_date:
        s_str = str(start_date)
        if not can_orders.empty:
            can_orders = can_orders[can_orders["order_day"] >= s_str]
        if not can_items.empty:
            can_items = can_items[can_items["order_day"] >= s_str]
        if not spend.empty:
            dcol = "date" if "date" in spend.columns else "spend_date"
            spend = spend[spend[dcol].astype(str) >= s_str]
        if not sess.empty:
            sess_day = sess["session_start"].astype(str).str.slice(0, 10)
            sess = sess[sess_day >= s_str]
        if not inv.empty:
            inv = inv[inv["snapshot_date"].astype(str) >= s_str]

    if end_date:
        e_str = str(end_date)
        if not can_orders.empty:
            can_orders = can_orders[can_orders["order_day"] <= e_str]
        if not can_items.empty:
            can_items = can_items[can_items["order_day"] <= e_str]
        if not spend.empty:
            dcol = "date" if "date" in spend.columns else "spend_date"
            spend = spend[spend[dcol].astype(str) <= e_str]
        if not sess.empty:
            sess_day = sess["session_start"].astype(str).str.slice(0, 10)
            sess = sess[sess_day <= e_str]
        if not inv.empty:
            inv = inv[inv["snapshot_date"].astype(str) <= e_str]

    # Channel filter
    if channels:
        if not can_orders.empty:
            can_orders = can_orders[can_orders["channel"].isin(channels)]
        if not spend.empty:
            spend = spend[spend["channel"].isin(channels)]
        if not sess.empty:
            sess = sess[sess["channel"].isin(channels)]

    # Campaign filter
    if campaigns:
        norm_cmps = ["" if c == "UNASSIGNED" else c for c in campaigns]
        if not can_orders.empty:
            can_orders = can_orders[can_orders["campaign_id"].fillna("").isin(norm_cmps)]
        if not spend.empty:
            spend = spend[spend["campaign_id"].fillna("").isin(norm_cmps)]
        if not sess.empty:
            sess = sess[sess["campaign_id"].fillna("").isin(norm_cmps)]

    # Payment mode filter
    if payment_modes:
        if not can_orders.empty:
            can_orders = can_orders[can_orders["payment_mode"].isin(payment_modes)]

    # City tier filter
    if city_tiers:
        if not can_orders.empty:
            can_orders = can_orders[can_orders["city_tier"].isin(city_tiers)]

    # Customer RFM segment filter
    if rfm_segments and rfm_table is not None and not rfm_table.empty:
        seg_cust_ids = set(
            rfm_table.loc[rfm_table["rfm_segment"].isin(rfm_segments), "customer_id"].astype(str)
        )
        if not can_orders.empty:
            can_orders = can_orders[can_orders["customer_id"].astype(str).isin(seg_cust_ids)]

    # Product / SKU filter
    if product_ids:
        if not can_items.empty:
            can_items = can_items[can_items["product_id"].isin(product_ids)]
        if not inv.empty:
            inv = inv[inv["product_id"].isin(product_ids)]
        if not can_orders.empty:
            valid_ord_ids_from_sku = set(can_items["order_id"].astype(str))
            can_orders = can_orders[can_orders["order_id"].astype(str).isin(valid_ord_ids_from_sku)]

    # Keep canonical_order_items aligned with surviving canonical_orders
    if not can_items.empty:
        surviving_ord_ids = set(can_orders["order_id"].astype(str)) if not can_orders.empty else set()
        can_items = can_items[can_items["order_id"].astype(str).isin(surviving_ord_ids)]

    return {
        "canonical_orders": can_orders.reset_index(drop=True),
        "canonical_order_items": can_items.reset_index(drop=True),
        "marketing_spend": spend.reset_index(drop=True),
        "sessions": sess.reset_index(drop=True),
        "inventory_snapshots": inv.reset_index(drop=True),
    }


def compute_time_series_trends(
    canonical_orders: pd.DataFrame,
    marketing_spend: pd.DataFrame,
    sessions: pd.DataFrame,
    freq: str = "W-MON",
) -> pd.DataFrame:
    """Compute periodic (daily/weekly/monthly) trends for orders, revenue, contribution, spend, MER, and funnel."""
    if canonical_orders.empty and marketing_spend.empty and sessions.empty:
        return pd.DataFrame(
            columns=[
                "period",
                "placed_orders",
                "delivered_orders",
                "rto_orders",
                "cancelled_orders",
                "net_merchandise_sales",
                "contribution_profit",
                "contribution_margin_pct",
                "aov",
                "ad_spend",
                "attributed_net_sales",
                "attributed_roas",
                "blended_mer",
                "sessions",
                "product_views",
                "add_to_carts",
                "checkout_started",
                "purchases",
                "session_conversion_rate",
            ]
        )

    def _to_period_str(date_series: pd.Series) -> pd.Series:
        dt = pd.to_datetime(date_series)
        if freq == "D":
            return dt.dt.strftime("%Y-%m-%d")
        if freq == "M":
            return dt.dt.strftime("%Y-%m")
        # Weekly bucket (week start Monday)
        return dt.dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")

    # Orders aggregation by period
    if not canonical_orders.empty:
        ord_df = canonical_orders.copy()
        ord_df["period"] = _to_period_str(ord_df["order_day"])
        has_cmp = ord_df["campaign_id"].fillna("").astype(str).str.strip() != ""
        ord_df["attributed_sales_row"] = np.where(has_cmp, ord_df["net_merchandise_sales"], 0.0)

        ord_grp = (
            ord_df.groupby("period", as_index=False)
            .agg(
                placed_orders=("order_id", "nunique"),
                shipped_orders=("is_shipped", lambda s: int(s.astype(bool).sum())),
                delivered_orders=("is_delivered", lambda s: int(s.astype(bool).sum())),
                rto_orders=("is_rto", lambda s: int(s.astype(bool).sum())),
                cancelled_orders=("is_cancelled", lambda s: int(s.astype(bool).sum())),
                net_merchandise_sales=("net_merchandise_sales", "sum"),
                contribution_profit=("contribution_profit", "sum"),
                attributed_net_sales=("attributed_sales_row", "sum"),
            )
        )
    else:
        ord_grp = pd.DataFrame(
            columns=[
                "period",
                "placed_orders",
                "shipped_orders",
                "delivered_orders",
                "rto_orders",
                "cancelled_orders",
                "net_merchandise_sales",
                "contribution_profit",
                "attributed_net_sales",
            ]
        )

    # Spend aggregation by period
    if not marketing_spend.empty:
        sp_df = marketing_spend.copy()
        dcol = "date" if "date" in sp_df.columns else "spend_date"
        sp_df["period"] = _to_period_str(sp_df[dcol])
        sp_grp = sp_df.groupby("period", as_index=False).agg(ad_spend=("spend", "sum"))
    else:
        sp_grp = pd.DataFrame(columns=["period", "ad_spend"])

    # Sessions aggregation by period
    if not sessions.empty:
        s_df = sessions.copy()
        s_df["period"] = _to_period_str(s_df["session_start"].astype(str).str.slice(0, 10))
        s_grp = (
            s_df.groupby("period", as_index=False)
            .agg(
                sessions=("session_id", "nunique"),
                product_views=("product_view", lambda s: int(s.astype(bool).sum())),
                add_to_carts=("add_to_cart", lambda s: int(s.astype(bool).sum())),
                checkout_started=("checkout_started", lambda s: int(s.astype(bool).sum())),
                purchases=("converted", lambda s: int(s.astype(bool).sum())),
            )
        )
    else:
        s_grp = pd.DataFrame(
            columns=["period", "sessions", "product_views", "add_to_carts", "checkout_started", "purchases"]
        )

    merged = ord_grp.merge(sp_grp, on="period", how="outer").merge(s_grp, on="period", how="outer")
    merged = merged.sort_values("period").reset_index(drop=True)

    for int_col in (
        "placed_orders",
        "shipped_orders",
        "delivered_orders",
        "rto_orders",
        "cancelled_orders",
        "sessions",
        "product_views",
        "add_to_carts",
        "checkout_started",
        "purchases",
    ):
        if int_col in merged.columns:
            merged[int_col] = merged[int_col].fillna(0).astype(int)

    for flt_col in ("net_merchandise_sales", "contribution_profit", "attributed_net_sales", "ad_spend"):
        if flt_col in merged.columns:
            merged[flt_col] = merged[flt_col].fillna(0.0).round(2)

    merged["contribution_margin_pct"] = [
        safe_divide(cp, ns, 4) if ns > 0 else None
        for cp, ns in zip(merged["contribution_profit"], merged["net_merchandise_sales"])
    ]
    merged["aov"] = [
        safe_divide(ns, do, 2)
        for ns, do in zip(merged["net_merchandise_sales"], merged["delivered_orders"])
    ]
    merged["attributed_roas"] = [
        safe_divide(ans, sp, 4) if sp > 0 else None
        for ans, sp in zip(merged["attributed_net_sales"], merged["ad_spend"])
    ]
    merged["blended_mer"] = [
        safe_divide(ns, sp, 4) if sp > 0 else None
        for ns, sp in zip(merged["net_merchandise_sales"], merged["ad_spend"])
    ]
    merged["session_conversion_rate"] = [
        safe_divide(p, s, 4)
        for p, s in zip(merged["purchases"], merged["sessions"])
    ]
    return merged


def compute_operations_breakdowns(
    canonical_orders: pd.DataFrame,
    returns: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute courier performance, RTO reasons, and return reason breakdowns for Operations page."""
    if canonical_orders.empty:
        return {
            "courier_performance": pd.DataFrame(),
            "rto_reasons": pd.DataFrame(),
            "return_reasons": pd.DataFrame(),
        }

    shipped = canonical_orders[canonical_orders["is_shipped"].astype(bool)].copy()
    if not shipped.empty:
        courier_rows: list[dict[str, Any]] = []
        for courier, grp in shipped.groupby("courier_partner", as_index=False):
            c_name = str(courier) if str(courier).strip() != "" else "Unassigned"
            n_ship = int(grp["order_id"].nunique())
            n_deliv = int(grp.loc[grp["is_delivered"].astype(bool), "order_id"].nunique())
            n_rto = int(grp.loc[grp["is_rto"].astype(bool), "order_id"].nunique())
            s_cost = round(float(grp["shipping_cost"].sum()), 2)
            courier_rows.append(
                {
                    "courier_partner": c_name,
                    "shipped_orders": n_ship,
                    "delivered_orders": n_deliv,
                    "rto_orders": n_rto,
                    "delivery_rate": safe_divide(n_deliv, n_ship, 4),
                    "rto_rate": safe_divide(n_rto, n_ship, 4),
                    "total_shipping_cost": s_cost,
                    "avg_shipping_cost_per_order": safe_divide(s_cost, n_ship, 2),
                }
            )
        courier_df = pd.DataFrame(courier_rows).sort_values("shipped_orders", ascending=False).reset_index(drop=True)
    else:
        courier_df = pd.DataFrame()

    rto_sub = canonical_orders[canonical_orders["is_rto"].astype(bool)].copy()
    if not rto_sub.empty:
        tot_rto = len(rto_sub)
        rto_df = (
            rto_sub.groupby("rto_reason", as_index=False)
            .agg(
                rto_orders=("order_id", "nunique"),
                rto_shipping_cost=("shipping_cost", "sum"),
            )
        )
        rto_df["rto_shipping_cost"] = rto_df["rto_shipping_cost"].round(2)
        rto_df["share_of_rto"] = rto_df["rto_orders"].apply(lambda x: safe_divide(x, tot_rto, 4))
        rto_df = rto_df.sort_values("rto_orders", ascending=False).reset_index(drop=True)
    else:
        rto_df = pd.DataFrame()

    ret_sub = canonical_orders[canonical_orders["is_returned_any"].astype(bool)].copy()
    if not ret_sub.empty:
        tot_ret = len(ret_sub)
        ret_df = (
            ret_sub.groupby("return_reason", as_index=False)
            .agg(
                returned_orders=("order_id", "nunique"),
                refund_amount=("effective_refund_amount", "sum"),
            )
        )
        ret_df["refund_amount"] = ret_df["refund_amount"].round(2)
        ret_df["share_of_returns"] = ret_df["returned_orders"].apply(lambda x: safe_divide(x, tot_ret, 4))
        ret_df = ret_df.sort_values("returned_orders", ascending=False).reset_index(drop=True)
    else:
        ret_df = pd.DataFrame()

    return {
        "courier_performance": courier_df,
        "rto_reasons": rto_df,
        "return_reasons": ret_df,
    }

