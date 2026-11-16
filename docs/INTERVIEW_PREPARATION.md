# Interview Preparation & Resume Guide

All figures and architectural details in this guide come directly from the codebase and the deterministic synthetic dataset (`seed = 42`, `2026-05-01` to `2026-10-31`) of the **D2C Growth & Profitability Control Tower**. Always state clearly in interviews that the dataset is a deterministic synthetic case study modeled on an Indian skincare D2C business.

---

## Three Verified Resume Bullet Options

1. **Data & Business Analytics Focus**:
   - Built an end-to-end **D2C Growth & Profitability Control Tower** in **Python, DuckDB, SQL, and Streamlit** across 9 relational tables (`6,500` orders, `48,000` sessions, `9,722` order lines), decomposing `₹6.75M` placed GMV into `₹3.95M` Net Merchandise Sales and `₹2.29M` (`57.87%`) CM2 Contribution Profit after discounts, COGS, refunds, payment fees, and COD Return-to-Origin (RTO) logistics costs.
2. **Analytics Engineering & Data Quality Focus**:
   - Engineered a fan-out-free canonical data pipeline with **61 automated validation checks**, non-destructive rejected-row quarantine, and **23-KPI SQL-to-Python reconciliation** (`pytest` suite: 23/23 passing), preventing multi-shipment and multi-return join multiplication while surfacing diagnostics across Paid CAC, Attributed ROAS vs. Blended MER, RFM segments, and monthly retention cohorts.
3. **Growth, Product & Operations Focus**:
   - Developed a 9-page interactive **Streamlit** decision-support dashboard and rule-based recommendation engine evaluating campaign margin erosion (`48.23%` flash-sale CM2 vs. `57.87%` baseline), Tier 2/3 COD RTO losses (`25.03%` COD RTO vs. `4.18%` Prepaid RTO), mobile funnel drop-offs (`58.92%` view-to-cart leakage), and SKU reorder-point alerts with human-in-the-loop experiment designs.

---

## 1. 30-Second Project Explanation

> "In Indian D2C e-commerce, growing order volume often masks unit-economics losses from deep promotional discounts, post-delivery refunds, and Cash-on-Delivery Return-to-Origin (RTO) courier charges. I built the **D2C Growth & Profitability Control Tower** using Python, DuckDB, SQL, and Streamlit to unify 9 operational and marketing datasets—covering 48,000 sessions and 6,500 orders in a deterministic synthetic case study.
>
> On the engineering side, it enforces 61 data-quality checks, pre-aggregates line items, shipments, and returns to the order grain so joins never duplicate revenue, and reconciles 23 KPIs between DuckDB SQL and Python. On the business side, it traces `₹6.75M` in placed GMV down to `₹3.95M` in Net Merchandise Sales and `₹2.29M` in CM2 Contribution Profit, automatically flagging issues like a `25.03%` COD RTO rate vs. `4.18%` on Prepaid and `48.23%` margin compression on flash-sale campaigns—paired with concrete experiment designs."

---

## 2. Two-Minute Business Explanation

