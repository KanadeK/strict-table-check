# strict-table-check

Find every incompatible value before converting a SQLite column to a STRICT type.
The source opens read-only. Each value is inserted into a one-cell STRICT table
in a separate in-memory database, so SQLite itself decides acceptance and coercion.
The report counts rejections and representation changes across the entire scan.

This checks **column types only**. A passing result does not approve a full table
rebuild: primary keys, NOT NULL, UNIQUE, foreign keys, CHECK expressions, generated
columns, triggers and defaults require separate migration tests.

## Install and try

Python 3.11+ with SQLite 3.37+ is required. No runtime packages or server.
Clone this repository, then run:

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
python examples/create_demo.py demo.sqlite
strict-table-check demo.sqlite orders --type quantity=INTEGER --format json
```

The command exits **1**: one value rejects INTEGER and one (`"005"`) converts to
integer 5. Values are hidden by default. For a compatible target:

```sh
strict-table-check demo.sqlite orders --type quantity=TEXT
```

This exits 0. Remove only the generated `demo.sqlite` file when done. Uninstall
with `python -m pip uninstall strict-table-check`; remove your virtual environment
if no longer needed. `python -m strict_table_check` is the equivalent module entry.
GitHub Releases provide wheels/source archives and SHA256SUMS. No PyPI publication
is claimed; install a downloaded wheel with `python -m pip install path/to/file.whl`.

## Controls and reports

```sh
strict-table-check app.sqlite records --type amount=REAL --type payload=ANY --fail-on-conversion
strict-table-check app.sqlite records --include-values --max-samples 10 --format json
strict-table-check app.sqlite records --max-rows 500000 --max-seconds 20
```

Types default to declared types, restricted to INT, INTEGER, REAL, TEXT, BLOB or
ANY. Other declarations (for example VARCHAR or NUMERIC) require an explicit
mapping; the tool never guesses. Column names match stored names exactly. A name
containing `=` can be mapped because the final `=` is the separator. Empty tables
produce a valid zero-row type report. Views, virtual/shadow tables and tables with
generated columns are rejected explicitly.

Exit codes: **0** complete and no rejected cells; **1** complete with rejections
(or conversions when `--fail-on-conversion` is set); **2** invalid input or
incomplete scan; **130** interrupted. Conversion counts include storage-class
changes and value changes, even when SQLite accepts them. NULL is accepted by the
type probe; target nullability is outside its scope.

JSON `schema_version: 1` contains table/column metadata, original storage-class
histograms, rejected/converted counts, bounded samples, `complete`, and `ok`.
`scan_row` is the 1-based position in that scan, **not a primary key or persistent
row address**. Samples share a global cap (default 20); totals continue afterward.
Opt-in values use tagged JSON; BLOBs use base64 and non-finite reals use strings.

```python
from strict_table_check.core import audit

report = audit("app.sqlite", "orders", {"quantity": "INTEGER"})
assert report["complete"] and report["ok"]
```

## Safety and limits

`mode=ro`, `query_only=ON`, `trusted_schema=OFF`, and one read transaction protect
source contents and keep the scan consistent. Committed WAL data is visible;
SQLite may use/create WAL/SHM coordination sidecars. The tool doesn't use
`immutable=1`, execute source triggers, load extensions, or run supplied SQL.
Use a coherent backup if you need filesystem isolation.

Defaults: 1,000,000 rows, 30 seconds, 1 MiB SQLite value/record length limit.
SQLite's length limit also applies to encoded rows and schema expressions, so a
wide row can hit it even if each cell is smaller. Limits or engine read errors
produce an incomplete report and exit 2. The time budget is cooperative, not a
hard process deadline. The implementation uses O(row width + bounded samples)
memory, and one SQLite insert per cell; it prioritizes correct diagnostics over
bulk-load speed. Source text must decode as UTF-8 using Python's SQLite adapter.
Custom collation/function dependencies and unusual schema builds may fail.

SQLite's [STRICT rules](https://www.sqlite.org/stricttables.html) are the reference.
[sqlite-utils](https://github.com/simonw/sqlite-utils/issues/787) can perform actual
STRICT transformations; this tool adds an offline diagnostic pass over existing
values without changing the source. It does not recover representations already
lost under the source table's affinity.

## 中文说明

迁移到 SQLite STRICT 类型前，逐个检查现有单元格，汇总所有拒绝和隐式转换。
使用真正的 SQLite STRICT 表判断，源库只读，默认不输出数据值。支持列类型映射、
JSON 报告、数量和时间限制。只验证类型，不验证完整迁移、主键、非空或其他约束。
退出 0 表示类型检查通过；1 表示发现问题；2 表示输入错误或未检查完。
