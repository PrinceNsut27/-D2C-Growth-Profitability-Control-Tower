"""Marketing spend, customer acquisition cost (CAC), attributed ROAS, and blended MER.

Strictly separates observational campaign-attributed ROAS from blended MER, and aligns
acquisition spend with newly acquired customers (first delivered order in scope).
Never claims causal lift or incremental ROAS from observational attribution data.
"""

from __future__ import annotations

from typing import Any
import pandas as pd

from src.metrics import compute_business_performance_And_economics, safe_divide

ATTRIBUTION_CAVEAT = (
    "Attributed revenue and ROAS use observational last-touch order campaign tags. "
    "They do NOT represent causal lift or incremental revenue. Orders without a campaign tag "
    "(Organic Search, Direct, Email/CRM, Marketplace) remain unassigned and are included "
    "in Blended MER rather than forced into paid campaigns."
)


def filter_marketing_spend(
    marketing_spend: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    channels: list[str] | None = None,
    campaigns: list[str] | None = None,
) -> pd.DataFrame:
    """Filter marketing_spend table by date range, channel, and campaign."""
    if marketing_spend.empty:
        return marketing_spend.copy()

    df = marketing_spend.copy()
    date_col = "date" if "date" in df.columns else "spend_date"
    df[date_col] = df[date_col].astype(str)

    if start_date:
        df = df[df[date_col] >= str(start_date)]
    if end_date:
        df = df[df[date_col] <= str(end_date)]
    if channels:
        df = df[df["channel"].isin(channels)]
    if campaigns:
        df = df[df["campaign_id"].isin(campaigns)]
    return df.reset_index(drop=True)


def compute_acquisition_summary(
    canonical_orders: pd.DataFrame,
    marketing_spend: pd.DataFrame,
) -> dict[str, Any]:
    """Compute top-level acquisition KPIs: Spend, New Customers, Blended CAC, Paid CAC, Attributed ROAS, and Blended MER."""
    total_spend = round(float(marketing_spend["spend"].sum()), 2) if not marketing_spend.empty else 0.0
    total_impressions = int(marketing_spend["impressions"].sum()) if not marketing_spend.empty else 0
    total_clicks = int(marketing_spend["clicks"].sum()) if not marketing_spend.empty else 0

    if canonical_orders.empty:
        return {
            "ad_spend": total_spend,
            "impressions": total_impressions,
            "clicks": total_clicks,
            "ctr": safe_divide(total_clicks, total_impressions, 4),
            "cpc": safe_divide(total_spend, total_clicks, 2),
            "total_new_customers": 0,
            "paid_new_customers": 0,
            "total_net_sales": 0.0,
            "attributed_net_sales": 0.0,
            "unassigned_net_sales": 0.0,
            "blended_cac": None,
            "paid_channel_cac": None,
            "attributed_roas": safe_divide(0.0, total_spend, 4) if total_spend > 0 else None,
            "blended_mer": safe_divide(0.0, total_spend, 4) if total_spend > 0 else None,
            "attribution_caveat": ATTRIBUTION_CAVEAT,
        }

    df = canonical_orders
    has_campaign = df["campaign_id"].fillna("").astype(str).str.strip() != ""
    new_cust_mask = df["is_new_customer_order"].astype(bool)

    total_new_customers = int(df.loc[new_cust_mask, "customer_id"].nunique())
    paid_new_customers = int(df.loc[new_cust_mask & has_campaign, "customer_id"].nunique())

    total_net_sales = round(float(df["net_merchandise_sales"].sum()), 2)
    attributed_net_sales = round(float(df.loc[has_campaign, "net_merchandise_sales"].sum()), 2)
    unassigned_net_sales = round(total_net_sales - attributed_net_sales, 2)

    blended_cac = safe_divide(total_spend, total_new_customers, 2)
    paid_channel_cac = safe_divide(total_spend, paid_new_customers, 2)
    attributed_roas = safe_divide(attributed_net_sales, total_spend, 4)
    blended_mer = safe_divide(total_net_sales, total_spend, 4)

    return {
        "ad_spend": total_spend,
        "impressions": total_impressions,
        "clicks": total_clicks,
        "ctr": safe_divide(total_clicks, total_impressions, 4),
        "cpc": safe_divide(total_spend, total_clicks, 2),
        "total_new_customers": total_new_customers,
        "paid_new_customers": paid_new_customers,
        "total_net_sales": total_net_sales,
        "attributed_net_sales": attributed_net_sales,
        "unassigned_net_sales": unassigned_net_sales,
        "blended_cac": blended_cac,
        "paid_channel_cac": paid_channel_cac,
        "attributed_roas": attributed_roas,
        "blended_mer": blended_mer,
        "attribution_caveat": ATTRIBUTION_CAVEAT,
    }