> "When a small D2C brand scales paid ads on Meta and Google, the marketing dashboard might show rising order counts, while the founder sees shrinking cash in the bank. That happens because four different leaks occur between a placed order and actual contribution profit:
>
> 1. **Pre-shipment cancellations and COD RTOs**: Out of `6,500` placed orders (`₹6.75M` Placed GMV), `477` cancel before shipping (`7.34%`), and out of `5,402` shipped orders, `754` return undelivered as RTO (`13.96%`). Worse, on Cash-on-Delivery orders, the RTO rate is **25.03%**—and reaches **32.23% in Tier 3 cities**—compared to just **4.18%** on Prepaid orders. Every RTO order generates `₹0` revenue but costs the brand both forward and reverse courier freight (`₹95,217.95` total RTO shipping drag).
> 2. **Discounts and Post-Delivery Returns**: Among the `4,424` orders that physically deliver (`₹4.65M` Delivered Gross Revenue), promotional discounts take `₹284,604` and post-delivery customer returns (`10.71%` return rate) take `₹418,630` in refunds, leaving `₹3,949,726` in Net Merchandise Sales (`AOV ₹892.80`).
> 3. **Promo-Driven Margin Erosion**: By joining campaign tags with order-level variable costs, the dashboard shows that our 30%-off flash sale campaign (`CMP-META-FLASH-02`) has the lowest Contribution Margin in the portfolio (`48.23%` vs. `57.87%` overall) because deep discounts (`23.06%`) attract high-COD (`68.40%`), high-RTO (`19.70%`), low-repeat buyers.
> 4. **Repeat vs. One-Time Buyer Economics**: Across `2,466` active delivered customers, repeat buyers (`52.64%`) generate `₹2,269.74` in 6-month net sales vs. `₹859.25` for one-time buyers (`2.64x`). Identifying the `506` repeat buyers in the RFM **`At Risk`** segment (`₹1.03M` historical net sales, `117` days since last order) gives the retention team a concrete target for a 35-day skincare replenishment test."

---

## 3. Technical Architecture Explanation

The project is organized into six decoupled layers:
1. **Synthetic Data Generator (`src/generate_data.py`)**: Uses `np.random.default_rng(42)` to deterministically generate all 9 CSV tables (`customers`, `products`, `orders`, `order_items`, `sessions`, `marketing_spend`, `shipments`, `returns`, `inventory_snapshots`) in `data/raw/`.
2. **Ingestion Layer (`src/ingestion.py`)**: Loads CSVs with normalized string, boolean, and date types without dropping malformed rows.
3. **Validation Gate (`src/validation.py`)**: Runs 61 automated checks across schemas, primary keys, foreign keys, negative numbers, date chronology, header-vs-line discount reconciliation, inventory stock math, and funnel flag ordering. Invalid rows are isolated into `ValidationReport.rejected_rows` (`data/processed/rejected_rows.csv`), while valid rows pass into `clean_tables`.
4. **Anti-Fan-Out Canonical Transformation Layer (`src/transformations.py`)**: Pre-aggregates `order_items` (joined with `products.unit_cogs`), `shipments`, and `returns` to `1 row per order_id` before merging `1:1` onto `orders` to create `canonical_orders` (`6,500` rows) and `canonical_order_items` (`9,722` rows), persisting both raw and canonical tables into **DuckDB** (`data/processed/d2c_analytics.duckdb`).
5. **Dual SQL & Python Analytics Layer (`src/metrics.py`, `src/attribution.py`, `src/segmentation.py`, `src/cohorts.py`, `sql/core_metrics.sql`)**: Computes all metrics in Python and DuckDB SQL, verifying `23 / 23` KPI reconciliation within `0.01`.
6. **Recommendation Engine & Streamlit UI (`src/recommendations.py`, `app.py`)**: Evaluates 6 deterministic recommendation rules and renders 9 interactive dashboard views with 8 sidebar filters and CSV exports.

---

## 4. Explanation of DuckDB and ETL Choices

- **Why DuckDB over PostgreSQL or SQLite?**
  - **Local reproducibility**: Runs in-process from a single file (`d2c_analytics.duckdb`) with zero external server setup, so any reviewer can clone the repo and run `pytest` or `streamlit run app.py` immediately.
  - **Columnar OLAP execution**: Vectorized analytical execution handles aggregations, CTEs, `FULL OUTER JOIN`, and cohort queries much faster than row-oriented SQLite.
  - **Zero-copy Pandas integration**: Directly queries and registers Pandas DataFrames (`con.register`) while enforcing strict SQL DDL types (`DECIMAL(12,2)`, `TIMESTAMP`, composite primary keys).
- **Why Pre-Aggregate in ETL Instead of Joining Raw Tables in Every Query?**
  - In e-commerce schemas, `orders` (`1` row/order) has `1:N` relationships with `order_items`, `shipments`, and `returns`. Pre-aggregating each child fact table to `order_id` grain once in `src/transformations.py` guarantees that downstream queries and dashboard filters can never accidentally multiply order-header fields (`discount_amount`, `shipping_revenue`, `tax_amount`).

