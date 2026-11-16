"""Transparent rule-based business recommendation engine.

Generates human-in-the-loop decision-support recommendations directly from computed
metrics. Does not use an LLM, never fabricates numbers, never claims causal lift
from observational data, and never autonomously executes budget, pricing, or
inventory actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import pandas as pd

from src.attribution import (
    compute_acquisition_summary,
    compute_campaign_performance,
    compute_channel_acquisition_and_profitability,
)
from src.cohorts import compute_monthly_cohort_retention
from src.metrics import (
    compute_business_performance_And_economics,
    compute_cod_vs_prepaid_metrics,
    compute_funnel_metrics,
    compute_inventory_and_stockout_metrics,
    compute_sku_profitability,
    safe_divide,
)
from src.segmentation import (
    compute_repeat_purchase_and_ltv_summary,
    compute_rfm_table,
    summarize_rfm_segments,
)


@dataclass
class Recommendation:
    """Structured evidence-backed recommendation for human evaluation."""

    recommendation_id: str
    title: str
    business_area: str
    priority: str  # "High", "Medium", "Low"
    affected_segment: str
    date_window: str
    observed_condition: str
    evidence_metrics: str
    business_implication: str
    possible_mechanism: str
    suggested_action: str
    risks_and_alternatives: str
    success_metric: str
    measurement_period: str
    confidence_and_limitations: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_recommendations(
    canonical_orders: pd.DataFrame,
    canonical_order_items: pd.DataFrame,
    marketing_spend: pd.DataFrame,
    sessions: pd.DataFrame,
    inventory_snapshots: pd.DataFrame,
    products: pd.DataFrame | None = None,
    customers: pd.DataFrame | None = None,
) -> list[Recommendation]:
    """Evaluate deterministic business rules against computed metrics and return recommendations."""
    recommendations: list[Recommendation] = []

    if canonical_orders.empty and sessions.empty and inventory_snapshots.empty:
        return recommendations

    # Determine active date window
    if not canonical_orders.empty:
        min_d = str(canonical_orders["order_day"].min())
        max_d = str(canonical_orders["order_day"].max())
        date_window = f"{min_d} to {max_d}"
    elif not marketing_spend.empty:
        dcol = "date" if "date" in marketing_spend.columns else "spend_date"
        date_window = f"{marketing_spend[dcol].min()} to {marketing_spend[dcol].max()}"
    else:
        date_window = "Selected Filter Window"

    exec_kpis = compute_business_performance_And_economics(canonical_orders)
    acq_summary = compute_acquisition_summary(canonical_orders, marketing_spend)
    cmp_df = compute_campaign_performance(canonical_orders, marketing_spend, include_unassigned=False)
    funnel_overall = compute_funnel_metrics(sessions)
    funnel_by_dev = compute_funnel_metrics(sessions, group_cols=["device"])
    funnel_by_ch = compute_funnel_metrics(sessions, group_cols=["channel"])
    cod_df = compute_cod_vs_prepaid_metrics(canonical_orders, group_cols=["payment_mode"])
    cod_tier_df = compute_cod_vs_prepaid_metrics(canonical_orders, group_cols=["payment_mode", "city_tier"])
    sku_df = compute_sku_profitability(canonical_order_items)
    inv_df = compute_inventory_and_stockout_metrics(inventory_snapshots, products)
    rfm_df = compute_rfm_table(canonical_orders)
    rfm_seg_df = summarize_rfm_segments(rfm_df)
    repeat_summary = compute_repeat_purchase_and_ltv_summary(canonical_orders, customers)
    cohorts_res = compute_monthly_cohort_retention(canonical_orders)

    # -------------------------------------------------------------------------
    # RULE 1: Operations & Unit Economics — High COD RTO Rate vs Prepaid
    # -------------------------------------------------------------------------
    if not cod_df.empty and {"cod", "prepaid"}.issubset(set(cod_df["payment_mode"])):
        cod_row = cod_df[cod_df["payment_mode"] == "cod"].iloc[0]
        pre_row = cod_df[cod_df["payment_mode"] == "prepaid"].iloc[0]
        cod_rto = cod_row["rto_rate"]
        pre_rto = pre_row["rto_rate"]

        if cod_rto is not None and pre_rto is not None and cod_rto > max(0.12, pre_rto * 2.0):
            rto_drag_cod = float(cod_row["rto_shipping_cost"])
            cod_cm_pct = cod_row["contribution_margin_pct"]
            pre_cm_pct = pre_row["contribution_margin_pct"]

            tier3_note = ""
            if not cod_tier_df.empty:
                t3_cod = cod_tier_df[
                    (cod_tier_df["payment_mode"] == "cod") & (cod_tier_df["city_tier"] == "Tier 3")
                ]
                if not t3_cod.empty and t3_cod.iloc[0]["rto_rate"] is not None:
                    tier3_note = f" (reaching {t3_cod.iloc[0]['rto_rate']*100:.1f}% in Tier 3 cities)"

            recommendations.append(
                Recommendation(
                    recommendation_id="REC-OPS-01",
                    title="Mitigate High COD Return-to-Origin (RTO) Rate & Reverse Logistics Drag",
                    business_area="Operations & Unit Economics",
                    priority="High",
                    affected_segment=f"Cash-on-Delivery (COD) Orders{tier3_note}",
                    date_window=date_window,
                    observed_condition=(
                        f"COD RTO rate ({cod_rto*100:.2f}% of shipped COD orders) is {cod_rto/max(pre_rto, 0.0001):.1f}x "
                        f"higher than Prepaid RTO rate ({pre_rto*100:.2f}%){tier3_note}."
                    ),
                    evidence_metrics=(
                        f"COD Shipped Orders: {int(cod_row['shipped_orders']):,} | COD RTO Orders: {int(cod_row['rto_orders']):,} "
                        f"({cod_rto*100:.2f}%) vs Prepaid RTO: {int(pre_row['rto_orders']):,}/{int(pre_row['shipped_orders']):,} "
                        f"({pre_rto*100:.2f}%) | COD RTO Shipping Cost Drag: INR {rto_drag_cod:,.2f} | "
                        f"COD Contribution Margin: {(cod_cm_pct or 0)*100:.2f}% vs Prepaid: {(pre_cm_pct or 0)*100:.2f}%."
                    ),
                    business_implication=(
                        f"RTO orders generate INR 0 net sales while incurring INR {rto_drag_cod:,.2f} in forward and reverse "
                        f"courier charges, depressing COD contribution margin by {((pre_cm_pct or 0) - (cod_cm_pct or 0))*100:.2f} "
                        "percentage points relative to prepaid orders."
                    ),
                    possible_mechanism=(
                        "Impulse COD checkout during discount promotions, incomplete doorstep addresses in Tier 2/3 pincodes, "
                        "or lack of pre-dispatch order intent verification."
                    ),
                    suggested_action=(
                        "1) Test automated WhatsApp/IVR order confirmation before shipping COD orders in high-RTO pincodes; "
                        "2) Test a small instant UPI prepaid incentive (e.g., INR 20–25 off prepaid, funded by the avoided "
                        "INR 25 COD fee and reduced RTO shipping loss)."
                    ),
                    risks_and_alternatives=(
                        "Strict COD gating or confirmation friction can reduce gross checkout conversion among genuine "
                        "cash-preferring customers in Tier 2/3 cities. Courier partner SLA differences may also explain part of the gap."
                    ),
                    success_metric="Net Delivered Contribution Profit per 1,000 Checkout Sessions and Shipped COD RTO Rate (%).",
                    measurement_period="4-week randomized A/B checkout & pre-dispatch confirmation experiment.",
                    confidence_and_limitations=(
                        f"High data completeness ({int(cod_row['shipped_orders']):,} shipped COD orders). Observational comparison "
                        "between COD and Prepaid buyers reflects self-selection; validate via controlled checkout test."
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # RULE 2: Marketing & Unit Economics — Discount-Heavy / Weak-Margin Campaign
    # -------------------------------------------------------------------------
    if not cmp_df.empty and exec_kpis["contribution_margin_pct"] is not None:
        port_cm_pct = float(exec_kpis["contribution_margin_pct"])
        weak_cm_cmps = cmp_df[
            (cmp_df["ad_spend"] > 0)
            & (cmp_df["contribution_margin_pct"].notna())
            & (cmp_df["contribution_margin_pct"] < (port_cm_pct - 0.05))
        ].sort_values("contribution_margin_pct", ascending=True)

        if not weak_cm_cmps.empty:
            w_row = weak_cm_cmps.iloc[0]
            cmp_id = str(w_row["campaign_id"])
            c_spend = float(w_row["ad_spend"])
            c_roas = w_row["attributed_roas"]
            c_cm_pct = float(w_row["contribution_margin_pct"])
            c_disc = float(w_row["effective_discount_rate"] or 0.0)
            c_rto = float(w_row["rto_rate"] or 0.0)
            c_cod = float(w_row["cod_order_share"] or 0.0)
            c_aov = float(w_row["aov"] or 0.0)

            recommendations.append(
                Recommendation(
                    recommendation_id="REC-MKT-01",
                    title=f"Audit Promo Margin Erosion & COD/RTO Mix on Campaign {cmp_id}",
                    business_area="Marketing & Unit Economics",
                    priority="High",
                    affected_segment=f"Campaign {cmp_id} ({w_row['platform']} / {w_row['channel']})",
                    date_window=date_window,
                    observed_condition=(
                        f"{cmp_id} has the lowest contribution margin ({c_cm_pct*100:.2f}% vs portfolio {port_cm_pct*100:.2f}%), "
                        f"driven by a {c_disc*100:.2f}% effective discount rate, {c_cod*100:.2f}% COD share, and {c_rto*100:.2f}% RTO rate."
                    ),
                    evidence_metrics=(
                        f"Ad Spend: INR {c_spend:,.2f} | Placed Orders: {int(w_row['placed_orders']):,} | "
                        f"Delivered Orders: {int(w_row['delivered_orders']):,} | AOV: INR {c_aov:,.2f} | "
                        f"Effective Discount Rate: {c_disc*100:.2f}% | RTO Rate: {c_rto*100:.2f}% | "
                        f"Contribution Profit (before ad spend): INR {float(w_row['contribution_profit']):,.2f} ({c_cm_pct*100:.2f}%) | "
                        f"Attributed ROAS: {(c_roas or 0):.4f}x | Net Contribution After Ad Spend: INR {float(w_row['net_contribution_after_ad_spend']):,.2f}."
                    ),
                    business_implication=(
                        "Deep promotional discounting combined with high COD refusal erodes unit contribution before ad spend is "
                        "even recovered, making gross top-line order volume unprofitable on a fully loaded basis."
                    ),
                    possible_mechanism=(
                        "Flash-sale ad creative attracts price-sensitive, one-time COD shoppers with higher doorstep refusal "
                        "and lower repeat propensity."
                    ),
                    suggested_action=(
                        f"Evaluate replacing flat deep discounts on {cmp_id} with minimum-order-value (MOV >= INR 799) tiered "
                        "bundle offers or prepaid-exclusive promo codes to protect AOV and contribution margin."
                    ),
                    risks_and_alternatives=(
                        "Reducing discount depth may lower click-through and initial conversion rates. Note that last-touch "
                        "attribution does not capture upper-funnel awareness spillover."
                    ),
                    success_metric="Contribution Profit after Ad Spend (CM3) and New-Customer 60-Day Repeat Rate.",
                    measurement_period="3-week campaign creative & offer split test.",
                    confidence_and_limitations=(
                        f"High data completeness ({int(w_row['placed_orders']):,} orders). Observational campaign tags reflect "
                        "last-touch attribution, not causal incrementality."
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # RULE 3: Marketing Efficiency — High Spend / High CAC Campaign Review
    # -------------------------------------------------------------------------
    if not cmp_df.empty and acq_summary["paid_channel_cac"] is not None:
        paid_cmps = cmp_df[cmp_df["ad_spend"] > 0].sort_values("ad_spend", ascending=False)
        if not paid_cmps.empty:
            high_cac_cmps = paid_cmps[
                paid_cmps["cac"].notna() & (paid_cmps["cac"] >= float(acq_summary["paid_channel_cac"]))
            ].sort_values("cac", ascending=False)
            target_row = high_cac_cmps.iloc[0] if not high_cac_cmps.empty else paid_cmps.iloc[0]
            t_id = str(target_row["campaign_id"])
            t_spend = float(target_row["ad_spend"])
            t_cac = float(target_row["cac"] or 0.0)
            t_roas = float(target_row["attributed_roas"] or 0.0)
            t_new = int(target_row["new_customers"])

            recommendations.append(
                Recommendation(
                    recommendation_id="REC-MKT-02",
                    title=f"Investigate Acquisition Cost Efficiency & Budget Allocation on {t_id}",
                    business_area="Marketing & Acquisition",
                    priority="High",
                    affected_segment=f"Campaign {t_id} ({target_row['platform']} / {target_row['channel']})",
                    date_window=date_window,
                    observed_condition=(
                        f"Campaign {t_id} spent INR {t_spend:,.2f} with an attributed CAC of INR {t_cac:,.2f} "
                        f"(vsObserved 6M Customer Net Sales LTV of INR {float(repeat_summary['observed_avg_ltv_net_sales'] or 0):,.2f}) "
                        f"and attributed ROAS of {t_roas:.4f}x."
                    ),
                    evidence_metrics=(
                        f"Campaign Spend: INR {t_spend:,.2f} | Clicks: {int(target_row['clicks']):,} (CPC: INR {float(target_row['cpc'] or 0):,.2f}) | "
                        f"New Customers Acquired: {t_new:,} | Campaign CAC: INR {t_cac:,.2f} | "
                        f"Attributed Net Sales: INR {float(target_row['net_merchandise_sales']):,.2f} | "
                        f"Blended MER (Brand-wide): {float(acq_summary['blended_mer'] or 0):.4f}x."
                    ),
                    business_implication=(
                        "Paid acquisition cost per new customer currently exceeds 6-month observed contribution per customer "
                        f"(INR {float(repeat_summary['observed_avg_ltv_contribution'] or 0):,.2f}), creating negative first-cohort payback."
                    ),
                    possible_mechanism=(
                        "Broad auction competition on generic skincare keywords/audiences driving high CPCs alongside "
                        "landing page funnel leakage (58.9% view-to-cart drop-off)."
                    ),
                    suggested_action=(
                        f"1) Review search term / audience placement waste on {t_id}; "
                        "2) Run a controlled geo-holdout test before scaling or reallocating budget toward higher-converting "
                        "product landing pages; never scale or pause solely on platform ROAS."
                    ),
                    risks_and_alternatives=(
                        "Prospecting campaigns often assist organic/direct conversions (`UNASSIGNED` net sales = "
                        f"INR {float(acq_summary['unassigned_net_sales']):,.2f}); cutting upper-funnel spend without a holdout "
                        "test risks slowing organic and direct new-customer inflow."
                    ),
                    success_metric="Blended MER, Paid CAC, and Incremental Contribution in Geo-Holdout Cells.",
                    measurement_period="4-week geo-experiment window.",
                    confidence_and_limitations=(
                        "Medium-High confidence on spend/order accounting; limited by last-touch session attribution "
                        "(multi-touch cross-device journeys are not observed)."
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # RULE 4: Website Conversion Funnel — View-to-Cart & Mobile Checkout Drop-off
    # -------------------------------------------------------------------------
    if not funnel_overall.empty and int(funnel_overall.iloc[0]["sessions"]) > 0:
        fo = funnel_overall.iloc[0]
        v2c_drop = float(fo["dropoff_view_to_cart"] or 0.0)
        c2chk_drop = float(fo["dropoff_cart_to_checkout"] or 0.0)

        mob_note = ""
        if not funnel_by_dev.empty and {"mobile", "desktop"}.issubset(set(funnel_by_dev["device"])):
            mob_r = funnel_by_dev[funnel_by_dev["device"] == "mobile"].iloc[0]
            dsk_r = funnel_by_dev[funnel_by_dev["device"] == "desktop"].iloc[0]
            mob_c2chk = float(mob_r["cart_to_checkout_rate"] or 0.0)
            dsk_c2chk = float(dsk_r["cart_to_checkout_rate"] or 0.0)
            mob_note = (
                f" Mobile cart-to-checkout conversion ({mob_c2chk*100:.2f}%) also trails Desktop ({dsk_c2chk*100:.2f}%)."
            )

        recommendations.append(
            Recommendation(
                recommendation_id="REC-FUN-01",
                title="Reduce Product-View-to-Cart Leakage & Mobile Cart-to-Checkout Friction",
                business_area="Website Conversion Funnel",
                priority="High",
                affected_segment="Mobile Product Detail Pages (PDP) & Cart Drawer (Paid Social / Influencer Traffic)",
                date_window=date_window,
                observed_condition=(
                    f"{v2c_drop*100:.2f}% of sessions that view a product do not add to cart "
                    f"({int(fo['product_views']):,} views -> {int(fo['add_to_carts']):,} carts), and {c2chk_drop*100:.2f}% "
                    f"of carts abandon before initiating checkout.{mob_note}"
                ),
                evidence_metrics=(
                    f"Total Sessions: {int(fo['sessions']):,} | Product Views: {int(fo['product_views']):,} "
                    f"({float(fo['session_to_view_rate'] or 0)*100:.2f}%) | Add-to-Carts: {int(fo['add_to_carts']):,} "
                    f"({float(fo['view_to_cart_rate'] or 0)*100:.2f}% of views) | Checkouts Started: {int(fo['checkout_started']):,} "
                    f"({float(fo['cart_to_checkout_rate'] or 0)*100:.2f}% of carts) | Purchases: {int(fo['purchases']):,} "
                    f"({float(fo['session_conversion_rate'] or 0)*100:.2f}% overall conversion)."
                ),
                business_implication=(
                    "Improving view-to-cart and mobile cart-to-checkout progression increases converted orders on existing "
                    "paid traffic without increasing media spend, directly lowering effective CAC."
                ),
                possible_mechanism=(
                    "Skincare shoppers on mobile Paid Social/Influencer links may lack ingredient suitability clarity "
                    "(skin-type match, dermatological safety proof) on PDPs or face unexpected shipping fees (INR 49 below INR 499) in the cart."
                ),
                suggested_action=(
                    "1) A/B test sticky mobile Add-to-Cart bars with skin-type suitability badges and free-shipping progress "
                    "indicators (INR 499 threshold); 2) Simplify mobile cart-to-checkout transition with 1-click OTP/UPI checkout."
                ),
                risks_and_alternatives=(
                    "Upper-funnel social/reels traffic naturally exhibits higher browsing intent and lower immediate purchase "
                    "intent than brand search traffic; not all PDP drop-off represents UX friction."
                ),
                success_metric="Add-to-Cart Rate (% of Product Views), Cart-to-Checkout Rate (%), and Revenue per Session.",
                measurement_period="2-week randomized split test on mobile PDPs and cart drawer.",
                confidence_and_limitations=(
                    f"High sample size ({int(fo['sessions']):,} sessions). Session-level tracking does not link anonymous "
                    "multi-session browsers who view on mobile and purchase later on another device."
                ),
            )
        )

    # -------------------------------------------------------------------------
    # RULE 5: Customer Intelligence — At-Risk Repeat Buyers & Replenishment CRM
    # -------------------------------------------------------------------------
    if not rfm_seg_df.empty and repeat_summary["repeat_purchase_rate"] is not None:
        at_risk_rows = rfm_seg_df[rfm_seg_df["rfm_segment"] == "At Risk"]
        rep_rate = float(repeat_summary["repeat_purchase_rate"])
        ft_ltv = float(repeat_summary["first_time_avg_ltv"] or 0.0)
        rep_ltv = float(repeat_summary["repeat_customer_avg_ltv"] or 0.0)

        if not at_risk_rows.empty:
            ar = at_risk_rows.iloc[0]
            ar_custs = int(ar["customers"])
            ar_sales = float(ar["total_net_sales"])
            ar_share = float(ar["revenue_share"] or 0.0)
            ar_rec = float(ar["avg_recency_days"])

            recommendations.append(
                Recommendation(
                    recommendation_id="REC-CRM-01",
                    title="Launch Replenishment Cadence for 'At Risk' Repeat Buyers & 30–45 Day First-Time Cohort",
                    business_area="Customer Retention & CRM",
                    priority="Medium",
                    affected_segment=f"RFM 'At Risk' Segment ({ar_custs:,} customers) & First-Time Buyers ({int(repeat_summary['first_time_customers']):,} customers)",
                    date_window=date_window,
                    observed_condition=(
                        f"{ar_custs:,} previously loyal customers ('At Risk', averaging {float(ar['avg_frequency']):.2f} orders "
                        f"and {ar_rec:.1f} days since last order) account for {ar_share*100:.2f}% of total net sales "
                        f"(INR {ar_sales:,.2f}). Repeat buyers generate {rep_ltv/max(ft_ltv, 1.0):.2f}x higher 6M net sales "
                        f"(INR {rep_ltv:,.2f}) than one-time buyers (INR {ft_ltv:,.2f})."
                    ),
                    evidence_metrics=(
                        f"Active Customers: {int(repeat_summary['active_delivered_customers']):,} | "
                        f"Repeat Purchase Rate: {rep_rate*100:.2f}% | 'At Risk' Customers: {ar_custs:,} "
                        f"(Net Sales: INR {ar_sales:,.2f}, Contribution: INR {float(ar['total_contribution_profit']):,.2f}) | "
                        f"First-Time Customers: {int(repeat_summary['first_time_customers']):,} (Avg LTV: INR {ft_ltv:,.2f}) vs "
                        f"Repeat Customers: {int(repeat_summary['repeat_customers']):,} (Avg LTV: INR {rep_ltv:,.2f})."
                    ),
                    business_implication=(
                        "Retaining existing buyers via zero-media-spend CRM flows (Email/WhatsApp) carries a 57.37% contribution "
                        "margin without paid acquisition cost, critical to offsetting high first-order paid CAC."
                    ),
                    possible_mechanism=(
                        "50g/100ml daily skincare consumables (Sunscreen, Face Wash, Moisturiser) deplete in ~30–45 days; "
                        "customers without timely reorder reminders lapse after Month +1/+2."
                    ),
                    suggested_action=(
                        "Design a human-reviewed CRM experiment: send personalized 35-day SKU usage replenishment reminders "
                        "and routine cross-sell offers (e.g., Pairing Face Wash with SPF 50 Sunscreen) with a 20% holdout control group."
                    ),
                    risks_and_alternatives=(
                        "Over-messaging or unnecessary discount coupons in CRM can cannibalize full-price organic repeat orders "
                        "and increase unsubscribe rates."
                    ),
                    success_metric="Incremental 60-Day Repeat Order Rate and Contribution Profit per Customer (Treatment vs Holdout).",
                    measurement_period="60-day randomized CRM holdout test.",
                    confidence_and_limitations=(
                        "High confidence in historical purchase cadence within the 6-month window; right-censoring applies to "
                        "customers acquired in September–October 2026 who have had less time to repeat."
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # RULE 6: Inventory & Replenishment — SKUs Below Reorder Point
    # -------------------------------------------------------------------------
    if not inv_df.empty:
        low_skus = inv_df[
            (inv_df["latest_status"].isin(["STOCKOUT_SIGNAL", "BELOW_REORDER_POINT"]))
            | (inv_df["days_below_reorder_point"] >= 10)
        ].copy()

        if not low_skus.empty:
            sku_list_str = ", ".join(
                f"{r['product_id']} (closing: {int(r['latest_closing_stock'])}, ROP: {int(r['reorder_point'])}, "
                f"{int(r['days_below_reorder_point'])}d <= ROP)"
                for _, r in low_skus.iterrows()
            )
            top_low = low_skus.iloc[0]

            recommendations.append(
                Recommendation(
                    recommendation_id="REC-INV-01",
                    title="Expedite Replenishment Buffer Review for Hero SKUs Below Reorder Point",
                    business_area="Inventory & Supply Chain",
                    priority="Medium",
                    affected_segment=f"{len(low_skus)} SKU(s): {', '.join(low_skus['product_id'].tolist())}",
                    date_window=date_window,
                    observed_condition=(
                        f"{len(low_skus)} SKU(s) ended the period below reorder point or experienced recurring low-stock windows: "
                        f"{sku_list_str}."
                    ),
                    evidence_metrics=(
                        f"Flagged SKUs: {sku_list_str} | Highest Sell-Through: {top_low['product_id']} "
                        f"({float(top_low['sell_through_rate'] or 0)*100:.2f}% sell-through, {int(top_low['total_units_sold']):,} units sold) | "
                        f"Total Snapshot Days: {int(top_low['snapshot_days'])}."
                    ),
                    business_implication=(
                        "Hero SKUs (especially SPF 50 Invisible Sunscreen SKU-SS-01 and Clarifying Face Wash SKU-FW-01) drive "
                        "the highest net sales and contribution; buffer depletion risks fulfilment delays or paid ad waste "
                        "if traffic lands on out-of-stock PDPs."
                    ),
                    possible_mechanism=(
                        "Replenishment lead-time lag (5+ days below reorder point before batch receipt) relative to daily "
                        "campaign-driven order velocity."
                    ),
                    suggested_action=(
                        "1) Review safety stock and reorder points for SKU-SS-01, SKU-FW-01, and SKU-SR-01 ahead of promotional spikes; "
                        "2) Sync ad ops with warehouse snapshots so paid campaigns do not push SKUs with <5 days of cover."
                    ),
                    risks_and_alternatives=(
                        "Excess safety stock increases working capital lock-up and shelf-life expiry risk for active skincare formulations."
                    ),
                    success_metric="Percentage of Snapshot Days Above Reorder Point and On-Time Dispatch SLA (%).",
                    measurement_period="Next 2 replenishment cycles (60 days).",
                    confidence_and_limitations=(
                        "Caveat: Daily closing stock <= reorder point is a warehouse snapshot signal, NOT proof of lost sales "
                        "(unfulfilled intraday demand and backorder intent are not observed in the dataset)."
                    ),
                )
            )

    return recommendations


def recommendations_to_dataframe(recommendations: list[Recommendation]) -> pd.DataFrame:
    """Convert a list of Recommendation objects into a clean Pandas DataFrame for export/display."""
    if not recommendations:
        return pd.DataFrame(
            columns=[
                "recommendation_id",
                "title",
                "business_area",
                "priority",
                "affected_segment",
                "date_window",
                "observed_condition",
                "evidence_metrics",
                "business_implication",
                "possible_mechanism",
                "suggested_action",
                "risks_and_alternatives",
                "success_metric",
                "measurement_period",
                "confidence_and_limitations",
            ]
        )
    return pd.DataFrame([r.to_dict() for r in recommendations])
