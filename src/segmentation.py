"""Customer intelligence: RFM segmentation, repeat-purchase analysis, and observed LTV.

All calculations use explicit observation windows and deterministic scoring rules.
Never claims predictive CLV from historical window sums.
"""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from src.metrics import safe_divide

RFM_SCORING_RULES = {
    "recency": "Quintile score 1–5 on days since last delivered order at snapshot_date (fewer days = higher score 5).",
    "frequency": "Deterministic order count brackets: 1 delivered order -> 1; 2 orders -> 3; 3 orders -> 4; 4+ orders -> 5.",
    "monetary": "Quintile score 1–5 on cumulative Net Merchandise Sales across delivered orders in the observation window.",
    "ltv_caveat": "Monetary value represents observed cumulative Net Merchandise Sales within the dataset window, not a predictive lifetime value model.",
}


def _score_quintile(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Assign 1–5 quintile scores deterministically, handling small (<5 row) fixtures gracefully."""
    n = len(series)
    if n == 0:
        return pd.Series(dtype=int)
    if n < 5 or series.nunique() == 1:
        # Linear min-max scaling to 1..5 for tiny test fixtures
        s_min = float(series.min())
        s_max = float(series.max())
        if s_max == s_min:
            return pd.Series(3, index=series.index, dtype=int)
        norm = (series - s_min) / (s_max - s_min)
        if not ascending:
            norm = 1.0 - norm
        return (1 + np.floor(norm * 4.0).clip(0, 4)).astype(int)

    ranks = series.rank(method="first", ascending=ascending)
    labels = [1, 2, 3, 4, 5]
    return pd.qcut(ranks, q=5, labels=labels).astype(int)


def _assign_rfm_segment(row: pd.Series) -> str:
    """Assign named customer segment from R, F, M scores (1–5)."""
    r = int(row["r_score"])
    f = int(row["f_score"])
    m = int(row["m_score"])

    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if f >= 3 and r >= 3:
        return "Loyal Customers"
    if r <= 2 and (f >= 3 or m >= 4):
        return "At Risk"
    if f == 1 and r >= 4:
        return "New Customers"
    if r >= 3 and (f >= 2 or m >= 3):
        return "Potential Loyalists"
    return "Hibernating"


def compute_rfm_table(
    canonical_orders: pd.DataFrame,
    snapshot_date: str | None = None,
) -> pd.DataFrame:
    """Compute customer-level Recency, Frequency, Monetary (RFM) scores and segments."""
    cols = [
        "customer_id",
        "city_tier",
        "first_touch_channel",
        "first_delivered_date",
        "last_delivered_date",
        "snapshot_date",
        "recency_days",
        "frequency",
        "monetary",
        "contribution_profit",
        "r_score",
        "f_score",
        "m_score",
        "rfm_score_str",
        "rfm_segment",
        "customer_type",
    ]
    if canonical_orders.empty:
        return pd.DataFrame(columns=cols)

    deliv = canonical_orders[canonical_orders["is_delivered"].astype(bool)].copy()
    if deliv.empty:
        return pd.DataFrame(columns=cols)

    snap_str = str(snapshot_date) if snapshot_date else str(deliv["order_day"].max())
    snap_ts = pd.Timestamp(snap_str)

    cust_agg = (
        deliv.groupby("customer_id", as_index=False)
        .agg(
            city_tier=("city_tier", "first"),
            first_touch_channel=("first_touch_channel", "first"),
            first_delivered_date=("order_day", "min"),
            last_delivered_date=("order_day", "max"),
            frequency=("order_id", "nunique"),
            monetary=("net_merchandise_sales", "sum"),
            contribution_profit=("contribution_profit", "sum"),
        )
    )
    cust_agg["monetary"] = cust_agg["monetary"].round(2)
    cust_agg["contribution_profit"] = cust_agg["contribution_profit"].round(2)
    cust_agg["snapshot_date"] = snap_str
    cust_agg["recency_days"] = (snap_ts - pd.to_datetime(cust_agg["last_delivered_date"])).dt.days.clip(lower=0)

    # Sort deterministically by customer_id before ranking so ties are 100% reproducible
    cust_agg = cust_agg.sort_values("customer_id").reset_index(drop=True)

    # R score: lower recency_days -> higher score (ascending=False)
    cust_agg["r_score"] = _score_quintile(cust_agg["recency_days"], ascending=False)

    # F score: deterministic order count brackets
    freq_s = cust_agg["frequency"]
    cust_agg["f_score"] = np.select(
        [freq_s <= 1, freq_s == 2, freq_s == 3, freq_s >= 4],
        [1, 3, 4, 5],
        default=1,
    ).astype(int)

    # M score: higher monetary -> higher score (ascending=True)
    cust_agg["m_score"] = _score_quintile(cust_agg["monetary"], ascending=True)

    cust_agg["rfm_score_str"] = (
        cust_agg["r_score"].astype(str)
        + cust_agg["f_score"].astype(str)
        + cust_agg["m_score"].astype(str)
    )
    cust_agg["rfm_segment"] = cust_agg.apply(_assign_rfm_segment, axis=1)
    cust_agg["customer_type"] = np.where(cust_agg["frequency"] >= 2, "Repeat Customer", "First-Time Customer")

    return cust_agg[cols].sort_values(["monetary", "frequency"], ascending=[False, False]).reset_index(drop=True)


def summarize_rfm_segments(rfm_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate customer counts, revenue share, contribution share, and averages by RFM segment."""
    if rfm_df.empty:
        return pd.DataFrame(
            columns=[
                "rfm_segment",
                "customers",
                "customer_share",
                "avg_recency_days",
                "avg_frequency",
                "avg_monetary",
                "total_net_sales",
                "revenue_share",
                "total_contribution_profit",
                "contribution_share",
            ]
        )

    tot_cust = len(rfm_df)
    tot_rev = float(rfm_df["monetary"].sum())
    tot_contrib = float(rfm_df["contribution_profit"].sum())

    seg = (
        rfm_df.groupby("rfm_segment", as_index=False)
        .agg(
            customers=("customer_id", "nunique"),
            avg_recency_days=("recency_days", "mean"),
            avg_frequency=("frequency", "mean"),
            avg_monetary=("monetary", "mean"),
            total_net_sales=("monetary", "sum"),
            total_contribution_profit=("contribution_profit", "sum"),
        )
    )
    seg["avg_recency_days"] = seg["avg_recency_days"].round(1)
    seg["avg_frequency"] = seg["avg_frequency"].round(2)
    seg["avg_monetary"] = seg["avg_monetary"].round(2)
    seg["total_net_sales"] = seg["total_net_sales"].round(2)
    seg["total_contribution_profit"] = seg["total_contribution_profit"].round(2)
    seg["customer_share"] = seg["customers"].apply(lambda c: safe_divide(c, tot_cust, 4))
    seg["revenue_share"] = seg["total_net_sales"].apply(lambda r: safe_divide(r, tot_rev, 4))
    seg["contribution_share"] = seg["total_contribution_profit"].apply(
        lambda cp: safe_divide(cp, tot_contrib, 4) if tot_contrib > 0 else None
    )

    return seg.sort_values("total_net_sales", ascending=False).reset_index(drop=True)


def compute_repeat_purchase_and_ltv_summary(
    canonical_orders: pd.DataFrame,
    customers: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute first-time vs repeat customer metrics and observed lifetime value within the dataset window."""
    total_registered = int(customers["customer_id"].nunique()) if customers is not None and not customers.empty else 0
    rfm = compute_rfm_table(canonical_orders)

    if rfm.empty:
        return {
            "total_registered_customers": total_registered,
            "active_delivered_customers": 0,
            "first_time_customers": 0,
            "repeat_customers": 0,
            "repeat_purchase_rate": None,
            "total_delivered_orders": 0,
            "repeat_customer_orders": 0,
            "repeat_order_share": None,
            "total_net_sales": 0.0,
            "first_time_customer_net_sales": 0.0,
            "repeat_customer_net_sales": 0.0,
            "repeat_revenue_share": None,
            "observed_avg_ltv_net_sales": None,
            "observed_avg_ltv_contribution": None,
            "first_time_avg_ltv": None,
            "repeat_customer_avg_ltv": None,
            "observation_window_start": None,
            "observation_window_end": None,
            "caveat": RFM_SCORING_RULES["ltv_caveat"],
        }

    active_custs = len(rfm)
    ft_df = rfm[rfm["frequency"] == 1]
    rep_df = rfm[rfm["frequency"] >= 2]

    ft_custs = len(ft_df)
    rep_custs = len(rep_df)
    rep_rate = safe_divide(rep_custs, active_custs, 4)

    tot_deliv_orders = int(rfm["frequency"].sum())
    rep_cust_orders = int(rep_df["frequency"].sum())
    rep_order_share = safe_divide(rep_cust_orders, tot_deliv_orders, 4)

    tot_sales = round(float(rfm["monetary"].sum()), 2)
    ft_sales = round(float(ft_df["monetary"].sum()), 2)
    rep_sales = round(float(rep_df["monetary"].sum()), 2)
    rep_rev_share = safe_divide(rep_sales, tot_sales, 4)

    tot_contrib = round(float(rfm["contribution_profit"].sum()), 2)

    return {
        "total_registered_customers": max(total_registered, active_custs),
        "active_delivered_customers": active_custs,
        "first_time_customers": ft_custs,
        "repeat_customers": rep_custs,
        "repeat_purchase_rate": rep_rate,
        "total_delivered_orders": tot_deliv_orders,
        "repeat_customer_orders": rep_cust_orders,
        "repeat_order_share": rep_order_share,
        "total_net_sales": tot_sales,
        "first_time_customer_net_sales": ft_sales,
        "repeat_customer_net_sales": rep_sales,
        "repeat_revenue_share": rep_rev_share,
        "observed_avg_ltv_net_sales": safe_divide(tot_sales, active_custs, 2),
        "observed_avg_ltv_contribution": safe_divide(tot_contrib, active_custs, 2),
        "first_time_avg_ltv": safe_divide(ft_sales, ft_custs, 2),
        "repeat_customer_avg_ltv": safe_divide(rep_sales, rep_custs, 2),
        "observation_window_start": str(canonical_orders["order_day"].min()),
        "observation_window_end": str(canonical_orders["order_day"].max()),
        "caveat": RFM_SCORING_RULES["ltv_caveat"],
    }
