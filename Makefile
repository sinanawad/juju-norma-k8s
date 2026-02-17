.PHONY: lint fmt unit integration integration-setup clean

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

fmt:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

unit:
	uv run coverage run -m pytest tests/unit -v
	uv run coverage report

integration:
	uv run pytest tests/integration -v --tb=short

integration-setup:
	SETUP_ENVIRONMENT=1 uv run pytest tests/integration -v --tb=short

clean:
	rm -rf *.charm __pycache__ .coverage htmlcov .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
