.PHONY: help install install-dev test test-unit test-integration test-auth lint format clean build

help:
	@echo "Available commands:"
	@echo "  make install          - Install SDK"
	@echo "  make install-dev      - Install with dev dependencies"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests"
	@echo "  make test-integration - Run integration tests"
	@echo "  make test-auth        - Run auth-focused tests"
	@echo "  make lint             - Run linting (ruff)"
	@echo "  make format           - Format code (black)"
	@echo "  make clean            - Clean build artifacts"
	@echo "  make build            - Build distribution package"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --cov=src

test-unit:
	pytest tests/unit/ -v --cov=src

test-integration:
	pytest tests/integration/ -v --cov=src

test-auth:
	pytest tests/unit/auth/ tests/integration/test_auth_flow.py -v --cov=src

lint:
	ruff check src/ tests/ examples/

format:
	black src/ tests/ examples/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf build/ dist/ *.egg-info .coverage .pytest_cache

build: clean
	python -m build

.DEFAULT_GOAL := help
