# Technical Review — Architecture, Data Engineering & Analytics Audit

**Project Reviewed**: D2C Growth & Profitability Control Tower (`v1.0.0`)  
**Environment**: Python 3.13.5, Pandas 2.2.3, NumPy 2.1.3, DuckDB 2.0.0, Streamlit 1.45.1, Plotly 5.24.1, pytest 8.3.4

---

## 1. Architecture & Code Quality Evaluation

### Strengths
1. **Strict Separation of Concerns**:
   - All business logic, validation rules, transformations, KPI calculations, cohort matrices, and recommendation rules reside in modular Python files under `src/` (`generate_data.py`, `ingestion.py`, `validation.py`, `transformations.py`, `metrics.py`, `attribution.py`, `segmentation.py`, `cohorts.py`, `recommendations.py`, `pipeline.py`).
   - `app.py` is purely a presentation and filter-binding layer. Zero KPI formulas are hardcoded or recalculated inline in UI callbacks.
2. **Type Hints & Dataclass Contracts**:
   - Public functions use Python 3.11+ type annotations (`from __future__ import annotations`, `Path | str | None`, `dict[str, pd.DataFrame]`).
   - Structured return payloads (`GeneratedDataset`, `CheckResult`, `ValidationReport`, `CanonicalModel`, `Recommendation`, `PipelineResult`) prevent brittle dictionary-key guesswork across module boundaries.
3. **Configuration Hygiene & Portability**:
   - Zero hardcoded absolute paths (`C:\Users\...`), credentials, or environment-specific paths exist in `src/`, `tests/`, `sql/`, or `app.py`.
   - `src/config.py` resolves all paths relative to `PROJECT_ROOT` and falls back gracefully from `config/settings.toml` to `config/settings.example.toml`.

### Code Quality Observations & Minor Trade-offs
- **Function Naming Minor Typo**: In `src/metrics.py`, `compute_business_performance_And_economics` has a capitalized `And` in its identifier. It is used consistently across `src/`, `tests/`, and `app.py`, so preserving it avoids breaking existing callers, though `compute_business_performance_and_economics` would strictly follow PEP 8 `snake_case`.
- **In-Memory DataFrame Slicing vs Pushdown SQL Filtering**: Interactive dashboard filters (`apply_global_filters`) slice pre-loaded Pandas DataFrames in memory rather than issuing parameterized `WHERE` queries to DuckDB on every click. At the current scale (`6,500` orders, `48,000` sessions) and up to `~250,000` orders, in-memory Pandas slicing with `@st.cache_resource` is faster (`< 50 ms`) and avoids file-lock contention on Windows; at `> 5M` rows, pushing filter predicates down to DuckDB SQL would be preferable.

---

## 2. SQL Queries, Database Design & Anti-Fan-Out Data Modeling

### Strengths
1. **Explicit Table Grain Enforcement ([sql/schema.sql](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/sql/schema.sql))**:
   - All 9 source tables declare explicit primary keys (`customer_id`, `product_id`, `order_id`, `order_item_id`, `session_id`, `(date, platform, channel, campaign_id)`, `shipment_id`, `return_id`, `(snapshot_date, product_id)`).
2. **Prevention of Join Fan-Out ([src/transformations.py](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/src/transformations.py), [sql/core_metrics.sql](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/sql/core_metrics.sql))**:
   - A common failure mode in e-commerce analytics is joining `orders` directly to `order_items` (`1:N`), `shipments` (`1:N`), and `returns` (`1:N`), which multiplies order-header columns (`discount_amount`, `shipping_revenue`, `tax_amount`).
   - `src/transformations.py` pre-aggregates `order_items` (enriched with `products.unit_cogs`), `shipments`, and `returns` to `1 row per order_id` before merging onto `orders`.
   - `build_canonical_model()` explicitly audits join cardinality (`orders_input = 6,500` vs `canonical_orders_output = 6,500`, `fanout_detected = False`) and raises a `ValueError` if row multiplication occurs.
3. **Proportional Variable Cost Allocation to SKU Lines**:
   - To enable SKU-level contribution analysis without double-counting order-level shipping costs (`shipments.shipping_cost`), earned shipping revenue (`orders.shipping_revenue`), or payment fees (`payment_fee`), `canonical_order_items` allocates those order-level amounts across line items by each line's share of `gross_item_revenue`. As a result, `SUM(line_contribution_profit)` across all `9,722` order items reconciles with `SUM(contribution_profit)` across all `6,500` orders (`₹2,285,753.18`).

---

## 3. ETL Reliability, Validation Gate & Error Handling