---

## 5. Explanation of CAC, ROAS, MER, and Contribution Margin

- **Blended CAC (`₹2,946.13`) vs. Paid Channel CAC (`₹4,705.41`)**:
  - A customer's acquisition cohort is defined by their **first delivered order** (`is_new_customer_order = True`).
  - **Paid Channel CAC** divides total paid media spend (`₹7,265,150.14`) by newly acquired customers whose first delivered order came from a paid campaign (`1,544` customers).
  - **Blended CAC** divides total paid media spend by **all** newly acquired customers across both paid and unpaid channels (`2,466` customers).
- **Campaign-Attributed ROAS (`0.2516x`) vs. Blended MER (`0.5437x`)**:
  - **Attributed ROAS** = Campaign-Attributed Net Merchandise Sales (`₹1,827,890.65`) $\div$ Paid Media Spend (`₹7,265,150.14`). It is strictly an observational last-touch ratio, not causal lift.
  - **Blended MER (Marketing Efficiency Ratio)** = Total Brand Net Merchandise Sales (`₹3,949,725.97`, which includes `₹2,121,835.32` from unassigned Organic Search, Direct, Email/CRM, and Marketplace orders) $\div$ Total Paid Media Spend (`₹7,265,150.14`).
- **Gross Profit (`70.25%`) vs. CM2 Contribution Profit (`57.87%`)**:
  - **Net Merchandise Sales (`₹3,949,725.97`)** = Delivered GMV (`₹4,652,960.00`) $-$ Delivered Discounts (`₹284,604.12`) $-$ Refunds (`₹418,629.91`).
  - **Gross Profit (`₹2,774,752.97`)** = Net Merchandise Sales $-$ Net Retained Product COGS (`₹1,174,973.00`).
  - **CM2 Contribution Profit (`₹2,285,753.18`)** = Gross Profit $+$ Earned Shipping Revenue (`₹40,033.00`) $-$ Total Courier Shipping Cost (`₹407,932.32`, including `₹95,217.95` RTO courier drag) $-$ Payment Processing Fees (`₹121,100.47`).

---

## 6. Five SQL Questions Based on This Project

### SQL Q1: How do you join `orders`, `order_items`, `shipments`, and `returns` in SQL without duplicating `orders.discount_amount`?
- **Answer**: Pre-aggregate each `1:N` table to `order_id` grain in separate CTEs (`items_agg`, `shipments_agg`, `returns_agg`) with `GROUP BY order_id`, and then `LEFT JOIN` those CTEs `1:1` onto `orders` on `order_id`.

### SQL Q2: Write the SQL expression for RTO Rate and explain why `WHERE is_shipped` is required in the denominator.
- **Answer**:
  ```sql
  CASE WHEN COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) > 0
       THEN ROUND(
           CAST(COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS DOUBLE)
           / COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END),
           4
       )
       ELSE NULL END AS rto_rate
  ```
  Pre-shipment cancelled orders (`477`) and unshipped `placed`/`confirmed` orders were never dispatched to a courier and cannot experience Return-to-Origin. Using `NULL` in the `ELSE` branch prevents division-by-zero errors and avoids fabricated `0.0` rates.

### SQL Q3: Why did you use a `FULL OUTER JOIN` between `orders_by_channel` and `spend_by_channel` in `sql/core_metrics.sql`?
- **Answer**: Unpaid channels (`Direct`, `Organic Search`, `Email/CRM`, `Marketplace`) exist in `orders` but have no rows in `marketing_spend`. Conversely, a newly launched paid channel or filtered date slice could have ad spend in `marketing_spend` with zero orders in `orders`. A `FULL OUTER JOIN` with `COALESCE(o.channel, s.channel)` preserves both zero-spend organic channels and zero-order paid channels.

