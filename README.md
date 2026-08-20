# Hub'Eau

## 1. What This Project Is Abouts

A scheduled, unattended ETL pipeline that ingests daily water-level observations
from **Hub'Eau** (France's official open water-data API), cleans and standardises
them, and publishes a versioned analytics-ready dataset.

The pipeline runs weekly with no human in the loop. That constraint — *nobody is
watching when it fails* — is what drives every design decision in this document.


## 2. Provenance and Differentiation

This project takes its patterns from the freeCodeCamp article "The ETL Pipeline Handbook: How to Build a Production-Grade Pipeline in Python" by brooklyn (July 2026).  The article stops at a Jupyter notebook. This repository builds the layer the article deliberately skips.

| The article does | This repo does |
| --- | --- |
| Jupyter notebook | Installable Python package (`uv` + `pyproject.toml`) |
| `print()` for progress | `structlog` structured JSON logs + a run manifest |
| `break` on any network error | Retry with exponential backoff, then fail cleanly |
| Claims idempotency | A test that **proves** run-twice == run-once |
| Hardcoded config constants | Env-driven config validated at startup (`pydantic-settings`) |
| Manual `python script.py` | GitHub Actions: CI on PR + weekly cron |
| No tests | `pytest` suite with mocked HTTP and a frozen clock |
| Kaggle CLI hardcoded into Load | `Writer` Protocol with two implementations (local, S3) |

---

## 3. Locked Design Decisions

### 3.1 Data source — Hub'Eau (kept)

Retained from the article. Rationale:

- Free, no API key, no rate-limit paperwork
- Genuine cursor-style pagination (20,000 records/page cap)
- Genuinely messy input: French column names, French categorical values,
  mixed types arriving as strings
- Updates daily, so **incremental loading is actually necessary** rather than
  a demonstration of a pattern that isn't needed

Endpoint: `https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab`
Metric: `HIXnJ` (daily maximum water level, elaborated observations)

### 3.2 Destination — local first, S3 second (Kaggle dropped)

The article publishes to Kaggle via the Kaggle CLI. Dropped, because:

1. Kaggle CLI auth in CI is friction that produces zero engineering signal.
2. It is the single most recognisable "followed the tutorial" marker.
3. It is inconsistent with how the other portfolio repos present themselves.

Replacement:

- **`LocalWriter`** (default) — writes CSV + Parquet to `data/output/`,
  committed back to the repo by the scheduled workflow.
- **`S3Writer`** — a second implementation of the same `Writer` Protocol.

The second implementation exists specifically to **prove the abstraction holds**.
An interface with exactly one implementation is not an abstraction; it's a
guess.

### 3.3 Configuration — `pydantic-settings`

The article uses `@dataclass` with `__post_init__` validation. That is a good
teaching pattern but it is not what production systems use for configuration.

Choosing `pydantic-settings` gives:

- Environment-variable and `.env` file loading (12-factor)
- Real validation with useful error messages at **startup**, not mid-run
- Nested settings groups (`api`, `stations`, `output`)
- Type coercion for free

`@dataclass` with `field(default_factory=...)` is still used where a plain
value object is the right fit (e.g. the run manifest), so the pattern is still
demonstrated in the codebase.

### 3.4 Scope ceiling — hard stop at Phase 8

Explicitly **out of scope**:

- Airflow / Prefect / Dagster — GitHub Actions cron is proportionate for a
  weekly job. Adding an orchestrator here would be resume-padding.
- Docker — the deployable artefact is a scheduled Action, not a service.
- A database — the output is a file-based analytics dataset.
- A dashboard / BI layer — not the point of this repo.

Any of these can be added later as an explicit, justified follow-up. None are
added just to lengthen the tech list.

---

## 4. Architecture