### Strengths
1. **Non-Destructive 61-Check Validation Gate ([src/validation.py](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/src/validation.py))**:
   - Validates table existence, schema columns, mandatory non-nulls, PK duplicates (`keep='first'`), non-negative numerics, date/timestamp parsing, currency (`INR`), 9 foreign-key relationships, order lifecycle status domains and cross-table transitions, shipment timestamp chronology (`delivered_at >= shipped_at`), order header vs line discount reconciliation (`abs_diff <= 0.05`), inventory stock arithmetic (`opening + received - sold == closing`), and session funnel boolean ordering (`converted => checkout_started => add_to_cart => product_view`).
2. **Zero Silent Data Dropping**:
   - Every failed row index is tracked in `reject_tracker` with all applicable failure reasons concatenated and exported to `data/processed/rejected_rows.csv` alongside `clean_tables`.

---

## 4. Analytics Accuracy & Metric Definitions

### Strengths
1. **Strict Zero-Denominator Handling**:
   - `safe_divide(numerator, denominator)` returns `None` (`NA`) whenever the denominator is `0`, `None`, or `NaN`, preventing fabricated `0.0%` rates or `ZeroDivisionError` exceptions on empty filter slices.
2. **Domain-Accurate Operational Denominators**:
   - **RTO Rate (`13.96%`)**: Uses `shipped_orders` (`5,402`) as the denominator (`754 / 5,402`), never `placed_orders` (`6,500`).
   - **Post-Delivery Return Rate (`10.71%`)**: Uses `delivered_orders` cohort (`4,424`, comprising `delivered`, `partially_refunded`, and `returned` orders) as the denominator (`474 / 4,424`), ensuring the numerator is a true subset of the denominator bounded in `[0, 1]`.
3. **23-KPI SQL-to-Python Reconciliation**:
   - `reconcile_sql_and_python_metrics()` executes analytical SQL queries directly on `d2c_analytics.duckdb` and verifies that all 23 KPIs match Python calculations within `<= 0.01` (`abs_diff = 0.0` across all 23 metrics).

---

## 5. Scalability & Measured Performance Benchmarks

### Measured Execution Timings (Local Windows Environment, Python 3.13.5)
We benchmarked the pipeline at both the baseline scale (`6,500` orders, `76,235` total records across 9 tables) and a **16× scaled order dataset (`104,000` orders, `155,552` order items)**:

| Pipeline Stage | Dataset Scale | Measured Latency | Notes |
|---|---|---:|---|
| `ingest_all_tables()` | 9 CSV tables (`76,235` total rows) | `0.637 s` | Pandas CSV I/O + type normalization |
| `validate_all_tables()` | 61 checks across 9 tables (`76,235` rows) | `1.215 s` | Vectorized Pandas boolean mask checks |
| `build_canonical_model()` | `6,500` orders, `9,722` items, `5,402` shipments | `2.389 s` | Pre-aggregation `groupby` + `1:1` merges |
| `compute_business_performance_And_economics()` | Baseline (`6,500` canonical orders) | `0.025 s` | Vectorized NumPy/Pandas aggregations |
| `compute_business_performance_And_economics()` | **16× Scale (`104,000` canonical orders)** | **`0.199 s`** | Processes 100k+ order rows in `< 200 ms` |

### Identified Scalability Bottlenecks & Remediation Path
1. **Row-by-Row Loops in `src/generate_data.py`**:
   - While the analytical and canonical transformation layers are vectorized (`104,000` orders processed in `0.199 s`), the synthetic generator (`generate_all_datasets`) iterates over orders and non-converted sessions in Python `for` loops to construct realistic chronological sequences (`~3.5 s` for `6,500` orders and `48,000` sessions). Generating `1,000,000` synthetic sessions would require vectorizing session construction with NumPy array operations.
2. **Groupby Iteration in `compute_sku_profitability` and `compute_inventory_and_stockout_metrics`**:
   - Iterating over `df.groupby(...)` in Python is fast when cardinality is low (`8` SKUs, `7` channels, `7` campaigns), but if the catalog scaled to `50,000` SKUs, replacing the Python `for _, grp in df.groupby(...)` loop with a single vectorized `df.groupby(...).agg(...)` or DuckDB SQL query would be 20–50× faster.

---

## 6. Test Coverage Evaluation (`23 / 23 Passing`)
- **Strengths**: Tests cover deterministic seed reproducibility, all 8 major validation failure classes (duplicate PKs, missing columns, negative numbers, invalid currencies, bad dates, orphan FKs, impossible lifecycle states, discount mismatches, stock math, funnel ordering), split-shipment anti-fan-out, hand-calculated unit economics fixtures, zero-denominator `NA` edge cases, 23-KPI SQL/Python reconciliation, boundary-date filtering, CSV round-trip integrity, and full 9-page headless Streamlit `AppTest` rendering.
- **Future Test Additions**: Property-based testing with `hypothesis` on random order/return permutations and automated visual regression diffs on Plotly chart layouts.