def compute_channel_acquisition_and_profitability(
    canonical_orders: pd.DataFrame,
    marketing_spend: pd.DataFrame,
) -> pd.DataFrame:
    """Compute channel-level spend, new customers, CAC, attributed ROAS, and contribution economics."""
    spend_by_ch: dict[str, dict[str, Any]] = {}
    if not marketing_spend.empty:
        for ch, grp in marketing_spend.groupby("channel", as_index=False):
            spend_by_ch[str(ch)] = {
                "ad_spend": round(float(grp["spend"].sum()), 2),
                "impressions": int(grp["impressions"].sum()),
                "clicks": int(grp["clicks"].sum()),
            }

    all_channels = sorted(
        set(spend_by_ch.keys())
        | (set(canonical_orders["channel"].dropna().astype(str)) if not canonical_orders.empty else set())
    )

    rows: list[dict[str, Any]] = []
    for ch in all_channels:
        ch_orders = (
            canonical_orders[canonical_orders["channel"] == ch]
            if not canonical_orders.empty
            else pd.DataFrame()
        )
        sp_info = spend_by_ch.get(ch, {"ad_spend": 0.0, "impressions": 0, "clicks": 0})
        ad_spend = sp_info["ad_spend"]
        impressions = sp_info["impressions"]
        clicks = sp_info["clicks"]

        perf = compute_business_performance_And_economics(ch_orders)
        if not ch_orders.empty:
            new_custs = int(ch_orders.loc[ch_orders["is_new_customer_order"].astype(bool), "customer_id"].nunique())
            repeat_orders = int(
                ch_orders.loc[
                    ch_orders["is_delivered"].astype(bool) & (ch_orders["customer_delivered_seq"] > 1),
                    "order_id",
                ].nunique()
            )
            cod_orders = int((ch_orders["payment_mode"] == "cod").sum())
            cod_share = safe_divide(cod_orders, perf["placed_orders"], 4)
        else:
            new_custs = 0
            repeat_orders = 0
            cod_share = None

        # CAC is defined for paid channels with spend > 0 and new_custs > 0; None otherwise
        cac = safe_divide(ad_spend, new_custs, 2) if ad_spend > 0 else None
        roas = safe_divide(perf["net_merchandise_sales"], ad_spend, 4) if ad_spend > 0 else None
        net_contribution_after_ads = round(perf["contribution_profit"] - ad_spend, 2)

        rows.append(
            {
                "channel": ch,
                "ad_spend": ad_spend,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": safe_divide(clicks, impressions, 4),
                "cpc": safe_divide(ad_spend, clicks, 2),
                "placed_orders": perf["placed_orders"],
                "delivered_orders": perf["delivered_orders"],
                "new_customers": new_custs,
                "repeat_delivered_orders": repeat_orders,
                "cod_order_share": cod_share,
                "rto_rate": perf["rto_rate"],
                "return_rate": perf["return_rate"],
                "delivered_gross_revenue": perf["delivered_gross_revenue"],
                "delivered_discounts": perf["delivered_discounts"],
                "refund_amount": perf["refund_amount"],
                "net_merchandise_sales": perf["net_merchandise_sales"],
                "aov": perf["aov"],
                "net_cogs": perf["net_cogs"],
                "gross_profit": perf["gross_profit"],
                "shipping_cost": perf["shipping_cost"],
                "payment_fees": perf["payment_fees"],
                "contribution_profit": perf["contribution_profit"],
                "contribution_margin_pct": perf["contribution_margin_pct"],
                "cac": cac,
                "attributed_roas": roas,
                "net_contribution_after_ad_spend": net_contribution_after_ads,
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("net_merchandise_sales", ascending=False).reset_index(drop=True)


def compute_campaign_performance(
    canonical_orders: pd.DataFrame,
    marketing_spend: pd.DataFrame,
    include_unassigned: bool = True,
) -> pd.DataFrame:
    """Compute campaign-level spend, attributed orders, new customers, CAC, attributed ROAS, and contribution."""
    spend_by_cmp: dict[str, dict[str, Any]] = {}
    if not marketing_spend.empty:
        for (cmp_id, platform, channel), grp in marketing_spend.groupby(
            ["campaign_id", "platform", "channel"], as_index=False
        ):
            spend_by_cmp[str(cmp_id)] = {
                "platform": str(platform),
                "channel": str(channel),
                "ad_spend": round(float(grp["spend"].sum()), 2),
                "impressions": int(grp["impressions"].sum()),
                "clicks": int(grp["clicks"].sum()),
            }

    order_cmp_ids = set()
    if not canonical_orders.empty:
        order_cmp_ids = {
            c for c in canonical_orders["campaign_id"].fillna("").astype(str).str.strip().unique() if c != ""
        }

    all_cmp_ids = sorted(set(spend_by_cmp.keys()) | order_cmp_ids)
    rows: list[dict[str, Any]] = []

    for cmp_id in all_cmp_ids:
        cmp_orders = (
            canonical_orders[canonical_orders["campaign_id"].fillna("").astype(str).str.strip() == cmp_id]
            if not canonical_orders.empty
            else pd.DataFrame()
        )
        sp = spend_by_cmp.get(
            cmp_id,
            {
                "platform": "Unknown",
                "channel": str(cmp_orders["channel"].iloc[0]) if not cmp_orders.empty else "Unknown",
                "ad_spend": 0.0,
                "impressions": 0,
                "clicks": 0,
            },
        )
        ad_spend = sp["ad_spend"]
        impressions = sp["impressions"]
        clicks = sp["clicks"]

        perf = compute_business_performance_And_economics(cmp_orders)
        if not cmp_orders.empty:
            new_custs = int(cmp_orders.loc[cmp_orders["is_new_customer_order"].astype(bool), "customer_id"].nunique())
            cod_orders = int((cmp_orders["payment_mode"] == "cod").sum())
            cod_share = safe_divide(cod_orders, perf["placed_orders"], 4)
            disc_rate = safe_divide(perf["delivered_discounts"], perf["delivered_gross_revenue"], 4)
        else:
            new_custs = 0
            cod_share = None
            disc_rate = None

        cac = safe_divide(ad_spend, new_custs, 2) if ad_spend > 0 else None
        roas = safe_divide(perf["net_merchandise_sales"], ad_spend, 4) if ad_spend > 0 else None
        contrib_after_ads = round(perf["contribution_profit"] - ad_spend, 2)

        rows.append(
            {
                "campaign_id": cmp_id,
                "platform": sp["platform"],
                "channel": sp["channel"],
                "ad_spend": ad_spend,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": safe_divide(clicks, impressions, 4),
                "cpc": safe_divide(ad_spend, clicks, 2),
                "placed_orders": perf["placed_orders"],
                "delivered_orders": perf["delivered_orders"],
                "new_customers": new_custs,
                "cod_order_share": cod_share,
                "rto_rate": perf["rto_rate"],
                "return_rate": perf["return_rate"],
                "effective_discount_rate": disc_rate,
                "delivered_gross_revenue": perf["delivered_gross_revenue"],
                "delivered_discounts": perf["delivered_discounts"],
                "refund_amount": perf["refund_amount"],
                "net_merchandise_sales": perf["net_merchandise_sales"],
                "aov": perf["aov"],
                "net_cogs": perf["net_cogs"],
                "gross_profit": perf["gross_profit"],
                "shipping_cost": perf["shipping_cost"],
                "payment_fees": perf["payment_fees"],
                "contribution_profit": perf["contribution_profit"],
                "contribution_margin_pct": perf["contribution_margin_pct"],
                "cac": cac,
                "attributed_roas": roas,
                "net_contribution_after_ad_spend": contrib_after_ads,
            }
        )

    if include_unassigned and not canonical_orders.empty:
        unassigned_orders = canonical_orders[
            canonical_orders["campaign_id"].fillna("").astype(str).str.strip() == ""
        ]
        if not unassigned_orders.empty:
            perf = compute_business_performance_And_economics(unassigned_orders)
            new_custs = int(
                unassigned_orders.loc[unassigned_orders["is_new_customer_order"].astype(bool), "customer_id"].nunique()
            )
            cod_orders = int((unassigned_orders["payment_mode"] == "cod").sum())
            cod_share = safe_divide(cod_orders, perf["placed_orders"], 4)
            disc_rate = safe_divide(perf["delivered_discounts"], perf["delivered_gross_revenue"], 4)
            rows.append(
                {
                    "campaign_id": "UNASSIGNED (Organic / Direct / CRM / Marketplace)",
                    "platform": "Non-Paid / External",
                    "channel": "Multiple Non-Campaign",
                    "ad_spend": 0.0,
                    "impressions": 0,
                    "clicks": 0,
                    "ctr": None,
                    "cpc": None,
                    "placed_orders": perf["placed_orders"],
                    "delivered_orders": perf["delivered_orders"],
                    "new_customers": new_custs,
                    "cod_order_share": cod_share,
                    "rto_rate": perf["rto_rate"],
                    "return_rate": perf["return_rate"],
                    "effective_discount_rate": disc_rate,
                    "delivered_gross_revenue": perf["delivered_gross_revenue"],
                    "delivered_discounts": perf["delivered_discounts"],
                    "refund_amount": perf["refund_amount"],
                    "net_merchandise_sales": perf["net_merchandise_sales"],
                    "aov": perf["aov"],
                    "net_cogs": perf["net_cogs"],
                    "gross_profit": perf["gross_profit"],
                    "shipping_cost": perf["shipping_cost"],
                    "payment_fees": perf["payment_fees"],
                    "contribution_profit": perf["contribution_profit"],
                    "contribution_margin_pct": perf["contribution_margin_pct"],
                    "cac": None,
                    "attributed_roas": None,
                    "net_contribution_after_ad_spend": perf["contribution_profit"],
                }
            )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("ad_spend", ascending=False).reset_index(drop=True)