```
flood-etl/
├── pyproject.toml              # uv-managed; deps + ruff/mypy/pytest config
├── README.md
├── Makefile                    # make install / lint / typecheck / test / run
├── .env.example
├── .gitignore
│
├── .github/workflows/
│   ├── ci.yml                  # lint + mypy + pytest on push and PR
│   └── scheduled.yml           # weekly cron -> run pipeline -> commit output
│
├── src/flood_etl/
│   ├── __init__.py
│   ├── config.py               # pydantic-settings; validated at import
│   ├── logging_setup.py        # structlog JSON configuration
│   ├── manifest.py             # RunManifest dataclass (run metrics)
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── client.py           # HTTP session, timeout, retry, pagination
│   │   ├── mock.py             # deterministic fake API generator
│   │   └── incremental.py      # determine_update_range()
│   │
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── schema.py           # API_TO_EN, CATEGORICAL_MAPPINGS, COLUMN_ORDER
│   │   ├── coercion.py         # graceful type parsing
│   │   ├── dedup.py            # composite key + set-based filtering
│   │   └── pipeline.py         # postprocess(): sequencing only, no logic
│   │
│   ├── load/
│   │   ├── __init__.py
│   │   ├── base.py             # Writer Protocol
│   │   ├── local.py            # CSV + Parquet writer
│   │   ├── s3.py               # S3 writer
│   │   └── metadata.py         # dataset manifest / metadata JSON
│   │
│   ├── quality.py              # post-run validation gate
│   └── cli.py                  # entry point + argument parsing
│
├── tests/                      # mirrors src/ structure
│   ├── conftest.py             # shared fixtures, frozen clock
│   ├── test_config.py
│   ├── extract/
│   ├── transform/
│   ├── load/
│   └── test_idempotency.py     # the headline test
│
├── data/
│   ├── output/                 # committed: the published dataset
│   └── .gitignore              # everything else ignored
│
└── docs/
    └── plan_etl_pipeline.md    # this document
```

### Layer boundaries

- **Extract** knows about HTTP and about what data already exists. It knows
  nothing about column names or output formats.
- **Transform** is pure functions: DataFrame in, new DataFrame out, no I/O,
  no side effects. Every function starts with `df.copy()`.
- **Load** knows about destinations only. It receives a finished DataFrame.
- **`cli.py`** is the only module that wires the three together. It contains
  sequencing, not logic.

---

## 5. Core Patterns Being Implemented

These are the ideas the repo must actually demonstrate, not just mention.

### 5.1 Idempotency

Running the pipeline twice produces the same result as running it once.

Achieved through:

- Deduplication on a composite key: `station_code + record_date + water_level_mm`
  (the value is included deliberately — a revised reading for the same station
  and day is a distinct observation, not a duplicate)
- `Path.mkdir(parents=True, exist_ok=True)` for directory creation
- Atomic writes: write to a temp path, then rename

Verified by `tests/test_idempotency.py`, which runs the full pipeline twice
against the same fixture data and asserts byte-level equality of the output.

### 5.2 Incremental loading

Never re-download the full history. On each run:

1. Read the newest `record_date` already present in the output
2. Compare against **yesterday** (not today — today's reading may not be
   finalised upstream)
3. If already covered, exit early with a clear log line
4. Otherwise fetch only from `last_date + 1 day`

### 5.3 Graceful coercion

`errors="coerce"` on all type conversions. One malformed row becomes `NaT` /
`NaN` rather than killing an unattended run.

This is a deliberate trade-off: **availability over strictness**. To keep it
honest, coerced-to-null counts are recorded in the run manifest and surfaced in
the quality gate, so silent data rot is visible.

### 5.4 Consistent return types

Every function returns one type on every code path. `load_existing()` returns
an empty DataFrame rather than `None` (Null Object pattern), so no caller ever
needs a null check.

### 5.5 Single Responsibility in the fetch layer

```
fetch_all_stations()          <- loops and delegates; nothing else
    └── fetch_station()       <- pagination, cursors, retries, stop conditions
```

If fetching is ever parallelised, `fetch_all_stations()` is the only function
that changes.

### 5.6 One authoritative schema mapping

`API_TO_EN` is hand-maintained. `EN_TO_API` is derived by dict comprehension.
There is exactly one place in the codebase where a schema change happens.

### 5.7 Set-based membership for deduplication

Existing keys are held in a `set` (O(1) average lookup), not a `list` (O(n)).
On a dataset of tens of thousands of rows checked on every run, the difference
is real, not theoretical.

---

## 6. Execution Phases

Each phase ends with a concrete verification step. Nothing proceeds until the
previous phase's verification passes.

### Phase 0 — Scaffold and tooling

**Build:** repo init, `uv` project, `pyproject.toml`, ruff + mypy + pytest
configuration, `Makefile`, `.gitignore`, directory skeleton.

**Verify:** `make lint`, `make typecheck`, and `make test` all run cleanly on an
empty package.

---

