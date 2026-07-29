# Data Engineering Upskill

Hands-on Python data engineering projects focused on ingesting, cleaning,
deduplicating, validating, and exporting data from multiple source systems.

## Projects

### `sk1-lab`

A guided customer data quality pipeline for ShopStream. It combines customer
records from CSV, JSON, and fixed-width sources, standardizes key fields,
deduplicates customers, runs quality checks, and exports golden datasets and
reports.

### `sk1-capstone`

An end-to-end HR data integration pipeline for GlobalTech's acquisition of
AcquiredCo. It unifies four HR sources, normalizes employee data, identifies
duplicate and ghost employees, validates data quality, and publishes a golden
employee dataset.

See [`sk1-capstone/README.md`](sk1-capstone/README.md) for architecture,
outputs, assumptions, and detailed usage.

## Getting started

Python 3.9 or later is recommended. Each project has its own requirements file
and should be run from its project directory.

Run the guided lab:

```bash
cd sk1-lab
python3 -m pip install -r requirements.txt
cd my_pipeline
python3 pipeline.py
```

Run the capstone:

```bash
cd sk1-capstone
python3 -m pip install -r requirements.txt
cd hr_pipeline
python3 pipeline.py
```

## Tests

Run each project's tests from its project directory:

```bash
python3 -m pytest -v
```
