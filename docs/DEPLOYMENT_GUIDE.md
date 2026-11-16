# Deployment Guide — Local, Streamlit Community Cloud & Container Hosting

> **Note**: Per project governance, this application is configured for zero-credential, local-first execution and seamless cloud deployment, but **nothing has been deployed or pushed externally without explicit user permission**.

---

## 1. Deployment Readiness Assessment

The **D2C Growth & Profitability Control Tower** (`app.py`) is **100% ready for one-click cloud deployment** (e.g., Streamlit Community Cloud, Render, Railway, or Hugging Face Spaces) with zero external database servers or paid API keys required:

1. **Automatic Cold-Start Data & DuckDB Initialization**:
   - Because `data/raw/*.csv` and `data/processed/d2c_analytics.duckdb` are excluded via `.gitignore` to keep the Git repository lightweight, a newly booted cloud container starts with empty `data/raw/` and `data/processed/` directories.
   - On initial startup, `get_pipeline_state()` in [app.py](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/app.py#L79-L92) checks `not orders_file.exists()` and `not db_file.exists()`.
   - When missing, it automatically invokes `run_data_engineering_pipeline(regenerate_data=True, write_artifacts=True)`, which deterministically generates all 9 synthetic tables (`seed = 42`), runs all 61 validation checks, builds `data/processed/d2c_analytics.duckdb`, and caches the `PipelineResult` in memory via `@st.cache_resource` in `~4–6 seconds`.
   - Subsequent user interactions and tab switches reuse the in-memory cached state without re-running data generation or re-writing DuckDB (`write_artifacts=False`).
2. **Configuration Fallback (`src/config.py`)**:
   - `load_settings()` automatically loads `config/settings.toml` if present, or falls back to `config/settings.example.toml`. Both files use portable relative paths (`data/raw/*.csv`, `data/processed/d2c_analytics.duckdb`) resolved against `PROJECT_ROOT`.
3. **Theme & Server Configuration (`.streamlit/config.toml`)**:
   - Included at [.streamlit/config.toml](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/.streamlit/config.toml) with a cohesive teal/slate analytical palette (`primaryColor = "#0F766E"`), `headless = true`, and `gatherUsageStats = false`.
4. **Minimal, Pure-Wheel Dependencies (`requirements.txt`)**:
   - All dependencies in [requirements.txt](file:///c:/Users/Prince/Desktop/D2C_Growth_Profitability_Control_Tower/requirements.txt) (`pandas`, `numpy`, `duckdb`, `streamlit`, `plotly`, `pytest`) publish pre-compiled binary wheels for Linux (`x86_64` / `aarch64`), Windows, and macOS on Python 3.11–3.13.

---

## 2. Option A: Local Deployment (Development or Production Mode)

### 1. Clone & Create Virtual Environment
```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Pre-Warm Data & Verify Tests (Optional — `app.py` also auto-initializes if skipped)
```bash
python -m src.generate_data
python -m src.pipeline
python -m pytest -v
```

### 3. Launch Streamlit Server
```bash
streamlit run app.py
```
- Access the dashboard at `http://localhost:8501`.
- Deep-link directly to any of the 9 views via `?page=1` through `?page=9` (e.g., `http://localhost:8501/?page=4` for Profitability & Unit Economics).

---

## 3. Option B: Deploying to Streamlit Community Cloud

When you are ready to publish the repository to GitHub and deploy on [Streamlit Community Cloud](https://share.streamlit.io/):

1. **Push Repository to GitHub** (only when you choose to publish):
   - Verify `.gitignore` excludes `.venv/`, `.env`, `data/raw/*`, `data/processed/*`, and `*.duckdb`.
   - Commit code, `requirements.txt`, `.streamlit/config.toml`, `config/settings.example.toml`, `sql/`, `tests/`, `docs/`, and `screenshots/`.
2. **Create App in Streamlit Community Cloud**:
   - Sign in to `share.streamlit.io` and click **Create app**.
   - **Repository**: `<your-github-username>/D2C_Growth_Profitability_Control_Tower`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **Python version** (Advanced settings): `3.11` or `3.12` (recommended for fastest wheel installation).
   - **Secrets**: None required (the app requires zero API keys or external credentials).
3. **First-Boot Behavior**:
   - On the first cold boot, Streamlit Community Cloud installs `requirements.txt` and launches `app.py`.
   - `get_pipeline_state()` detects that `data/raw/orders.csv` is not yet on the container filesystem, generates the exact `seed = 42` dataset (`6,500` orders, `48,000` sessions), creates `d2c_analytics.duckdb`, and caches the validated analytical model across sessions.

---

## 4. Option C: Containerized Deployment (Docker / Render / Railway)

If deploying to a container platform (Render, Railway, Fly.io, Cloud Run), use the following reference `Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-generate synthetic data and DuckDB warehouse during image build for instant cold starts
RUN python -m src.generate_data && python -m src.pipeline

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

---

## 5. Pre-Deployment Security & Privacy Checklist
- [x] Zero API keys, database passwords, or tokens in code or git history.
- [x] `.env` and `.streamlit/secrets.toml` excluded in `.gitignore`.
- [x] Zero real customer PII (all records are pseudonymous `CUST-*`, `ORD-*`, `SES-*` synthetic entities).
- [x] Prominent synthetic-data disclosure banner rendered at the top of every dashboard view.