### SQL Q4: How do you identify a customer's first delivered order in SQL to compute `is_new_customer_order`?
- **Answer**: Use a window function partitioned by `customer_id` over delivered-cohort orders:
  ```sql
  ROW_NUMBER() OVER (
      PARTITION BY customer_id
      ORDER BY order_date ASC, order_id ASC
  ) AS customer_delivered_seq
  ```
  Where `is_delivered = TRUE` and `customer_delivered_seq = 1` marks the exact order that acquired the customer.

### SQL Q5: How do you reconcile SQL and Python metrics automatically in tests?
- **Answer**: In `src/metrics.py`, `reconcile_sql_and_python_metrics()` connects to `d2c_analytics.duckdb` read-only, runs the aggregate SQL queries on `canonical_orders`, `marketing_spend`, and `sessions`, compares all 23 metrics against the Python dictionary outputs, and asserts `abs(py_val - sql_val) <= 0.01` (or both `None`/`NULL` when undefined).

---

## 7. Five Python & Data Engineering Questions Based on This Project

### Python Q1: How did you guarantee that the synthetic dataset generator is 100% deterministic across runs?
- **Answer**: In `src/generate_data.py`, I instantiated an explicit local NumPy Generator (`rng = np.random.default_rng(seed)`) rather than relying on global `np.random.seed()` state, and sorted generated records deterministically before assigning sequential IDs. `test_deterministic_reproducibility` in `tests/test_validation.py` runs `generate_all_datasets(seed=99)` twice and verifies bit-for-bit equality across all 9 DataFrames using `pd.testing.assert_frame_equal`.

### Python Q2: How did you structure `src/validation.py` so that multiple errors on the same row are all reported without dropping rows silently?
- **Answer**: I used an accumulator dictionary `reject_tracker: dict[str, dict[int, list[str]]]` mapping `table_name -> row_index -> list_of_reasons`. Each of the 61 checks appends its failure reason to the offending row indices via `_record_rejections()`. After all checks run, flagged indices are extracted into `ValidationReport.rejected_rows` with `"; ".join(reasons)` and dropped cleanly from `clean_tables`.

### Python Q3: How did you allocate order-level shipping costs and payment fees down to individual SKU line items in `canonical_order_items`?
- **Answer**: In `src/transformations.py`, I computed each line item's gross revenue share within its order (`rev_share = gross_line_revenue / gross_item_revenue`, guarded by `np.where(gross_item_revenue > 0, ..., 0.0)`). Multiplying order-level `earned_shipping_revenue`, `shipping_cost`, and `payment_fee` by `rev_share` ensures that SKU-level `line_contribution_profit` sums to the exact order-level `contribution_profit`.

### Python Q4: How did you optimize Streamlit startup and filter responsiveness in `app.py`?
- **Answer**: `get_pipeline_state()` is decorated with `@st.cache_resource` and checks whether `data/processed/d2c_analytics.duckdb` already exists on disk (`write_artifacts = regenerate or not db_file.exists()`). Once initialized, switching across the 9 pages or changing any of the 8 sidebar filters slices the cached canonical DataFrames in memory (`< 50 ms`) without re-running disk I/O or reloading DuckDB.

### Python Q5: How does the analytical layer scale to 100,000+ order rows?
- **Answer**: Because `compute_business_performance_And_economics()` uses vectorized Pandas/NumPy masks rather than `df.iterrows()`, benchmarking `104,000` canonical order rows (`16×` the baseline dataset) completes in **`0.199 seconds`** on a single local CPU core.

---

## 8. Five Business & Product Analytics Questions

### Analytics Q1: Which funnel stage has the largest drop-off, and how would you test a fix?
- **Answer**: Across `48,000` sessions, `37,640` view a product (`78.42%`), but only `15,464` add to cart—a **58.92% view-to-cart drop-off** (`22,176` sessions lost). In addition, mobile cart-to-checkout conversion (`62.32%`) trails desktop (`67.12%`). I proposed (`REC-FUN-01`) a 2-week randomized split test on mobile PDPs adding a sticky Add-to-Cart bar, skin-type suitability badges, and a `₹499` free-shipping progress meter, measuring View-to-Cart Rate (`%`), Cart-to-Checkout Rate (`%`), and Revenue per Session.

