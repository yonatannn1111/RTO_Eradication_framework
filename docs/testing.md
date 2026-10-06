# Testing

## Run all tests

    pytest -v

## Run one file

    pytest tests/test_forensics.py -v

## Coverage

    pytest --cov=modules --cov-report=term-missing

## What's covered

- `test_smoke.py` — every module imports cleanly
- `test_forensics.py` — hash determinism, diff detection
- `test_scheduler.py` — SimPy model runs and produces output

## CI

GitHub Actions runs on every push to `main`, `dev`, and `feature/**`.
See `.github/workflows/ci.yml`.