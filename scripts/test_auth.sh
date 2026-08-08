#!/bin/bash
# Run auth-focused SDK tests.

set -e

echo "Running auth-focused SDK tests..."

pip install ".[dev]"
pytest tests/unit/auth/ tests/integration/test_auth_flow.py -v --cov=src --cov-report=term-missing

echo "✓ Auth tests complete"
