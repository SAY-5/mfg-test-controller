.PHONY: dev test test-integration lint typecheck run simulate bench bench-regress up clean

# Iteration count for the test-cycle benchmark.
BENCH_ITERS ?= 200

# Coverage gate for the unit suite. Raised from the 65% baseline to 70%.
COV_MIN ?= 70

dev:
	poetry install

test:
	poetry run pytest tests/unit -q \
		--cov=mfg_test_controller --cov-report=term-missing \
		--cov-fail-under=$(COV_MIN)

test-integration:
	RUN_INTEGRATION=1 poetry run pytest tests/integration -q

lint:
	poetry run ruff check src tests bench
	poetry run black --check src tests bench

typecheck:
	poetry run mypy

run:
	poetry run mfg-ctl run plans/station_bringup.yaml

simulate:
	poetry run mfg-ctl simulate-fault --profile profiles/dmm.yaml --fault drift

bench:
	poetry run python bench/cycle_bench.py --iterations $(BENCH_ITERS)

bench-regress:
	poetry run python bench/cycle_bench.py --iterations $(BENCH_ITERS) --check --no-write

up:
	docker compose up --build

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis reports *.db
	find . -type d -name __pycache__ -exec rm -rf {} +
