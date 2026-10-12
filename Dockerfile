FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations/ migrations/
COPY src/ src/

# Optional CI-only stages (docker build --target lint|check|test). Not used by compose up.
FROM python:3.12-slim AS lint

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements-lint.txt .pylintrc ./
RUN pip install --no-cache-dir -r requirements-lint.txt

COPY src/ src/
COPY tests/ tests/
COPY scripts/ scripts/

CMD ["sh", "-c", "black --check --line-length 100 src tests scripts || exit 1; pe=0; pylint src || pe=$?; if [ $((pe & 1)) -ne 0 ] || [ $((pe & 2)) -ne 0 ] || [ $((pe & 32)) -ne 0 ]; then exit 1; fi; bandit -r src -ll -q"]

FROM python:3.12-slim AS check

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt requirements-lint.txt requirements-test.txt pytest.ini .pylintrc ./
RUN pip install --no-cache-dir -r requirements-test.txt -r requirements-lint.txt

COPY src/ src/
COPY tests/ tests/
COPY scripts/ scripts/

CMD ["sh", "-c", "failed=0; echo 'running black'; black --check --line-length 100 src tests scripts/ || failed=1; echo 'running pylint'; pe=0; pylint src || pe=$?; if [ \"$pe\" -ne 0 ]; then if [ $((pe & 1)) -ne 0 ] || [ $((pe & 2)) -ne 0 ] || [ $((pe & 32)) -ne 0 ]; then failed=1; fi; fi; echo 'running bandit'; bandit -r src -ll -q || failed=1; echo 'running pytest'; PYTHONPATH=src pytest -v || failed=1; exit \"$failed\""]

FROM runtime AS e2e

COPY scripts/ scripts/
CMD ["python", "scripts/e2e_suite.py"]

# Default `docker build` / compose app services use the runtime image (must be last).
FROM runtime
