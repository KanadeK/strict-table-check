# Design and review

The unit of checking is a value under a proposed STRICT column type. SQLite
metadata supplies the declared types. Unsupported declarations require explicit
mapping. Probe tables contain no source constraints, triggers or expressions;
they have a single nullable column. Reports deliberately label this scope.

Memory stays bounded by the current row, SQLite's configurable length limit,
small metadata and diagnostic samples. The scratch table is emptied after each
successful insert. Source reads share a transaction. A sample limit never stops
the counting pass; a row/time limit is an incomplete result and cannot pass.

Review covered identifier quoting, URI escaping, missing-file noncreation,
explicit source connection closure, exceptions containing data, SQLITE_LIMIT_LENGTH
semantics, implicit coercions, empty tables and WAL visibility. Tests compare all
six target types to direct engine inserts. They also check source hashes and a
trigger counter. Windows exposed two fixture errors during development: an
invalid question-mark filename and SQLite context managers not closing connections.
Both were corrected; fixtures now close explicitly. No schema migration is run.

Known tradeoff: one insert/delete pair per cell is slower than a bulk conversion.
It gives complete rejection counts without retaining a second full database or
stopping at the first incompatible row. Scan positions are not persistent keys.
