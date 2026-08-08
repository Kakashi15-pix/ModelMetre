#!/bin/bash
# Test script

set -e

echo "Running LLM Cost Observability SDK tests..."

# Install dev dependencies
pip install -e ".[dev]"

# Run tests with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

echo "✓ Tests complete"
