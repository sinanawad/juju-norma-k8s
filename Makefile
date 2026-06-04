.PHONY: lint fmt unit integration integration-smoke integration-setup clean

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

fmt:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

unit:
	uv run coverage run -m pytest tests/unit -v
	uv run coverage report

# --log-cli-level=INFO streams setup_env + jubilant logs live (bootstrap, deploy,
# per-op progress) so a hang/timeout shows WHERE it stalled — pytest's captured
# stdout is buffered and lost if the step is killed at the CI timeout.
integration:
	uv run pytest tests/integration -v --tb=short --log-cli-level=INFO

integration-smoke:
	uv run pytest tests/integration -v --tb=short --log-cli-level=INFO -m smoke

integration-setup:
	SETUP_ENVIRONMENT=1 uv run pytest tests/integration -v --tb=short --log-cli-level=INFO

clean:
	rm -rf *.charm __pycache__ .coverage htmlcov .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
