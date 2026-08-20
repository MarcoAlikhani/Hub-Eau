# 🧱 Phase 0 — Scaffold & Tooling

**Project:** `flood-etl` · **Status:** ✅ Complete · **Python:** 3.12.13

---

## 🎯 Goal

Build an empty, installable package where **lint, format, typecheck, and test all
pass** — before a single line of pipeline logic exists.

The reasoning: guardrails installed on day one cost nothing. Guardrails installed
after 800 lines cost an afternoon of fixing violations. This is the cheapest
moment this work will ever be.

---

## 📦 What Was Built

| Artefact | Purpose |
| --- | --- |
| `uv` project, src layout | Installable package; tests import the *installed* code, not loose files |
| `pyproject.toml` tool config | Single config file for ruff, mypy, pytest, coverage, poe |
| Directory skeleton | `extract/`, `transform/`, `load/` in both `src/` and `tests/` |
| `.gitignore` | Ignore-broad-then-re-allow-narrow pattern for `data/` |
| `poethepoet` tasks | Cross-platform task runner; same commands locally and in CI |
| `tests/test_smoke.py` | 8 tests proving every subpackage is a real, importable package |

**Final verification output:**

```
Poe => ruff check .          All checks passed!
Poe => ruff format --check . 10 files already formatted
Poe => mypy                  Success: no issues found in 4 source files
Poe => pytest                8 passed in 0.10s
```

---

## 🧠 Decisions Made

### 1. `uv init --package` (src layout) over a flat script folder

With a `src/` layout, tests can only import `flood_etl` **if it is actually
installed**. This catches missing `__init__.py` files, broken packaging, and
"works because the file happened to be in the current directory" bugs before CI
does.

### 2. `poethepoet` over `Makefile`

The plan originally specified a `Makefile`. `make` is not installed on Windows,
so a Makefile would have been a file only CI could run — meaning CI becomes the
first place a failure is discovered. That is exactly the loop a task runner
exists to shorten.

Poe keeps task definitions inside `pyproject.toml` and runs identically on
Windows, Linux, and CI. The cost is recognisability: `make test` is universally
understood, `uv run poe test` needs a README line.

### 3. mypy `strict = true` from the start

Strict mode makes the article's central correctness lesson — *"return a
consistent type from every code path"* — a compile-time error rather than a
convention. The bug the article warns about becomes impossible to ship.

### 4. `boto3` as an optional extra, not a core dependency

The S3 writer is one of two `Writer` implementations. Anyone using only
`LocalWriter` should not be forced to install the AWS SDK. Confirmed working:
`uv sync` correctly uninstalled boto3, and `uv sync --extra s3` restores it.

---

## ❓ Questions & Answers

### Q: Why append config blocks to `pyproject.toml` instead of separate files?

Without them you would need `.ruff.toml`, `mypy.ini`, `pytest.ini`, and
`.coveragerc` — four files, four syntaxes, four places to search when something
misbehaves.

This is the same lesson the source article teaches about pipeline configuration
(*centralise the knobs*), applied one layer up to the tooling. It also means your
machine and CI enforce identical rules, so "passes locally, fails in CI" cannot
happen.

---

### Q: What does `[project.scripts]` actually do?

```toml
flood-etl = "flood_etl.cli:main"
#    ↓            ↓         ↓
# command      module    function
```

At install time, `uv` generates a wrapper executable that imports the module and
calls the function.

**The trap it avoids:** running a file by path (`python src/flood_etl/cli.py`)
puts *that file's folder* on the import path rather than the project root, and
relative imports break confusingly. An entry point always imports the properly
installed package. The Phase 8 cron job becomes one clean line: `uv run flood-etl`.

---

### Q: Which ruff rules matter most here, and why?

| Code | Catches |
| --- | --- |
| `B` (bugbear) | **The mutable default trap** — `stations: list[str] = []`. The single most-discussed gotcha in the source article, now a lint error |
| `RET` | Inconsistent return statements — the other correctness lesson from the article |
| `F` | Unused imports, undefined names — real bugs, not style |
| `I` | Import grouping (stdlib / third-party / first-party), which PEP 8 specifies and the article calls out |
| `PD` | pandas anti-patterns (`inplace=True`, `.ix[]`) |
| `PTH` | Prefer `Path` over `os.path` |

`src = ["src", "tests"]` is what tells ruff which imports are first-party, so
import sorting works correctly.

---

