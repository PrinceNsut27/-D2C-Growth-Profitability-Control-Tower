# D2C Growth & Profitability Control Tower — Final Technical & Business Report

> **SYNTHETIC CASE STUDY DISCLOSURE**: This report documents a **fictional Indian skincare D2C brand case study ("AuraVeda Skincare")**. Every dataset is **100% deterministic synthetic data** generated with a fixed seed (`random_seed = 42`, `Currency = INR`, `Timezone = Asia/Kolkata`, window `2026-05-01` to `2026-10-31`). Zero real customer PII is used, and simulated outputs must never be presented as real company performance.

---

## 1. Executive Summary
- **Business Problem**: D2C brands frequently evaluate growth through top-line Gross Merchandise Value (GMV) and ad-platform Return on Ad Spend (ROAS), while marketing spend, promotional discounts, Cash-on-Delivery (COD) Return-to-Origin (RTO) logistics losses, post-delivery customer refunds, payment processing fees, and warehouse stockouts live in separate silos.
- **Data Period & Scale**: `2026-05-01` to `2026-10-31` (`184` calendar days) comprising `3,200` registered customers, `8` skincare SKUs, `48,000` website sessions, `6,500` placed orders (`9,722` order line items), `1,288` campaign-day spend records, `5,402` courier shipments, `643` return line cases, and `1,472` daily SKU inventory snapshots.
- **Main Verified Findings**:
  1. **GMV-to-Contribution Compression**: Out of `₹6,752,129.00` in placed GMV (`6,500` orders), pre-shipment cancellations (`7.34%`), shipped RTOs (`13.96%`), delivered promotional discounts (`₹284,604.12`), and post-delivery refunds (`₹418,629.91`) reduce **Net Merchandise Sales** to `₹3,949,725.97` (`4,424` delivered cohort orders; AOV `₹892.80`). After Net COGS (`₹1,174,973.00`), courier shipping costs (`₹407,932.32`, including `₹95,217.95` dead-weight RTO shipping drag), and payment fees (`₹121,100.47`), **Contribution Profit (CM2)** is `₹2,285,753.18` (`57.87%` of Net Sales).
  2. **COD vs Prepaid Unit Economics Gap**: COD orders (`3,054` placed; `2,533` shipped) exhibit a **25.03% RTO rate** (reaching **32.23% in Tier 3 cities**), which is **6.0x higher** than Prepaid orders (`4.18%` RTO rate across `2,869` shipped orders). COD RTO orders incur `₹80,832.11` in courier losses with `₹0` revenue, depressing COD contribution margin to `54.73%` vs `59.96%` on Prepaid.
  3. **Discount Flash Sale Margin Erosion**: Campaign `CMP-META-FLASH-02` (Meta 30% Off Promo) spent `₹1,534,748.81` and generated `462` placed orders, but suffered a `23.06%` effective discount rate, `68.40%` COD share, `19.70%` RTO rate, lowest AOV (`₹718.44`), and the weakest contribution margin (`48.23%` vs `57.87%` brand average).
  4. **Website Funnel Drop-Off**: Across `48,000` sessions, `78.42%` view a product (`37,640`), but **58.92% of product viewers drop off before adding to cart** (`15,464` carts), and `36.25%` of carts abandon before checkout (`9,858` checkouts $\rightarrow$ `6,500` purchases; `13.54%` overall session conversion). Mobile cart-to-checkout conversion (`62.32%`) trails Desktop (`67.12%`).
  5. **Repeat Purchase & 'At Risk' Cohort Value**: `52.64%` of active delivered customers (`1,298 / 2,466`) place `2+` delivered orders, generating `₹2,269.74` average 6-month net sales vs `₹859.25` for one-time buyers (`2.64x`). However, `506` previously repeat buyers in the RFM **`At Risk`** segment (`₹1,032,186.62` historical net sales, `26.13%` of brand revenue) average `117.0` days since their last order.
- **Key Limitations**: All findings are derived from deterministic synthetic data (`seed = 42`). Campaign ROAS reflects observational last-touch order tags rather than causal incrementality; customer LTV is right-censored to the 6-month window; warehouse snapshots (`closing_stock <= reorder_point`) indicate replenishment risk rather than proven lost sales.

