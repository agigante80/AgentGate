# Testing

AgentGate uses `pytest` (with `pytest-asyncio` in `auto` mode) and enforces a
minimum coverage gate of **60%** in CI. Current coverage is ~86% across 800+ tests.

## Run the suite

```bash
pip install -r requirements.txt -r requirements-dev.txt

# Full suite
pytest tests/ -v --tb=short

# A single file / test
pytest tests/unit/test_bot.py -v
pytest tests/unit/test_bot.py::TestPrefix::test_default_prefix -v

# With coverage (matches the CI gate)
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=60
```

Layout: `tests/unit/` (pure logic), `tests/contract/` (backend interface compliance),
`tests/integration/` (history DB, factory).

## The README Tests / Coverage badges

The **Tests** and **Coverage** badges in the README are [shields.io `endpoint`](https://shields.io/badges/endpoint-badge)
badges. On every push to `main`, CI (`.github/workflows/ci-cd.yml`) runs the suite
with `--cov-report=json --junitxml`, then `scripts/gen_badges.py` derives two small
JSON files which a dedicated `badges` job publishes to the root of the orphan
**`badges`** branch:

- `tests.json` — passed-test count
- `coverage.json` — line-coverage percentage (green ≥80%, yellow ≥60%, red below)

shields.io reads those JSON files via `raw.githubusercontent.com/.../badges/<file>.json`.
The values are aggregate numbers only — no test names or paths are published.

You can regenerate the JSON locally to preview:

```bash
pytest tests/ --cov=src --cov-report=json --junitxml=test-results.xml
python scripts/gen_badges.py ./badges-out test-results.xml coverage.json
cat badges-out/tests.json badges-out/coverage.json
```
