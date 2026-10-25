"""Command-line entry point."""

import argparse
import json
import sqlite3
import sys

from . import __version__
from .core import audit


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check SQLite values against STRICT column types.")
    parser.add_argument("database")
    parser.add_argument("table")
    parser.add_argument("--type", action="append", default=[], metavar="COLUMN=TYPE")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-samples", type=int, default=20)
    parser.add_argument("--max-rows", type=int, default=1_000_000)
    parser.add_argument("--max-seconds", type=float, default=30)
    parser.add_argument("--max-value-bytes", type=int, default=1_048_576)
    parser.add_argument("--include-values", action="store_true")
    parser.add_argument("--fail-on-conversion", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        overrides = {}
        for item in args.type:
            name, separator, target = item.rpartition("=")
            if not separator or not name or name in overrides:
                raise ValueError("each --type must be a distinct COLUMN=TYPE")
            overrides[name] = target
        result = audit(
            args.database,
            args.table,
            overrides,
            max_samples=args.max_samples,
            max_rows=args.max_rows,
            max_seconds=args.max_seconds,
            max_value_bytes=args.max_value_bytes,
            include_values=args.include_values,
        )
    except (OSError, ValueError) as exc:
        result = {"schema_version": 1, "ok": False, "complete": False, "error": str(exc)}
    except sqlite3.Error:
        result = {
            "schema_version": 1,
            "ok": False,
            "complete": False,
            "error": "SQLite could not open the input",
        }
    except KeyboardInterrupt:
        return 130
    result["fail_on_conversion"] = args.fail_on_conversion
    if args.fail_on_conversion and result.get("converted_cells", 0):
        result["ok"] = False
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
    else:
        print(
            f"rows={result.get('rows_scanned', 0)} "
            f"rejected={result.get('rejected_cells', 0)} "
            f"converted={result.get('converted_cells', 0)} "
            f"complete={result['complete']} ok={result['ok']}"
        )
        if "error" in result:
            print(result["error"], file=sys.stderr)
        for sample in result.get("samples", []):
            print(json.dumps(sample, ensure_ascii=True, allow_nan=False))
    return 2 if not result["complete"] else (0 if result["ok"] else 1)