---

## 2. Business Problem
Indian D2C skincare brands face four interlocking operational challenges:
1. **Fragmented Reporting**: Ad platforms report gross attributed revenue on placed orders without deducting pre-shipment cancellations, COD doorstep refusals (RTO), discounts, or post-delivery refunds.
2. **Join Fan-Out Errors in Analytics**: Joining order headers (`orders`) directly to multi-line `order_items`, split `shipments`, and multi-item `returns` multiplies order-level fields (`discount_amount`, `shipping_revenue`, `tax_amount`) and overstates revenue.
3. **COD & Tier 2/3 Logistics Drag**: High COD adoption drives order volume in Tier 2 and Tier 3 cities but introduces substantial reverse-logistics costs when parcels are refused at the doorstep.
4. **Disconnected Merchandising & Ad Ops**: Paid campaigns frequently push hero SKUs (`SKU-SS-01` SPF 50 Sunscreen and `SKU-FW-01` Clarifying Face Wash) even when warehouse inventory drops below reorder point.

---

## 3. System Architecture
The platform is structured into 6 strictly separated layers:
1. **Synthetic Data Generator (`src/generate_data.py`)**: Deterministic NumPy `default_rng(42)` generator creating all 9 relational CSV datasets in `data/raw/`.
2. **Ingestion Layer (`src/ingestion.py`)**: Schema-aware CSV reader normalizing nullable strings, booleans, and timestamps.
3. **Validation Gate (`src/validation.py`)**: Executes **61 automated checks** across schema presence, mandatory non-nulls, primary-key uniqueness, non-negative numerics, date parsing, currency consistency (`INR`), foreign-key referential integrity, lifecycle transition rules, header-vs-line discount reconciliation, inventory arithmetic (`opening + received - sold == closing`), and funnel flag ordering. Invalid rows are never silently dropped; they are isolated into `ValidationReport.rejected_rows` (`data/processed/rejected_rows.csv`).
4. **Anti-Fan-Out Canonical Layer (`src/transformations.py`)**: Pre-aggregates `order_items` (+ `products.unit_cogs`), `shipments`, and `returns` to `order_id` grain before merging `1:1` onto `orders` to build `canonical_orders` (`6,500` rows) and `canonical_order_items` (`9,722` rows), persisting all tables to **DuckDB 2.0** (`data/processed/d2c_analytics.duckdb`).
5. **Dual SQL & Python Metric Layer (`src/metrics.py`, `src/attribution.py`, `src/segmentation.py`, `src/cohorts.py`, `sql/core_metrics.sql`)**: Computes all KPIs in both Python and DuckDB SQL and verifies 23/23 KPI reconciliation within `0.01` tolerance.
6. **Recommendation Engine & Streamlit UI (`src/recommendations.py`, `app.py`)**: Evaluates rule-based decision-support cards and serves 9 interactive dashboard views with global filtering and CSV exports.

---

## 4. Data Engineering Workflow & Join-Safety Audit
- **Source Grain & Row Counts**:
  - `customers.csv`: `3,200` rows (`PK: customer_id`)
  - `products.csv`: `8` rows (`PK: product_id`)
  - `orders.csv`: `6,500` rows (`PK: order_id`)
  - `order_items.csv`: `9,722` rows (`PK: order_item_id`)
  - `sessions.csv`: `48,000` rows (`PK: session_id`)
  - `marketing_spend.csv`: `1,288` rows (`PK: date, platform, channel, campaign_id`)
  - `shipments.csv`: `5,402` rows (`PK: shipment_id`)
  - `returns.csv`: `643` rows (`PK: return_id`)
  - `inventory_snapshots.csv`: `1,472` rows (`PK: snapshot_date, product_id`)
- **Anti-Fan-Out Verification**:
  - `orders_input`: `6,500`
  - `canonical_orders_output`: `6,500` (`unique_order_ids = 6,500`, `fanout_detected = False`)
  - `SUM(canonical_orders.net_merchandise_sales)`: `₹3,949,725.97`
  - `SUM(canonical_order_items.line_net_merchandise_sales)`: `₹3,949,725.97` (`abs_diff = 0.0`)

