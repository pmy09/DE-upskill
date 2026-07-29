# Golden Employee Dataset Schema

Unified, cleaned, and deduplicated employee records exported as Parquet partitioned by `company_origin`.

Generated: 2026-07-29T12:03:27
Record count: 18,001

| column_name | data_type | description | example_value |
|---|---|---|---|
| `employee_id` | `string` | Canonical namespaced employee ID (GT-###### or AC-######) | AC-000000 |
| `first_name` | `string` | Standardized given name (Unicode NFKC, title case) | John |
| `last_name` | `string` | Standardized family name (Unicode NFKC, title case) | Allen |
| `email` | `object` | Work email address used for identity matching | john.allen@acquiredco.com |
| `department` | `string` | Mapped standard department name | Quality Assurance |
| `job_title` | `object` | Job title as provided by the source HRIS | Sales Representative |
| `hire_date` | `datetime64[ns]` | Parsed hire date (datetime64[ns]) | 2015-11-24T00:00:00 |
| `country` | `object` | Work location country | United Kingdom |
| `employment_type` | `string` | Standard employment type: Full-Time, Part-Time, or Contractor | Part-Time |
| `employment_status` | `object` | Employment status when provided by the source | Active |
| `manager_id` | `string` | Namespaced manager employee ID, when present | AC-002436 |
| `company_origin` | `object` | Partition key: GlobalTech or AcquiredCo | AcquiredCo |
| `source_system` | `object` | Primary contributing source system for the surviving row | acquiredco_hris |
| `employee_id_raw` | `object` | Original employee ID before namespacing | ACQ_DUP_00000 |
| `manager_id_raw` | `object` | Original manager ID before namespacing | ACQ_02436 |
| `department_original` | `object` | Department value before taxonomy mapping | Quality Assurance |
| `department_unmapped` | `bool` | True when the original department was not in the taxonomy map | False |
| `hire_date_invalid` | `bool` | True when hire_date could not be parsed cleanly | False |
| `payroll_effective_date_invalid` | `bool` | True when payroll_effective_date was invalid | False |
| `benefit_enrollment_date_invalid` | `bool` | True when benefit_enrollment_date was invalid | False |
| `source_systems` | `string` | Comma-separated provenance of all contributing sources | acquiredco_hris |
| `dedup_method` | `string` | How the row was resolved: exact_id, email_match, fuzzy_name, or single_source | single_source |
| `base_salary` | `object` | Original salary amount before FX / frequency conversion | 47742 |
| `currency` | `string` | ISO currency code for base_salary (USD, EUR, GBP) | GBP |
| `pay_frequency` | `string` | Payroll frequency: Annual, Monthly, or Bi-Weekly | Monthly |
| `bonus_target_pct` | `float64` | Target bonus percentage from payroll, when present | 4.0 |
| `payroll_effective_date` | `datetime64[ns]` | Effective date of the retained payroll record | 2024-12-03T00:00:00 |
| `salary_usd_annual` | `Float64` | Annualized salary converted to USD using configured FX rates | 727588.08 |
| `benefits_enrolled` | `bool` | True when the employee has at least one benefits enrollment | False |
| `benefit_plans` | `string` | Aggregated benefit plan names for the employee | Dental |
| `benefit_plan_count` | `int64` | Number of distinct benefit plans enrolled | 0 |
| `benefit_coverage_level` | `object` | Coverage level from the latest enrollment | Employee+Child |
| `benefit_enrollment_date` | `datetime64[ns]` | Most recent benefit enrollment date | 2024-05-29T00:00:00 |
| `premium_employee` | `object` | Employee premium amount from benefits | 418.11 |
| `premium_employer` | `object` | Employer premium amount from benefits | 333.15 |
