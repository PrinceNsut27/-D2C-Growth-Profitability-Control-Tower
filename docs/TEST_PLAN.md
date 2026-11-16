# Test Plan & Automated Verification Evidence

All tests are executed via `pytest` (`python -m pytest -v`). Every test module is deterministic and self-contained.

---

## 1. Automated Test Suite Matrix (`23 / 23 Passed`)

| Test File | Test Function | Scope & Verification Target | Status |
|---|---|---|---|
| `tests/test_validation.py` | `test_deterministic_reproducibility` | Fixed seed (`seed=99`) produces bit-for-bit identical DataFrames across all 9 tables | `PASSED` |
| `tests/test_validation.py` | `test_generated_schema_and_clean_validation` | All 9 tables match `EXPECTED_COLUMNS` and pass all 61 validation checks with 0 rejected rows | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_duplicate_primary_keys` | Duplicate PK rows are caught and logged in `rejected_rows` with exact reason | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_missing_mandatory_columns` | Missing required schema columns fail validation immediately | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_negative_values_and_invalid_currency` | Negative spend, zero quantity, and non-`INR` currency codes are flagged and rejected | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_invalid_dates_and_foreign_keys` | Unparseable timestamps and orphan foreign keys (`customer_id`) are flagged and rejected | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_impossible_lifecycle_and_discount_mismatch` | Contradictory lifecycle transitions (`cancelled` order with `delivered` shipment) and header-vs-line discount mismatches are caught | `PASSED` |
| `tests/test_validation.py` | `test_validation_catches_bad_inventory_arithmetic_and_funnel_sequence` | Impossible stock arithmetic (`opening + received - sold != closing`) and out-of-sequence funnel flags are caught | `PASSED` |
| `tests/test_pipeline.py` | `test_anti_fanout_with_multiple_shipments_and_returns` | Injecting split shipments on an order preserves `1 row per order_id` and identical `net_merchandise_sales` | `PASSED` |
| `tests/test_pipeline.py` | `test_end_to_end_data_engineering_pipeline` | Full `generate -> ingest -> validate -> canonical transform -> DuckDB` workflow in isolated `tmp_path` | `PASSED` |
| `tests/test_metrics.py` | `test_hand_calculated_business_performance_and_contribution` | Hand-calculated 4-order fixture (`delivered`, `partially_refunded`, `rto`, `cancelled`) verifies exact GMV, discounts, refunds, Net Sales (`₹1,400`), AOV (`₹700`), COGS (`₹300`), RTO shipping (`₹120`), payment fees (`₹46.24`), Contribution (`₹803.76`), RTO rate (`33.33%`), and Return rate (`50.0%`) | `PASSED` |
| `tests/test_metrics.py` | `test_zero_denominator_and_empty_dataset_edge_cases` | Empty DataFrames return `None` (`NA`) for AOV, RTO rate, Return rate, Contribution margin %, and funnel conversion rates | `PASSED` |
| `tests/test_metrics.py` | `test_funnel_stage_rates_and_dropoffs` | Hand-crafted session fixture verifies stage conversion and drop-off rates | `PASSED` |
| `tests/test_metrics.py` | `test_inventory_sell_through_and_stockout_signals` | Verifies sell-through formula (`sold / (opening + received)`) and `STOCKOUT_SIGNAL` classification | `PASSED` |
| `tests/test_metrics.py` | `test_sql_and_python_full_reconciliation` | Executes DuckDB SQL queries and reconciles all 23 KPIs against Python outputs within `0.01` tolerance | `PASSED` |
| `tests/test_attribution.py` | `test_cac_roas_and_mer_alignment_and_distinction` | Verifies Blended CAC (`₹150`), Paid CAC (`₹300`), Attributed ROAS (`3.0x`), Blended MER (`4.6667x`), and unassigned organic sales separation | `PASSED` |
| `tests/test_attribution.py` | `test_zero_spend_and_zero_new_customers_return_na` | Verifies zero spend returns `None`/`NaN` for ROAS, MER, and unpaid channel CAC | `PASSED` |
| `tests/test_cohorts.py` | `test_rfm_and_repeat_purchase_summary` | Verifies customer recency days, frequency, monetary totals, and repeat purchase rate (`33.33%`) | `PASSED` |
| `tests/test_cohorts.py` | `test_monthly_cohort_retention_matrix` | Verifies Month 0 (`100%`) and Month +1 (`50%`) cohort retention pivot matrix | `PASSED` |
| `tests/test_recommendations_and_dashboard.py` | `test_recommendation_engine_generates_evidence_backed_rules` | Verifies all 6 rule categories trigger with required evidence, mechanism, risk, and measurement fields, plus empty-slice safety | `PASSED` |
| `tests/test_recommendations_and_dashboard.py` | `test_global_filters_and_no_duplicate_revenue` | Verifies channel, payment mode, SKU, RFM segment, empty-date, boundary-date (`2026-05-01` and `2026-10-31`), and CSV export round-trip integrity | `PASSED` |
| `tests/test_recommendations_and_dashboard.py` | `test_time_series_trends_and_operations_breakdowns` | Verifies Weekly, Monthly, and Daily time-series sums reconcile with total Net Merchandise Sales | `PASSED` |
| `tests/test_recommendations_and_dashboard.py` | `test_streamlit_app_renders_all_pages_without_error` | Uses `streamlit.testing.v1.AppTest` to render all 9 dashboard views and verify synthetic-data banner presence and zero runtime exceptions | `PASSED` |

---

## 2. Reproduction Command
```bash
python -m pytest -v
```