### Phase 1 — Configuration layer

**Build:** `config.py` with `pydantic-settings`. Nested groups for API,
stations, and output. `.env.example`.

**Verify:** a deliberately invalid setting (e.g. `PAGE_SIZE=-1`) fails at
startup with a readable error. Tests cover defaults, env override, and
validation failure.

---

### Phase 2 — Logging and run manifest

**Build:** `logging_setup.py` (structlog, JSON to stdout, ISO timestamps),
`manifest.py` (`RunManifest` dataclass: rows read, rows fetched, rows new,
rows deduped, nulls coerced, duration, status).

**Verify:** a throwaway script emits parseable JSON log lines and a populated
manifest.

---

### Phase 3 — Extract, mock first

**Build:** `extract/mock.py` (deterministic, seeded fake API responses shaped
exactly like Hub'Eau) and `extract/incremental.py`
(`determine_update_range()`).

**Verify:** tests with a frozen clock cover all three branches — no existing
data, stale data, already-current data.

**Note:** the mock is built before the real client on purpose. Debugging
parsing logic and network flakiness at the same time is two mysteries at once.

---

### Phase 4 — Extract, real client

**Build:** `extract/client.py` — `requests.Session`, explicit timeout, retry
with exponential backoff, cursor pagination, and the four stop conditions
(empty response, latest date reaches yesterday, partial page, exhausted
retries).

**Verify:** tests with mocked HTTP cover multi-page pagination, an empty
response, a partial final page, a transient 500 that succeeds on retry, and a
timeout that exhausts retries. No test hits the network.

---

### Phase 5 — Transform

**Build:** `transform/schema.py`, `transform/coercion.py`,
`transform/pipeline.py`. Type parsing, French-to-English column renaming,
categorical value mapping with `.map().fillna()` passthrough, the derived
`flood_alert` column, column ordering, sorting.

**Verify:** each function tested in isolation. Round-trip test proves
`rename_to_api_schema(rename_to_english(df))` restores the original columns.
Messy-input test proves bad values become nulls without raising.

---

### Phase 6 — Deduplication and idempotency

**Build:** `transform/dedup.py` — composite key construction, set-based
filtering, indexing back into the **original** DataFrame (not the
type-coerced comparison copy).

**Verify:** `tests/test_idempotency.py` runs the full pipeline twice and
asserts identical output. This is the headline test of the repo.

---

### Phase 7 — Load and quality gate

**Build:** `load/base.py` (`Writer` Protocol), `load/local.py` (CSV +
Parquet, atomic write), `load/s3.py`, `load/metadata.py`, `quality.py`.

**Verify:** both writers satisfy the same test suite. The quality gate fails
the run on a seeded violation (e.g. null rate above threshold, non-monotonic
date coverage, zero rows written).

---

### Phase 8 — CI/CD and documentation

**Build:** `.github/workflows/ci.yml` (lint, typecheck, test on push and PR),
`.github/workflows/scheduled.yml` (weekly cron, run pipeline, commit updated
output), README, CV bullets.

**Verify:** CI green on a PR. Scheduled workflow triggered manually via
`workflow_dispatch` completes and commits.

---

## 7. Tech Stack

| Concern | Choice |
| --- | --- |
| Packaging | `uv`, `pyproject.toml`, src layout |
| Data | `pandas`, `pyarrow` (Parquet) |
| HTTP | `requests` |
| Config | `pydantic-settings` |
| Logging | `structlog` |
| Testing | `pytest`, `pytest-cov`, `responses` (HTTP mocking), `freezegun` |
| Lint / format | `ruff` |
| Types | `mypy` (strict on `src/`) |
| CI/CD | GitHub Actions |
| Cloud (optional path) | `boto3` for the S3 writer |

---

## 8. Definition of Done

The project is complete when all of the following hold:

- [ ] `make lint`, `make typecheck`, `make test` pass locally and in CI
- [ ] Test coverage above 80% on `src/flood_etl/`
- [ ] `tests/test_idempotency.py` passes — run twice, identical output
- [ ] No test makes a real network call
- [ ] A first run on an empty `data/` directory succeeds (cold start)
- [ ] A second immediate run exits early with "already current"
- [ ] The scheduled workflow has run at least once successfully
- [ ] README explains the architecture, credits the source article, and states
      what was added on top of it
- [ ] Every CV bullet is defensible against the actual repo contents
