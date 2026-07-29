# GlobalTech HR Data Integration Pipeline

Day-1 integration pipeline that unifies GlobalTech and AcquiredCo employee data after acquisition. It loads four heterogeneous HR sources, cleans and namespaces identifiers, deduplicates across systems, validates data quality, produces an EDA report, and publishes a golden employee dataset for downstream HR analytics.

## Business context

GlobalTech acquired AcquiredCo and needs a single trustworthy employee spine on day one. Source systems disagree on ID formats, employment-type codes, salary currencies, and department labels. This pipeline creates one cleaned employee record per person (where confidently matched), flags payroll-only "ghost" employees, and routes fuzzy name matches to HR for review instead of auto-merging.

## Pipeline stages

```text
raw files
  → ingest.py      standardize four sources onto a common schema
  → clean.py       names, IDs, FX salaries, departments, dates
  → dedup.py       exact ID → email → fuzzy name; ghosts + probable matches
  → validate.py    ≥12 quality checks + FAIL-count gate
  → visualize.py   six-chart 300 DPI EDA PNG
  → export.py      golden Parquet, schema doc, review CSVs
```

Orchestration lives in `hr_pipeline/pipeline.py`.
See [`docs/architecture.md`](docs/architecture.md) for component boundaries,
runtime flow, data contracts, failure handling, and design decisions.

## Input sources

| Source | Path | Format | Grain / notes |
|---|---|---|---|
| GlobalTech HRIS | `data/raw/globaltech_hris.csv` | CSV (UTF-8) | ~15,000 employees; flat Workday-style columns |
| AcquiredCo HRIS | `data/raw/acquiredco_api.json` | JSON | ~3,200 employees; nested BambooHR-style payload; ingestion simulates API pagination |
| Combined payroll | `data/raw/payroll_data.xlsx` | Excel | ~19,000 payroll rows; mixed currency symbols and pay frequencies |
| Benefits | `data/raw/benefits_enrollment.xml` | XML | ~12,000 enrollments (GlobalTech-focused); aggregated to employee grain before join |

All sources are aligned to the configured standard schema in `hr_pipeline/config.py` (`CONFIG["standard_schema"]`), then cleaned.

## Output files

| Output | Path | Format | Description |
|---|---|---|---|
| Golden employees | `data/processed/golden_employees/` | Parquet (partitioned by `company_origin`) | Unified cleaned/deduplicated employee records |
| Schema documentation | `docs/schema.md` | Markdown | Column name, data type, description, example value |
| Ghost employees | `data/processed/ghost_employees.csv` | CSV | Payroll IDs with no HRIS match (`payroll_employee_id`, `name`, `salary_usd_annual`, `ghost_flag_reason`, …) |
| Probable matches | `data/processed/probable_matches.csv` | CSV | Fuzzy pairs for HR review (`record_1_id`, `record_2_id`, `similarity_score`, `hire_date_diff_days`, `recommended_action`, …) |
| Quality report | `data/processed/quality_report.csv` / `.html` | CSV + HTML | Per-check pass/fail summary |
| EDA report | `data/processed/hr_eda_report.png` | PNG @ 300 DPI | Six-chart visualization dashboard |
| Unmapped departments | `data/processed/unmapped_departments.csv` | CSV | Department values needing taxonomy review |
| Dead letters | `data/processed/dead_letter/*_dead_letters.csv` | CSV | Malformed/rejected ingest records |
| Pipeline log | `logs/pipeline.log` | Text | Stage logs and gate decisions |

Read golden partitions with pandas:

```python
import pandas as pd

employees = pd.read_parquet("data/processed/golden_employees")
globaltech = pd.read_parquet("data/processed/golden_employees/company_origin=GlobalTech")
```

## How to run

From the project root:

```bash
pip3 install -r requirements.txt
cd hr_pipeline
python3 pipeline.py
```

Optional walkthrough notebook:

```bash
jupyter notebook notebooks/capstone_pipeline.ipynb
```

Stage entry points (also usable from Python):

- `run_ingestion()`
- `run_cleaning()`
- `run_deduplication()`
- `run_validation()`
- `run_eda()`
- `run_export()`
- `run_pipeline()`

## Quality gate

Each check PASSes when its pass rate meets `CONFIG["quality_threshold"]` (default 95%). The pipeline halts with a critical error when more than `CONFIG["max_failed_quality_checks"]` (default 2) checks FAIL, before EDA / golden export.

## Known limitations and assumptions

1. **Department taxonomy** — Both HRIS extracts already use English department names, not GlobalTech codes like `ENG-01`. Mapping is still applied; unknown values are logged.
2. **Date formats** — Brief examples differ from the files. Cleaning accepts multiple formats; AcquiredCo uses ISO timestamps and benefits uses `YYYY-MM-DD`.
3. **Employee IDs** — Namespaced to `GT-######` / `AC-######`. AcquiredCo `ACQ_*` IDs are normalized by stripping the prefix.
4. **Email cross-match (Pass 2)** — Cross-company email collisions are rare or empty in this synthetic dataset; the pass is still implemented.
5. **Fuzzy matches (Pass 3)** — Candidates are written for HR review only; they are not auto-merged into the golden dataset.
6. **Salary annualization** — Monthly × 12 and Bi-Weekly × 26 can produce values above the $2M validation ceiling on this dataset; those rows FAIL the numeric-range check but do not alone halt the gate.
7. **Email uniqueness** — Many shared emails exist in the synthetic HRIS data, so the UNIQUE email check often FAILs.
8. **Benefits coverage** — Benefits primarily cover GlobalTech; AcquiredCo employees may show `benefits_enrolled=False`.
9. **FX rates** — Fixed project rates in config (`USD=1.00`, `EUR=1.09`, `GBP=1.27`), not live market rates.
10. **Ghost employees** — Current extracts produce zero ghosts after namespacing; the report CSV is still written with the required headers.

## Project layout

```text
sk1-capstone/
├── data/raw/                 # source extracts
├── data/processed/           # golden + reports
├── docs/
│   ├── architecture.md       # system architecture and data flow
│   └── schema.md             # golden schema documentation
├── hr_pipeline/
│   ├── config.py
│   ├── ingest.py
│   ├── clean.py
│   ├── dedup.py
│   ├── validate.py
│   ├── visualize.py
│   ├── export.py
│   └── pipeline.py
├── notebooks/
│   └── capstone_pipeline.ipynb
├── requirements.txt
└── README.md
```

## Change log

| Date | Change |
|---|---|
| 2026-07-23 | Deliverable 6: golden Parquet partitioned by `company_origin`, `docs/schema.md`, README, final export stage |
| 2026-07-23 | Deliverable 5: six-chart EDA PNG at 300 DPI (`visualize.py`) |
| 2026-07-23 | Deliverable 4: `DataQualityValidator`, CSV/HTML quality report, FAIL-count gate |
| 2026-07-23 | Centralized output writing in `export.py` |
| 2026-07-22 | Deliverable 3: multi-pass dedup, ghosts, probable-match review |
| 2026-07-21 | Deliverables 1–2: multi-source ingest + cleaning/transformation |
