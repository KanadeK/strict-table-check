"""Create synthetic input; refuses to replace an existing file."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
args = parser.parse_args()
with args.path.open("xb"):
    pass
with closing(sqlite3.connect(args.path)) as db, db:
    db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY, quantity TEXT, memo ANY);")
    db.executemany("INSERT INTO orders VALUES(?, ?, ?)", [(1, "005", "ok"), (2, "many", b"abc")])
print("Created two synthetic orders; quantity='many' cannot become INTEGER.")