---

## 5. Analytics Methodology & Complete KPI Results (`2026-05-01` to `2026-10-31`)

| KPI Category | Metric Name | Formula | Numerator | Denominator | Computed Result |
|---|---|---|---|---|---|
| **Order Lifecycle** | Placed Orders | `COUNT(DISTINCT order_id)` | `6,500` orders | — | `6,500` |
| **Order Lifecycle** | Shipped Orders | `COUNT(DISTINCT order_id) WHERE is_shipped` | `5,402` orders | — | `5,402` |
| **Order Lifecycle** | Delivered Orders (Cohort) | `COUNT(DISTINCT order_id) WHERE is_delivered` | `4,424` orders | — | `4,424` |
| **Order Lifecycle** | Retained Delivered Orders | `COUNT(DISTINCT order_id) WHERE is_retained_delivered` | `4,106` orders | — | `4,106` |
| **Order Lifecycle** | Cancellation Rate | `Cancelled Orders / Placed Orders` | `477` cancelled | `6,500` placed | `7.34%` |
| **Order Lifecycle** | RTO Rate | `RTO Orders / Shipped Orders` | `754` RTO | `5,402` shipped | `13.96%` |
| **Order Lifecycle** | Post-Delivery Return Rate | `Returned Orders / Delivered Orders` | `474` returned | `4,424` delivered | `10.71%` |
| **Revenue & AOV** | Placed GMV | `SUM(gross_item_revenue)` | `₹6,752,129.00` | `11,271` units | `₹6,752,129.00` |
| **Revenue & AOV** | Delivered Gross Revenue | `SUM(gross_item_revenue) WHERE is_delivered` | `₹4,652,960.00` | `7,740` units | `₹4,652,960.00` |
| **Revenue & AOV** | Delivered Discounts | `SUM(discount_amount) WHERE is_delivered` | `₹284,604.12` | `4,424` orders | `₹284,604.12` |
| **Revenue & AOV** | Effective Refunds | `SUM(effective_refund_amount) WHERE is_delivered` | `₹418,629.91` | `474` returned orders | `₹418,629.91` |
| **Revenue & AOV** | Net Merchandise Sales | `Delivered GMV - Discounts - Refunds` | `₹3,949,725.97` | — | `₹3,949,725.97` |
| **Revenue & AOV** | Average Order Value (AOV) | `Net Merchandise Sales / Delivered Orders` | `₹3,949,725.97` | `4,424` delivered | `₹892.80` |
| **Unit Economics** | Net Product COGS | `SUM(retained_product_cogs) WHERE is_delivered` | `₹1,174,973.00` | — | `₹1,174,973.00` |
| **Unit Economics** | Gross Profit & Margin % | `(Net Sales - Net COGS) / Net Sales` | `₹2,774,752.97` | `₹3,949,725.97` | `₹2,774,752.97` (`70.25%`) |
| **Unit Economics** | Total Shipping Cost | `SUM(shipments.shipping_cost)` | `₹407,932.32` | `5,402` shipped | `₹407,932.32` (`₹95,217.95` RTO) |
| **Unit Economics** | Payment Processing Fees | `2% Prepaid + ₹25 COD Delivered` | `₹121,100.47` | — | `₹121,100.47` |
| **Unit Economics** | Contribution Profit (CM2) | `Gross Profit + Shipping Rev (₹40,033) - Shipping Cost - Payment Fees` | `₹2,285,753.18` | `₹3,949,725.97` | `₹2,285,753.18` (`57.87%`) |
| **Acquisition** | Total Paid Media Spend | `SUM(marketing_spend.spend)` | `₹7,265,150.14` | `723,919` clicks | `₹7,265,150.14` |
| **Acquisition** | Blended CAC | `Total Paid Spend / Total New Customers` | `₹7,265,150.14` | `2,466` new customers | `₹2,946.13` |
| **Acquisition** | Paid Channel CAC | `Total Paid Spend / Paid-Attributed New Customers` | `₹7,265,150.14` | `1,544` paid new custs | `₹4,705.41` |
| **Acquisition** | Campaign-Attributed ROAS | `Attributed Net Sales / Total Paid Spend` | `₹1,827,890.65` | `₹7,265,150.14` | `0.2516x` |
| **Acquisition** | Blended MER | `Total Net Merchandise Sales / Total Paid Spend` | `₹3,949,725.97` | `₹7,265,150.14` | `0.5437x` |
| **Funnel** | Session Conversion Rate | `Purchases / Eligible Sessions` | `6,500` purchases | `48,000` sessions | `13.54%` |
| **Customer** | Repeat Purchase Rate | `Customers (2+ Delivered) / Customers (1+ Delivered)` | `1,298` repeat | `2,466` active | `52.64%` |
| **Customer** | Observed 6M Customer LTV | `Total Net Sales / Active Delivered Customers` | `₹3,949,725.97` | `2,466` active | `₹1,601.67` |

