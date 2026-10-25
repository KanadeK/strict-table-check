# Contributing

Start with an issue describing a reproducible problem and synthetic input. Do not
upload private database files or production records. Keep changes focused and add
a regression test for changed behavior.

```sh
python -m venv .venv
# Activate it for your shell, then:
python -m pip install -e . ruff==0.17.2 build==1.6.1
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
```

Tests use temporary synthetic data. Runtime dependencies should remain minimal.
Changes to reports need a documented compatibility decision. CI only tests and
builds; it never commits code or enables automated dependency merges.
