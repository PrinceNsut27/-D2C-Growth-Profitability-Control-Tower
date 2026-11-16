"""Monthly customer cohort retention and cumulative cohort revenue analysis.

Defines cohorts explicitly by the calendar month of a customer's first delivered
order (Month 0) and tracks repeat delivered purchases in subsequent calendar months.
"""

from __future__ import annotations

from typing import Any
import pandas as pd

from src.metrics import safe_divide


def _month_diff(order_month: pd.Series, cohort_month: pd.Series) -> pd.Series:
    """Compute integer month offset (0, 1, 2, ...) between YYYY-MM strings."""
    o_yr = order_month.str.slice(0, 4).astype(int)
    o_mo = order_month.str.slice(5, 7).astype(int)
    c_yr = cohort_month.str.slice(0, 4).astype(int)
    c_mo = cohort_month.str.slice(5, 7).astype(int)
    return (o_yr - c_yr) * 12 + (o_mo - c_mo)


def compute_monthly_cohort_retention(
    canonical_orders: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Compute monthly cohort table (long format, retention rate pivot matrix, and active count matrix)."""
    empty_long = pd.DataFrame(
        columns=[
            "cohort_month",
            "order_month",
            "period_number",
            "cohort_size",
            "active_customers",
            "retention_rate",
            "cohort_net_sales",
            "cohort_contribution_profit",
            "revenue_per_cohort_customer",
        ]
    )
    if canonical_orders.empty:
        return {
            "cohort_long": empty_long,
            "retention_matrix": pd.DataFrame(),
            "active_customers_matrix": pd.DataFrame(),
            "cohort_sizes": pd.DataFrame(columns=["cohort_month", "cohort_size"]),
        }

    deliv = canonical_orders[canonical_orders["is_delivered"].astype(bool)].copy()
    if deliv.empty:
        return {
            "cohort_long": empty_long,
            "retention_matrix": pd.DataFrame(),
            "active_customers_matrix": pd.DataFrame(),
            "cohort_sizes": pd.DataFrame(columns=["cohort_month", "cohort_size"]),
        }

    # Recompute first delivered month inside the filtered slice so cohorts are self-consistent
    first_month_df = (
        deliv.groupby("customer_id", as_index=False)["order_month"]
        .min()
        .rename(columns={"order_month": "slice_cohort_month"})
    )
    deliv = deliv.merge(first_month_df, on="customer_id", how="left")
    deliv["period_number"] = _month_diff(deliv["order_month"], deliv["slice_cohort_month"])
    deliv = deliv[deliv["period_number"] >= 0]

    cohort_sizes = (
        first_month_df.groupby("slice_cohort_month", as_index=False)["customer_id"]
        .nunique()
        .rename(columns={"slice_cohort_month": "cohort_month", "customer_id": "cohort_size"})
    )

    grouped = (
        deliv.groupby(["slice_cohort_month", "order_month", "period_number"], as_index=False)
        .agg(
            active_customers=("customer_id", "nunique"),
            cohort_net_sales=("net_merchandise_sales", "sum"),
            cohort_contribution_profit=("contribution_profit", "sum"),
        )
        .rename(columns={"slice_cohort_month": "cohort_month"})
    )

    cohort_long = grouped.merge(cohort_sizes, on="cohort_month", how="left")
    cohort_long["cohort_net_sales"] = cohort_long["cohort_net_sales"].round(2)
    cohort_long["cohort_contribution_profit"] = cohort_long["cohort_contribution_profit"].round(2)
    cohort_long["retention_rate"] = [
        safe_divide(act, csize, 4)
        for act, csize in zip(cohort_long["active_customers"], cohort_long["cohort_size"])
    ]
    cohort_long["revenue_per_cohort_customer"] = [
        safe_divide(rev, csize, 2)
        for rev, csize in zip(cohort_long["cohort_net_sales"], cohort_long["cohort_size"])
    ]

    cohort_long = cohort_long[
        [
            "cohort_month",
            "order_month",
            "period_number",
            "cohort_size",
            "active_customers",
            "retention_rate",
            "cohort_net_sales",
            "cohort_contribution_profit",
            "revenue_per_cohort_customer",
        ]
    ].sort_values(["cohort_month", "period_number"]).reset_index(drop=True)

    retention_matrix = cohort_long.pivot(
        index="cohort_month", columns="period_number", values="retention_rate"
    )
    active_matrix = cohort_long.pivot(
        index="cohort_month", columns="period_number", values="active_customers"
    )

    return {
        "cohort_long": cohort_long,
        "retention_matrix": retention_matrix,
        "active_customers_matrix": active_matrix,
        "cohort_sizes": cohort_sizes,
    }