### Analytics Q2: Should the brand disable Cash on Delivery (COD) since COD RTO is 25.03% vs. 4.18% on Prepaid?
- **Answer**: No—disabling COD outright would likely cause a steep drop in checkout conversion in Tier 2 and Tier 3 cities, where `cod` accounts for `56%–68%` of order volume. Instead (`REC-OPS-01`), the brand should run a 4-week A/B test combining: (1) automated WhatsApp/IVR order confirmation before shipping high-risk Tier 2/3 COD orders, and (2) a `₹20–25` instant UPI prepaid discount (which is self-funded by saving the `₹25` COD collection fee and avoiding RTO courier charges). The primary success metric is **Net Contribution Profit per 1,000 Checkout Sessions**.

### Analytics Q3: Why is `CMP-META-RETARG-03` showing a much higher ROAS (`0.4857x`) than `CMP-META-PROSP-01` (`0.2386x`)?
- **Answer**: `CMP-META-RETARG-03` retargets cart abandoners and existing visitors who already have high purchase intent (`AOV ₹960.43`, low RTO `10.74%`, `60.01%` contribution margin), whereas `CMP-META-PROSP-01` is broad upper-funnel prospecting (`368` new customers vs. `153` on retargeting). Comparing retargeting ROAS directly to prospecting ROAS without an incrementality test overstates retargeting's true lift.

### Analytics Q4: How do you interpret the monthly cohort retention table (`2026-05` to `2026-10`)?
- **Answer**: For the May 2026 acquisition cohort (`472` new customers), `47.03%` (`222` customers) place a repeat delivered order in Month +1 (`2026-06`), `27.97%` in Month +2, and `16.10%` in Month +3. The steepest drop occurs between Month +1 and Month +2, which aligns with the 30–45 day physical usage cycle of 50g/100ml skincare products—making Day 35 post-delivery the optimal window for a CRM replenishment reminder experiment (`REC-CRM-01`).

### Analytics Q5: Four SKUs ended the period below their warehouse reorder point. Can we calculate exact lost revenue from those low-stock days?
- **Answer**: No. Our inventory table (`inventory_snapshots.csv`) is a daily warehouse snapshot showing `closing_stock <= reorder_point` (e.g., `SKU-SS-01` ending at `10` units vs. `220` ROP, `99.50%` sell-through). Without tracking unfulfilled backorder clicks or out-of-stock PDP impressions, claiming a specific rupee amount of "lost sales" would be an unverified fabrication.

---

## 9. Ten Difficult Follow-Up Questions Recruiters May Ask

1. **"Since this is synthetic data, didn't you just program the findings you wanted to find?"**
   - *Answer*: I parameterized realistic domain priors in `src/generate_data.py` (such as higher COD preference in Tier 2/3 cities and higher price sensitivity on flash-sale promos), but all downstream KPIs, cohort matrices, and recommendations are computed dynamically from the raw tables. More importantly, the engineering value—61 validation checks, anti-fan-out pre-aggregation, 23-KPI SQL/Python reconciliation, and automated tests—works identically on any real e-commerce dataset matching the schema.
2. **"What happens if a customer places a first order that gets cancelled or RTO'd, and then places a second order that is delivered? Which order is their acquisition cohort?"**
   - *Answer*: In `src/transformations.py`, `customer_delivered_seq` is computed strictly over delivered-cohort orders (`can[can["is_delivered"]]`). A cancelled or RTO order never generated realized revenue, so the customer's first **delivered** order (`customer_delivered_seq == 1`) defines `is_new_customer_order = True` and their `cohort_month`.
3. **"Why did you include `returned` orders inside `is_delivered` when computing Delivered Orders (`4,424`)?"**
   - *Answer*: Because a post-delivery customer return only happens *after* the courier physically delivered the parcel (`shipments.delivered_at IS NOT NULL`). If `is_delivered` excluded post-delivery returns, then the numerator of `Return Rate` (`returned + partially_refunded = 474`) would be disjoint from the denominator (`unreturned delivered = 3,950`), which violates probability bounds. Meanwhile, for `returned` orders, `effective_refund_amount` equals `gross_item_revenue - discount_amount`, so their `net_merchandise_sales` is `₹0.00`—and we also report `Retained Delivered Orders` (`4,106`) and `Retained AOV` (`₹961.94`) right alongside it.
