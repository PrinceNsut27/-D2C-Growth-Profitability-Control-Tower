# System Architecture — D2C Growth & Profitability Control Tower

## 1. End-to-End Architecture Diagram (Mermaid)

```mermaid
flowchart TD
    subgraph Gen["1. Deterministic Synthetic Generator (Seed = 42)"]
        G1["src/generate_data.py<br/>AuraVeda Skincare (INR, Asia/Kolkata)"]
    end

    subgraph Raw["2. Raw CSV Source Layer (data/raw/)"]
        R1["customers.csv (3,200)"]
        R2["products.csv (8)"]
        R3["orders.csv (6,500)"]
        R4["order_items.csv (9,722)"]
        R5["sessions.csv (48,000)"]
        R6["marketing_spend.csv (1,288)"]
        R7["shipments.csv (5,402)"]
        R8["returns.csv (6,43)"]
        R9["inventory_snapshots.csv (1,472)"]
    end

    subgraph Val["3. Ingestion & 61-Check Validation Gate"]
        V1["src/ingestion.py<br/>Typed DataFrame Loader"]
        V2["src/validation.py<br/>Schema, PK, FK, Lifecycle, Math Checks"]
        V3["Rejected Rows Report<br/>data/processed/rejected_rows.csv"]
    end

    subgraph Can["4. Anti-Fan-Out Canonical Layer (src/transformations.py)"]
        C1["Pre-Aggregate order_items + unit_cogs<br/>to order_id grain"]
        C2["Pre-Aggregate shipments<br/>to order_id grain"]
        C3["Pre-Aggregate returns<br/>to order_id grain"]
        C4["canonical_orders (6,500 rows, 1:1)<br/>canonical_order_items (9,722 rows)"]
    end

    subgraph Engine["5. Dual Analytical & Reconciliation Layer"]
        E1[("DuckDB 2.0 Warehouse<br/>d2c_analytics.duckdb<br/>sql/schema.sql & core_metrics.sql")]
        E2["Python Analytics Modules<br/>src/metrics.py | src/attribution.py<br/>src/segmentation.py | src/cohorts.py"]
        E3["23-KPI SQL vs Python Reconciliation<br/>Tolerance <= 0.01 (23/23 Matched)"]
    end

    subgraph App["6. Decision-Support Presentation Layer"]
        A1["src/recommendations.py<br/>6 Rule-Based Evidence Cards"]
        A2["app.py — 9-Page Streamlit Dashboard<br/>Global Filters, Plotly Charts, CSV Exports"]
        A3["Human Operator Review<br/>(No Autonomous Execution)"]
    end

    G1 --> Raw
    Raw --> V1 --> V2
    V2 -->|Invalid Rows| V3
    V2 -->|Clean Tables| C1 & C2 & C3
    C1 & C2 & C3 --> C4
    C4 --> E1 & E2
    E1 & E2 --> E3
    E3 --> A1 & A2
    A1 --> A2 --> A3
```

---

## 2. Repository Structure

```text
D2C-Growth-Profitability-Control-Tower/
├── README.md                                    # Complete setup, methodology, and guide
├── LICENSE                                      # MIT License
├── requirements.txt                             # Python package dependencies
├── app.py                                       # 9-view Streamlit interactive application
├── .streamlit/
│   └── config.toml                              # Streamlit theme and server configuration
├── config/
│   ├── settings.example.toml                    # Template project configuration
│   └── settings.toml                            # Active local configuration (seed=42, INR)
├── data/
│   ├── README.md                                # Dataset provenance and simulation rules
│   ├── sample/                                  # Reference schema header CSVs
│   ├── raw/                                     # Generated raw synthetic CSVs (git-ignored)
│   └── processed/                               # DuckDB database & canonical CSVs (git-ignored)
├── src/
│   ├── __init__.py                              # Package metadata
│   ├── config.py                                # TOML settings loader & logging setup
│   ├── generate_data.py                         # Deterministic synthetic generator (seed=42)
│   ├── ingestion.py                             # CSV loader and type normalizer
│   ├── validation.py                            # 61-check data validation & rejection engine
│   ├── transformations.py                       # Anti-fan-out canonical builder & DuckDB loader
│   ├── metrics.py                               # Performance, funnel, economics, ops, inventory
│   ├── attribution.py                           # Spend, CAC, campaign ROAS, and blended MER
│   ├── segmentation.py                          # RFM scoring, repeat rate, and observed 6M LTV
│   ├── cohorts.py                               # Monthly acquisition cohort retention matrices
│   ├── recommendations.py                       # Rule-based recommendation engine
│   └── pipeline.py                              # End-to-end CLI pipeline orchestrator
├── sql/
│   ├── schema.sql                               # DuckDB DDL for all 9 source tables
│   └── core_metrics.sql                         # Parameterized analytical SQL queries
├── tests/
│   ├── test_validation.py                       # Schema, PK, FK, math, and rejection tests
│   ├── test_pipeline.py                         # Anti-fan-out & DuckDB integration tests
│   ├── test_metrics.py                          # Hand-calculated KPI & SQL reconciliation tests
│   ├── test_attribution.py                      # CAC, ROAS, MER, and zero-spend NA tests
│   ├── test_cohorts.py                          # RFM and monthly cohort retention tests
│   └── test_recommendations_and_dashboard.py    # Recommendation rules, filters, & Streamlit AppTest
├── screenshots/                                 # Live application screenshots (01..09)
└── docs/
    ├── ARCHITECTURE.md                          # System architecture & data flow
    ├── DATA_DICTIONARY.md                       # Complete schema and field definitions
    ├── DEPLOYMENT_GUIDE.md                      # Local, Streamlit Cloud & Docker deployment guide
    ├── FINAL_REPORT.md                          # Complete analytical report with computed results
    ├── INTERVIEW_PREPARATION.md                 # Project walkthroughs & technical/business Q&A
    ├── METRIC_DEFINITIONS.md                    # KPI formulas, denominators, and caveats
    ├── TECHNICAL_REVIEW.md                      # Architecture audit & 104k-order benchmark timings
    └── TEST_PLAN.md                             # Automated test suite documentation
```

---

## 3. Anti-Fan-Out Relational Design
Joining `orders` directly to multiple `order_items`, multiple `shipments`, and multiple `returns` causes Cartesian row multiplication within an order and inflates order-header metrics (`discount_amount`, `shipping_revenue`, `tax_amount`).

To guarantee **zero revenue duplication**:
1. `aggregate_order_items_to_order_grain()` aggregates `order_items` joined with `products.unit_cogs` to `1 row per order_id`.
2. `aggregate_shipments_to_order_grain()` aggregates `shipments` to `1 row per order_id`.
3. `aggregate_returns_to_order_grain()` aggregates `returns` to `1 row per order_id`.
4. `build_canonical_model()` merges these `1:1` summaries onto `orders` and asserts `len(canonical_orders) == len(orders)` (`6,500 == 6,500`) and `SUM(canonical_orders.net_merchandise_sales) == SUM(canonical_order_items.line_net_merchandise_sales)` (`₹3,949,725.97 == ₹3,949,725.97`).