---

## 6. Dashboard Capabilities (`app.py`)
The Streamlit application provides 9 analytical views (`1. Executive Overview`, `2. Marketing Performance`, `3. Conversion Funnel`, `4. Profitability & Unit Economics`, `5. Customer Intelligence`, `6. Operations & Returns`, `7. Product & Inventory`, `8. Business Recommendations`, and `9. Data Quality & Glossary`), interactive sidebar filtering across 8 dimensions (Date Window, Trend Grain, Sales Channel, Campaign, Product/SKU, RFM Segment, Payment Mode, City Tier), one-click filter reset, CSV exports on every page, and a persistent synthetic-data disclosure banner.

---

## 7. Key Computed Business Findings (Structured Analysis)

### Finding 1: Cash-on-Delivery (COD) RTO Drag Across City Tiers
- **Observed Pattern**: Shipped COD orders (`2,533`) suffer a **25.03% RTO rate** (`634` RTO orders) compared to **4.18%** on shipped Prepaid orders (`120 / 2,869`). By city tier, COD RTO rises from `18.14%` in Tier 1 (`139 / 766`) to `28.43%` in Tier 2 (`280 / 985`) and **32.23% in Tier 3 (`215 / 667` shipped COD orders)**.
- **Supporting Evidence**: COD orders incur `₹80,832.11` in dead-weight RTO courier fees (84.9% of total `₹95,217.95` RTO shipping loss), lowering COD Contribution Margin to `54.73%` vs `59.96%` on Prepaid (`5.23` percentage point gap).
- **Alternative Explanations**: Tier 2/3 address formatting, courier partner last-mile coverage differences, and buyer self-selection into COD.
- **What Cannot Be Concluded**: We cannot conclude that disabling COD would increase total net profit, because removing COD could sharply reduce gross checkout conversion among cash-preferring shoppers.

### Finding 2: Promotional Discounting & RTO Compounding on `CMP-META-FLASH-02`
- **Observed Pattern**: Among all 7 paid campaigns, `CMP-META-FLASH-02` (*Meta Flash Sale 30% Off*) exhibits the lowest Contribution Margin (`48.23%` vs `57.87%` brand average) and lowest Attributed ROAS (`0.1484x` on `₹1,534,748.81` spend).
- **Supporting Evidence**: `CMP-META-FLASH-02` has a `23.06%` effective discount rate (`₹77,120.86` delivered discounts on `₹334,439.00` delivered GMV), the highest COD share (`68.40%`), a `19.70%` RTO rate, and the lowest AOV (`₹718.44` vs `₹960.43` on `CMP-META-RETARG-03`).
- **Alternative Explanations**: Upper-funnel promo ads reach cold audiences with lower brand trust.
- **What Cannot Be Concluded**: Observational last-touch ROAS does not measure multi-touch view-through or organic search spillover.