4. **"How do you handle a partial refund (`partially_refunded`) when computing product COGS?"**
   - *Answer*: In `aggregate_order_items_to_order_grain()`, each order line computes `retained_ratio = 1.0 - (line_refund_amount / net_line_before_refund)`. In our generator, a `partially_refunded` multi-item order refunds one returned line item while the customer keeps the other line item(s), so `retained_product_cogs` counts the exact COGS of the unrefunded item(s) retained by the customer.
5. **"Why is your overall Attributed ROAS (`0.2516x`) and Blended MER (`0.5437x`) below 1.0x in the baseline dataset?"**
   - *Answer*: In the `seed = 42` simulation, the 7 paid campaigns spend ~`₹39,484/day` combined (`₹7.27M` over 184 days) while total brand volume is set at `6,500` orders (`₹3.95M` Net Merchandise Sales). Rather than altering the raw CSVs after the fact to make ROAS look artificially high, I kept the raw dataset untouched and had the recommendation engine (`REC-MKT-02`) explicitly flag that paid CAC (`₹4,705.41`) exceeds 6-month observed customer contribution (`₹977.21`).
6. **"What if an order has an order-header discount that doesn't match the sum of `quantity * unit_discount` in `order_items`?"**
   - *Answer*: Check #8 in `src/validation.py` (`order_discount_reconciliation`) compares `orders.discount_amount` against `SUM(quantity * unit_discount)` grouped by `order_id`. Any order with an absolute discrepancy `> ₹0.05` fails validation and is quarantined into `rejected_rows` with the reason `"Order header discount_amount does not reconcile with sum of order_items discounts"`.
7. **"What happens in your dashboard if a user selects a filter combination that has zero orders (e.g., `Marketplace` channel + `CMP-META-FLASH-02` campaign)?"**
   - *Answer*: First, `safe_divide()` in `src/metrics.py` returns `None` (`NA`) for all ratios with zero denominators instead of raising `ZeroDivisionError`. Second, `app.py` checks `if flt_orders.empty:` and renders a clear warning banner guiding the user to broaden their filters or click **Reset All Filters**, verified by `test_global_filters_and_no_duplicate_revenue`.
8. **"How does proportional allocation of shipping cost to SKU lines behave if an order has two items: a heavy ₹349 Face Wash and a lightweight ₹1,299 Combo Kit?"**
   - *Answer*: Currently, `canonical_order_items` allocates order-level shipping cost by `gross_line_revenue` share (`rev_share`), which assigns more shipping cost to the higher-priced item rather than by physical parcel weight. If SKU weight in grams were added to `products.csv`, allocating shipping cost by `quantity * unit_weight_grams` would be a more physically accurate cost-accounting method.
9. **"Why didn't you use an LLM or AI agent inside the app to generate the recommendations?"**
   - *Answer*: Financial and operational recommendations require 100% determinism, auditability, and zero hallucinated numbers. Using explicit threshold rules in `src/recommendations.py` guarantees that every single metric cited in a recommendation card matches the exact numbers on the dashboard and runs locally in milliseconds without paid API keys.
10. **"How does this app deploy to Streamlit Community Cloud if `data/raw/*.csv` and `d2c_analytics.duckdb` are in `.gitignore`?"**
    - *Answer*: On startup, `get_pipeline_state()` in `app.py` checks if `data/raw/orders.csv` and `data/processed/d2c_analytics.duckdb` exist. On a fresh cloud container where they are absent, it automatically triggers `run_data_engineering_pipeline(regenerate_data=True, write_artifacts=True)` once, generating the deterministic `seed = 42` dataset and DuckDB database in `~5 seconds` and caching it across sessions with `@st.cache_resource`.
