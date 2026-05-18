.PHONY: dev test test-integration lint typecheck run simulate up clean

dev:
	poetry install

test:
	poetry run pytest tests/unit -q

test-integration:
	RUN_INTEGRATION=1 poetry run pytest tests/integration -q

lint:
	poetry run ruff check src tests
	poetry run black --check src tests

typecheck:
	poetry run mypy

run:
	poetry run mfg-ctl run plans/station_bringup.yaml

simulate:
	poetry run mfg-ctl simulate-fault --profile profiles/dmm.yaml --fault drift

up:
	docker compose up --build

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis reports *.db
	find . -type d -name __pycache__ -exec rm -rf {} +