### Finding 3: Website Product-View-to-Cart Leakage & Mobile Checkout Gap
- **Observed Pattern**: Of `48,000` sessions, `37,640` view a product (`78.42%`), but only `15,464` add to cart (**58.92% view-to-cart drop-off** — `22,176` sessions lost). Furthermore, mobile cart-to-checkout progression (`62.32%`) trails desktop (`67.12%`).
- **Supporting Evidence**: Channel × Device funnel metrics show `Paid Social` (`30.56%` add-to-cart rate) and `Influencer` (`29.83%` add-to-cart rate) experience the steepest PDP-to-cart drop-offs on mobile devices.
- **Alternative Explanations**: Social media discovery traffic naturally has higher casual browsing intent than high-intent search traffic.
- **What Cannot Be Concluded**: We cannot attribute the mobile drop-off solely to page load speed or UX friction without an A/B test.

### Finding 4: Repeat Buyer Economics & 'At Risk' High-Value Segment Concentration
- **Observed Pattern**: Repeat customers (`1,298` customers with `2+` delivered orders; `52.64%` repeat rate) generate **74.59% of total Net Merchandise Sales** (`₹2,946,120.80` out of `₹3,949,725.97`), averaging `₹2,269.74` vs `₹859.25` for first-time buyers. However, `506` repeat customers sit in the RFM **`At Risk`** segment (`avg_recency_days = 117.0`, `avg_frequency = 2.09`, `total_net_sales = ₹1,032,186.62`).
- **Supporting Evidence**: Monthly cohort retention (`2026-05` cohort, $N=472$) drops from `47.03%` in Month +1 (`222` buyers) to `27.97%` in Month +2 (`132` buyers) and `16.10%` in Month +3 (`76` buyers).
- **Alternative Explanations**: Customers buying 100ml/150ml cleansers or combo kits may have longer physical consumption cycles (>60 days).
- **What Cannot Be Concluded**: Historical 6-month cumulative revenue (`₹1,601.67`) is not a predictive multi-year CLV estimate.

### Finding 5: Hero SKU Contribution Concentration & Replenishment Lag Signals
- **Observed Pattern**: Top 2 hero SKUs — `SKU-SS-01` (*SPF 50 Invisible Fluid Sunscreen*, Net Sales `₹801,064.30`, Contribution `₹471,342.54`, `58.84%` margin) and `SKU-MO-01` (*Ceramide Barrier Moisturiser*, Net Sales `₹643,296.89`, Contribution `₹375,018.48`, `58.30%` margin) — generate **37.03% of total brand contribution profit**. Four SKUs (`SKU-FW-01`, `SKU-SS-01`, `SKU-SR-01`, `SKU-KT-01`) ended the period below their warehouse reorder point (`SKU-SS-01` closing stock `10` vs ROP `220`, `99.50%` sell-through; `SKU-FW-01` spent `21` days `<= ROP`).
- **What Cannot Be Concluded**: Snapshot closing stock below reorder point does **not** prove lost sales, as unfulfilled intraday demand is not recorded.

---

## 8. Business Recommendations (For Human Review)