### Q: Why do tests get a looser ruleset?

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["ARG", "PD"]
```

Test code legitimately breaks two rules: pytest fixtures arrive as arguments that
are sometimes unused (`ARG`), and tests build throwaway DataFrames in ways that
would be sloppy in production (`PD`).

**The principle:** do not loosen a rule globally to accommodate one context.
Scope the exception. Production code stays strict.

The same reasoning applies to the mypy override — tests are exempt from
`disallow_untyped_defs`, because fixtures and monkeypatching fight strict typing
constantly and a wrong test simply fails, which is its own check.

---

### Q: What is `--cov-report=term-missing` for?

It prints the exact line numbers no test touches:

```
Name                        Stmts   Miss  Cover   Missing
flood_etl/extract/client.py    47      6    87%   62-64, 88-90
```

Those uncovered lines are almost always the error-handling branches — the retry
path, the timeout path. Exactly the code that only executes at 3am when nobody is
watching. The report tells you where to aim next.

---

### Q: Why exclude lines from coverage at all?

```toml
exclude_lines = ["pragma: no cover", "if __name__ == .__main__.:", "if TYPE_CHECKING:"]
```

The entry guard never runs during tests by design, and `TYPE_CHECKING` blocks
never execute at runtime. If untestable-by-design lines drag the number to 78%,
you learn to ignore the metric — and then stop noticing when a genuinely untested
retry branch appears.

Excluding them keeps 80% meaningful.

*(Those strings are regex patterns, which is why dots surround `__main__` — the
dot matches either quote style.)*

---

### Q: Why did `import flood_etl.extract` succeed on an empty folder?

Because of **PEP 420 implicit namespace packages** (Python 3.3+): a directory
with no `__init__.py` is still importable. The initial verification produced a
false positive for exactly this reason.

Namespace packages are fine for plugin systems but cause subtle problems for a
normal package — mypy skips them, pytest collection gets confused, and a build
may silently omit them from the wheel.

**The fix became a test.** `test_smoke.py` checks `module.__file__ is not None`;
regular packages have it set, namespace packages do not. The bug is now
impossible to reintroduce silently.

---

### Q: Why is `ruff check` separate from `ruff check --fix`?

| Command | Behaviour | Used by |
| --- | --- | --- |
| `ruff check .` | Reports only | **CI** — must fail the build, not rewrite code |
| `ruff check --fix .` | Rewrites in place | **You**, locally |

If CI auto-fixed, a broken PR would quietly become a passing one and the author
would never learn what went wrong. Reporting and repairing are different jobs.

This is why `poe lint` is bound to the non-fixing version, with a separate
`poe fix` task for local repair.

---

### Q: What does "Sequence aborted after failed subtask 'lint'" mean?

Fail-fast, and it is correct. Lint failed, so poe stopped and never ran
typecheck, fmt-check, or test.

If formatting is broken, running the test suite is wasted time. The cheapest
check fails first and stops the line — the same principle the source article
applies to the pipeline: *guard expensive steps behind cheap ones*.

---

### Q: Why does a missing trailing newline (W292) matter?

POSIX defines a line as text terminated by a newline, so a file without one ends
with a technically incomplete line. Practical consequences: `cat file1 file2`
merges the last and first lines, git diffs show `\ No newline at end of file` and
the next edit touches a line that should not have changed, and some older tools
drop the final line.

**Fixed at the class level, not the instance level:** `.vscode/settings.json` sets
`files.insertFinalNewline: true`, so the editor adds it before ruff ever sees the
file.

---

## ⚠️ Known Issues Carried Forward

| Item | Status |
| --- | --- |
| Repo name mismatch — local `flood-etl` vs GitHub `Hub-Eau` | Unresolved; pick one and align |
| Git `LF will be replaced by CRLF` warnings | Needs a `.gitattributes` to normalise line endings before CI runs on Linux |
| pandas 3.0 behaviour changes (copy-on-write default, dedicated string dtype) | To be verified empirically in Phase 5, not assumed |

---

## 📋 Cheat Sheet

### Daily commands

```powershell
uv run poe fix        # auto-repair lint issues + reformat
uv run poe check      # lint -> fmt-check -> typecheck -> test (fail-fast)
uv run poe            # list all available tasks
uv sync               # install/refresh dependencies from the lockfile
uv sync --extra s3    # include the optional boto3 dependency
uv add <pkg>          # add a runtime dependency
uv add --dev <pkg>    # add a dev-only dependency
```

### Config block reference

| Block | Controls |
| --- | --- |
| `[project.scripts]` | The `flood-etl` terminal command |
| `[tool.ruff]` | Line length 100, target py312, first-party dirs |
| `[tool.ruff.lint]` | Which of ruff's 800+ rules are active |
| `[tool.ruff.lint.per-file-ignores]` | Scoped exceptions for `tests/` |
| `[tool.mypy]` | `strict = true`, scanning `src/` only |
| `[tool.pytest.ini_options]` | Test paths, coverage flags, strict markers |
| `[tool.coverage.report]` | Lines excluded from the coverage denominator |
| `[tool.poe.tasks]` | Named task definitions |

### Concepts to remember

| Concept | One-line version |
| --- | --- |
| **src layout** | Tests import the installed package, so packaging bugs surface early |
| **PEP 420 namespace package** | A folder with no `__init__.py` still imports — always add one |
| **Fail-fast sequencing** | Cheapest check runs first and stops the line |
| **Report vs repair** | CI reports; only humans repair |
| **Scoped exceptions** | Loosen a rule for one directory, never globally |
| **Ignore broad, re-allow narrow** | `data/*` then `!data/output/` — use `data/*`, not `data/` |
| **Optional extras** | Second-tier dependencies stay out of the default install |
| **Strict mypy early** | Free now, expensive later |

### Guiding principle

> **Make the correct thing automatic, and the incorrect thing loud.**
>
> Mutable default → ruff error. Inconsistent return type → mypy error. Typo'd
> marker → pytest error. Untested error path → visible in the coverage report.

---

**Next:** Phase 1 — configuration layer with `pydantic-settings`.
