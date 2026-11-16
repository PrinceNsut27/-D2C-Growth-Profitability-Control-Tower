"""Data engineering and analytics orchestration pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import duckdb
import pandas as pd

from src.attribution import (
    compute_acquisition_summary,
    compute_campaign_performance,
    compute_channel_acquisition_and_profitability,
)
from src.cohorts import compute_monthly_cohort_retention
from src.config import PROJECT_ROOT, load_settings
from src.generate_data import generate_from_config
from src.ingestion import ingest_all_tables
from src.metrics import (
    compute_business_performance_And_economics,
    compute_cod_vs_prepaid_metrics,
    compute_funnel_metrics,
    compute_inventory_and_stockout_metrics,
    compute_sku_profitability,
    reconcile_sql_and_python_metrics,
)
from src.recommendations import generate_recommendations, recommendations_to_dataframe
from src.segmentation import (
    compute_repeat_purchase_and_ltv_summary,
    compute_rfm_table,
    summarize_rfm_segments,
)
from src.transformations import (
    CanonicalModel,
    build_canonical_model,
    load_into_duckdb,
    save_processed_artifacts,
)
from src.validation import ValidationReport, validate_all_tables


@dataclass
class PipelineResult:
    """Result container for data engineering and analytics pipeline execution."""

    validation_report: ValidationReport
    canonical_model: CanonicalModel
    duckdb_path: Path
    processed_paths: dict[str, Path]
    duckdb_table_counts: dict[str, int]
    analytics_outputs: dict[str, Any]


def run_data_engineering_pipeline(
    regenerate_data: bool = False,
    data_dir: Path | str | None = None,
    processed_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    config_path: Path | str | None = None,
    write_artifacts: bool = True,
) -> PipelineResult:
    """Execute Milestone 1–3 pipeline: (optional) generate -> ingest -> validate -> transform -> DuckDB -> analytics."""
    settings = load_settings(config_path)
    if regenerate_data:
        generate_from_config(config_path=config_path, output_dir=data_dir)

    raw_tables = ingest_all_tables(data_dir=data_dir, config_path=config_path)
    expected_curr = str(settings.get("project", {}).get("currency", "INR"))
    val_report = validate_all_tables(raw_tables, expected_currency=expected_curr)

    costs_cfg = settings.get("costs", {})
    prepaid_rate = float(costs_cfg.get("prepaid_payment_fee_rate", 0.02))
    cod_fixed = float(costs_cfg.get("cod_payment_fee_fixed", 25.0))

    canonical_model = build_canonical_model(
        val_report.clean_tables,
        prepaid_fee_rate=prepaid_rate,
        cod_fee_fixed=cod_fixed,
    )

    if db_path is not None:
        duckdb_file = Path(db_path)
    else:
        rel_db = settings.get("database", {}).get("path", "data/processed/d2c_analytics.duckdb")
        duckdb_file = Path(rel_db) if Path(rel_db).is_absolute() else (PROJECT_ROOT / rel_db)

    processed_paths: dict[str, Path] = {}
    if write_artifacts or not duckdb_file.exists():
        duckdb_file = load_into_duckdb(canonical_model, db_path=duckdb_file)
        processed_paths = save_processed_artifacts(
            canonical_model,
            processed_dir=processed_dir,
            validation_summary_df=val_report.to_summary_dataframe(),
            rejected_rows_df=val_report.rejected_rows,
        )

    # Compute analytics layer outputs
    can_orders = canonical_model.canonical_orders
    can_items = canonical_model.canonical_order_items
    clean = val_report.clean_tables

    exec_kpis = compute_business_performance_And_economics(can_orders)
    acq_summary = compute_acquisition_summary(can_orders, clean["marketing_spend"])
    channel_df = compute_channel_acquisition_and_profitability(can_orders, clean["marketing_spend"])
    campaign_df = compute_campaign_performance(can_orders, clean["marketing_spend"], include_unassigned=True)
    funnel_overall_df = compute_funnel_metrics(clean["sessions"])
    funnel_ch_dev_df = compute_funnel_metrics(clean["sessions"], group_cols=["channel", "device"])
    sku_df = compute_sku_profitability(can_items)
    cod_prepaid_df = compute_cod_vs_prepaid_metrics(can_orders, group_cols=["payment_mode"])
    cod_tier_df = compute_cod_vs_prepaid_metrics(can_orders, group_cols=["payment_mode", "city_tier"])
    inv_df = compute_inventory_and_stockout_metrics(clean["inventory_snapshots"], clean["products"])
    rfm_df = compute_rfm_table(can_orders)
    rfm_summary_df = summarize_rfm_segments(rfm_df)
    repeat_summary = compute_repeat_purchase_and_ltv_summary(can_orders, clean["customers"])
    cohorts_res = compute_monthly_cohort_retention(can_orders)
    recs_list = generate_recommendations(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        products=clean["products"],
        customers=clean["customers"],
    )
    recs_df = recommendations_to_dataframe(recs_list)
    sql_reconciliation = reconcile_sql_and_python_metrics(
        db_path=str(duckdb_file),
        canonical_orders=can_orders,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
    )

    # Save analytical summary tables to processed_dir
    out_dir = Path(processed_dir) if processed_dir is not None else (PROJECT_ROOT / "data" / "processed")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_exports = {
        "channel_performance": channel_df,
        "campaign_performance": campaign_df,
        "funnel_by_channel_device": funnel_ch_dev_df,
        "sku_profitability": sku_df,
        "cod_vs_prepaid": cod_prepaid_df,
        "inventory_health": inv_df,
        "rfm_segments": rfm_summary_df,
        "cohort_retention_long": cohorts_res["cohort_long"],
        "recommendations": recs_df,
        "sql_python_reconciliation": sql_reconciliation["comparisons"],
    }
    if write_artifacts:
        for name, df_export in summary_exports.items():
            p = out_dir / f"{name}.csv"
            df_export.to_csv(p, index=False)
            processed_paths[name] = p

    # Query DuckDB table counts to verify persistence
    table_counts: dict[str, int] = {}
    con = duckdb.connect(str(duckdb_file), read_only=True)
    try:
        tables_res = con.execute("SHOW TABLES").fetchall()
        for (tname,) in tables_res:
            cnt = con.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
            table_counts[str(tname)] = int(cnt)
    finally:
        con.close()

    analytics_outputs = {
        "executive_kpis": exec_kpis,
        "acquisition_summary": acq_summary,
        "channel_performance": channel_df,
        "campaign_performance": campaign_df,
        "funnel_overall": funnel_overall_df,
        "funnel_by_channel_device": funnel_ch_dev_df,
        "sku_profitability": sku_df,
        "cod_vs_prepaid": cod_prepaid_df,
        "cod_by_city_tier": cod_tier_df,
        "inventory_health": inv_df,
        "rfm_table": rfm_df,
        "rfm_segments": rfm_summary_df,
        "repeat_purchase_summary": repeat_summary,
        "cohorts": cohorts_res,
        "recommendations": recs_list,
        "recommendations_df": recs_df,
        "sql_reconciliation": sql_reconciliation,
    }

    return PipelineResult(
        validation_report=val_report,
        canonical_model=canonical_model,
        duckdb_path=duckdb_file,
        processed_paths=processed_paths,
        duckdb_table_counts=table_counts,
        analytics_outputs=analytics_outputs,
    )


if __name__ == "__main__":
    result = run_data_engineering_pipeline(regenerate_data=False)
    ao = result.analytics_outputs
    ek = ao["executive_kpis"]
    aq = ao["acquisition_summary"]
    rp = ao["repeat_purchase_summary"]
    fo = ao["funnel_overall"].iloc[0]

    print("=== VALIDATION & RECONCILIATION ===")
    print(f"Validation Passed: {result.validation_report.passed} ({len(result.validation_report.checks)} checks)")
    print(f"SQL vs Python Reconciled: {ao['sql_reconciliation']['reconciled']} (23 KPIs compared)")
    print("\n=== A. BUSINESS PERFORMANCE & UNIT ECONOMICS ===")
    print(f"Placed Orders: {ek['placed_orders']:,} | Shipped: {ek['shipped_orders']:,} | Delivered (Cohort): {ek['delivered_orders']:,} | Retained Delivered: {ek['retained_delivered_orders']:,}")
    print(f"Cancelled Orders: {ek['cancelled_orders']:,} ({ek['cancellation_rate']*100:.2f}%) | RTO Orders: {ek['rto_orders']:,} ({ek['rto_rate']*100:.2f}% of shipped) | Returned: {ek['returned_orders']:,} ({ek['return_rate']*100:.2f}% of delivered)")
    print(f"Placed GMV: INR {ek['placed_gmv']:,.2f} | Delivered Gross Rev: INR {ek['delivered_gross_revenue']:,.2f}")
    print(f"Delivered Discounts: INR {ek['delivered_discounts']:,.2f} | Refunds: INR {ek['refund_amount']:,.2f} | Net Merchandise Sales: INR {ek['net_merchandise_sales']:,.2f}")
    print(f"AOV (Delivered): INR {ek['aov']:,.2f} | Delivered Units Sold: {ek['delivered_units']:,} (Placed Units: {ek['placed_units']:,})")
    print(f"Net COGS: INR {ek['net_cogs']:,.2f} | Gross Profit: INR {ek['gross_profit']:,.2f} ({ek['gross_margin_pct']*100:.2f}%)")
    print(f"Shipping Cost: INR {ek['shipping_cost']:,.2f} (RTO Shipping Drag: INR {ek['rto_shipping_cost']:,.2f}) | Payment Fees: INR {ek['payment_fees']:,.2f}")
    print(f"Contribution Profit (CM2): INR {ek['contribution_profit']:,.2f} ({ek['contribution_margin_pct']*100:.2f}%)")
    print("\n=== B. MARKETING & ACQUISITION ===")
    print(f"Total Ad Spend: INR {aq['ad_spend']:,.2f} | Total New Customers: {aq['total_new_customers']:,} (Paid New Customers: {aq['paid_new_customers']:,})")
    print(f"Blended CAC: INR {aq['blended_cac']:,.2f} | Paid Channel CAC: INR {aq['paid_channel_cac']:,.2f}")
    print(f"Attributed Net Sales: INR {aq['attributed_net_sales']:,.2f} | Unassigned Net Sales: INR {aq['unassigned_net_sales']:,.2f}")
    print(f"Campaign-Attributed ROAS: {aq['attributed_roas']:.4f}x | Blended MER: {aq['blended_mer']:.4f}x")
    print("\n=== C. CONVERSION FUNNEL ===")
    print(f"Sessions: {fo['sessions']:,} -> Views: {fo['product_views']:,} ({fo['session_to_view_rate']*100:.2f}%) -> Add-to-Cart: {fo['add_to_carts']:,} ({fo['add_to_cart_rate']*100:.2f}% of sessions, {fo['view_to_cart_rate']*100:.2f}% of views) -> Checkout: {fo['checkout_started']:,} ({fo['cart_to_checkout_rate']*100:.2f}% of carts) -> Purchases: {fo['purchases']:,} ({fo['checkout_completion_rate']*100:.2f}% of checkouts, {fo['session_conversion_rate']*100:.2f}% overall)")
    print("\n=== E. CUSTOMER INTELLIGENCE ===")
    print(f"Active Delivered Customers: {rp['active_delivered_customers']:,} | First-Time: {rp['first_time_customers']:,} | Repeat: {rp['repeat_customers']:,} ({rp['repeat_purchase_rate']*100:.2f}%)")
    print(f"Observed Avg 6M LTV (Net Sales): INR {rp['observed_avg_ltv_net_sales']:,.2f} | First-Time Avg: INR {rp['first_time_avg_ltv']:,.2f} | Repeat Avg: INR {rp['repeat_customer_avg_ltv']:,.2f}")
