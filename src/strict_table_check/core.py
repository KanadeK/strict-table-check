"""Probe values in an isolated STRICT table; never mutate the source database."""

from __future__ import annotations

import base64
import math
import sqlite3
import time
from pathlib import Path

TYPES = frozenset({"INT", "INTEGER", "REAL", "TEXT", "BLOB", "ANY"})


def identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def value_json(value):
    """Preserve types without emitting nonstandard JSON numbers."""
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"type": "real", "value": str(value)}
    return {"type": storage_type(value), "value": value}


def storage_type(value):
    if value is None:
        return "null"
    return {int: "integer", float: "real", str: "text", bytes: "blob"}[type(value)]


def audit(
    path: str | Path,
    table: str,
    overrides: dict[str, str] | None = None,
    *,
    max_samples: int = 20,
    max_rows: int = 1_000_000,
    max_seconds: float = 30,
    max_value_bytes: int = 1_048_576,
    include_values: bool = False,
) -> dict:
    """Check type conversion only, not a full CREATE TABLE or migration."""
    if sqlite3.sqlite_version_info < (3, 37, 0):
        raise ValueError("SQLite 3.37 or newer is required")
    if max_samples < 0 or max_rows < 1 or max_value_bytes < 1024:
        raise ValueError("invalid sample, row or value-size limit")
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be positive and finite")
    if not isinstance(table, str) or not table or "\0" in table:
        raise ValueError("table must be a nonempty identifier without NUL")
    source_path = Path(path).resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("source must be a regular database file")
    started = time.perf_counter()
    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=1)
    scratch = sqlite3.connect(":memory:")
    result = {
        "schema_version": 1,
        "sqlite_version": sqlite3.sqlite_version,
        "table": table,
        "scope": "column-types-only",
        "rows_scanned": 0,
        "rejected_cells": 0,
        "converted_cells": 0,
        "columns": [],
        "samples": [],
        "complete": False,
        "ok": False,
    }
    try:
        source.execute("PRAGMA query_only=ON")
        source.execute("PRAGMA trusted_schema=OFF")
        source.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, max_value_bytes)
        source.set_progress_handler(lambda: time.perf_counter() - started > max_seconds, 1000)
        source.execute("BEGIN")
        record = source.execute(
            "SELECT name, type FROM pragma_table_list WHERE schema='main' AND name=?", (table,)
        ).fetchone()
        if record is None or record[1] != "table" or table.lower().startswith("sqlite_"):
            raise ValueError("select an existing ordinary user table in main")
        metadata = source.execute("SELECT * FROM pragma_table_xinfo(?)", (table,)).fetchall()
        if any(column[6] != 0 for column in metadata):
            raise ValueError(
                "generated or hidden columns are unsupported; audit a plain projection"
            )
        overrides = dict(overrides or {})
        unknown = set(overrides) - {column[1] for column in metadata}
        if unknown:
            raise ValueError("override names must match stored column names exactly")
        for column in metadata:
            target = overrides.get(column[1], column[2]).upper().strip()
            if target not in TYPES:
                raise ValueError(
                    f"column {column[1]!r} needs an explicit --type mapping to a STRICT type"
                )
            result["columns"].append(
                {
                    "name": column[1],
                    "declared_type": column[2],
                    "target_type": target,
                    "storage_classes": {},
                    "rejected": 0,
                    "converted": 0,
                }
            )
        for target in sorted({col["target_type"] for col in result["columns"]}):
            scratch.execute(f"CREATE TABLE p_{target} (v {target}) STRICT")
        selection = ", ".join(identifier(col["name"]) for col in result["columns"])
        cursor = source.execute(f"SELECT {selection} FROM main.{identifier(table)}")
        for row in cursor:
            if result["rows_scanned"] >= max_rows:
                result["error"] = "row limit reached; remaining rows were not checked"
                break
            if time.perf_counter() - started > max_seconds:
                result["error"] = "time budget reached; remaining rows were not checked"
                break
            result["rows_scanned"] += 1
            for col, value in zip(result["columns"], row, strict=True):
                kind = storage_type(value)
                histogram = col["storage_classes"]
                histogram[kind] = histogram.get(kind, 0) + 1
                target = col["target_type"]
                converted = None
                try:
                    converted, target_kind = scratch.execute(
                        f"INSERT INTO p_{target}(v) VALUES (?) RETURNING v, typeof(v)", (value,)
                    ).fetchone()
                    scratch.execute(f"DELETE FROM p_{target}")
                except sqlite3.IntegrityError:
                    status = "rejected"
                    col["rejected"] += 1
                    result["rejected_cells"] += 1
                else:
                    if kind == target_kind and value == converted:
                        continue
                    status = "converted"
                    col["converted"] += 1
                    result["converted_cells"] += 1
                if len(result["samples"]) < max_samples:
                    sample = {
                        "scan_row": result["rows_scanned"],
                        "column": col["name"],
                        "source_type": kind,
                        "target_type": target,
                        "status": status,
                    }
                    if include_values:
                        sample["source"] = value_json(value)
                        if status == "converted":
                            sample["result"] = value_json(converted)
                    result["samples"].append(sample)
        else:
            result["complete"] = True
    except sqlite3.Error:
        # Engine exceptions may contain row values or SQL. Do not disclose them.
        result["error"] = "SQLite could not complete the scan (budget, size, schema or input error)"
    finally:
        source.close()
        scratch.close()
    result["ok"] = result["complete"] and result["rejected_cells"] == 0
    return result