| ID | Priority | Proposed Action for Human Review | Supporting Evidence | Expected Mechanism | Risk & Cost | Success Metric & Window | Experiment Needed |
|---|---|---|---|---|---|---|---|
| `REC-OPS-01` | **High** | Test automated WhatsApp/IVR pre-dispatch confirmation on COD orders in Tier 2/3 pincodes + `₹20–25` instant UPI prepaid incentive | COD RTO `25.03%` (`634/2,533`) vs Prepaid `4.18%`; Tier 3 COD RTO `32.23%`; `₹80,832.11` COD RTO shipping loss | Filters low-intent/impulse COD orders before courier dispatch and nudges genuine buyers to UPI | Confirmation friction may lower gross COD checkout conversion | Net Contribution Profit per 1,000 Checkouts & Shipped COD RTO % (4 weeks) | 50/50 Checkout & Pre-Dispatch Confirmation A/B Test |
| `REC-MKT-01` | **High** | Replace flat 30% discount on `CMP-META-FLASH-02` with tiered `MOV >= ₹799` routine bundles or prepaid-only promo codes | `CMP-META-FLASH-02` CM2 `48.23%` (lowest), discount rate `23.06%`, COD share `68.40%`, RTO `19.70%`, AOV `₹718.44` | Raises basket size above free-shipping threshold and deters one-off COD discount refusals | Lower click-through and initial conversion rate on ad creatives | Contribution Profit after Ad Spend (CM3) & 60-Day Repeat Rate (3 weeks) | Ad Set Creative & Offer Split Test |
| `REC-MKT-02` | **High** | Audit search terms/placements on `CMP-GGL-NONBRAND-02` and run geo-holdout test before reallocating budget | Spend `₹1,268,082.67`, Paid CAC `₹5,816.89` vs 6M observed LTV `₹1,601.67`, Attributed ROAS `0.1790x` | Reduces wasted clicks on broad non-converting skincare queries | Cutting prospecting spend blindly may reduce organic/direct assist (`₹2.12M` unassigned sales) | Blended MER, Paid CAC, and Incremental Geo Contribution (4 weeks) | Matched Geo-Holdout Incrementality Test |
| `REC-FUN-01` | **High** | Test sticky mobile Add-to-Cart bar with skin-type suitability badges, `₹499` free-shipping meter, and 1-click UPI checkout | `58.92%` view-to-cart drop-off (`22,176` sessions lost); Mobile cart-to-checkout `62.32%` vs Desktop `67.12%` | Reduces ingredient uncertainty on PDPs and payment friction on mobile devices | UI changes require engineering QA across mobile viewports | View-to-Cart Rate (%), Cart-to-Checkout Rate (%), Rev/Session (2 weeks) | Randomized Mobile PDP & Cart Drawer A/B Test |
| `REC-CRM-01` | **Medium** | Trigger day-35 replenishment reminders & routine cross-sell flows for `At Risk` (`506` buyers) and `First-Time` (`1,168` buyers) segments | `At Risk` holds `26.13%` of net sales (`₹1,032,186.62`) at `117.0d` recency; Repeat LTV (`₹2,269.74`) is `2.64x` First-Time (`₹859.25`) | Aligns CRM touchpoints with 30–45 day physical depletion of 50g/100ml skincare consumables | Over-messaging or unnecessary coupons can cannibalize organic repeat margin | Incremental 60-Day Repeat Order Rate & Contribution/Customer (60 days) | 80/20 Randomized CRM Holdout Experiment |
| `REC-INV-01` | **Medium** | Increase safety stock buffer / earlier reorder trigger for `SKU-SS-01`, `SKU-FW-01`, and `SKU-SR-01`; sync ad ops with stock cover | `4` SKUs below ROP (`SKU-SS-01` closing `10` vs ROP `220`, `99.50%` sell-through; `SKU-FW-01` `21` days `<= ROP`) | Buffers against 5-day supplier replenishment lag during campaign demand spikes | Higher working capital and shelf-life holding cost | % Snapshot Days Above Reorder Point & Dispatch SLA (60 days) | Operational Inventory Buffer Pilot |

---

## 9. Validation, Testing & Reconciliation Evidence
- **Automated Test Execution (`python -m pytest -v`)**: **`23 passed`** (`0` failures, `0` warnings) across 6 test modules (`test_validation.py`, `test_pipeline.py`, `test_metrics.py`, `test_attribution.py`, `test_cohorts.py`, `test_recommendations_and_dashboard.py`).
- **Data Validation**: `61` automated checks across all 9 tables (`Passed: True`, `0` rejected rows on clean dataset; all error pathways verified via corrupted fixtures).
- **SQL vs Python Reconciliation**: `23 / 23` KPIs matched between DuckDB SQL and Python within `<= 0.01` tolerance (`abs_diff = 0.0` across all 23 metrics).

---

## 10. Limitations & Future Scope
1. **Synthetic Dataset Scope**: Generated deterministically (`seed = 42`) to model realistic Indian D2C unit economics; does not represent real company records.
2. **Last-Touch Observational Attribution**: Campaign tags do not capture multi-touch journeys or causal incrementality.
3. **Future Enhancements**:
   - Interactive What-If Contribution Simulator for discount depth, COD fee, and RTO reduction scenarios.
   - Multi-SKU Market Basket / Co-occurrence analysis (`order_items` affinity rules).
   - Time-based backtested SKU demand forecasting for automated reorder point calibration.
