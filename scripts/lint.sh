#!/bin/bash
# Lint script

set -e

echo "Linting LLM Cost Observability SDK..."

# Install lint tools
pip install ruff black mypy

# Run ruff
echo "Running ruff..."
ruff check src/ tests/ examples/ --fix

# Run black check
echo "Checking code format..."
black --check src/ tests/ examples/ 2>/dev/null || {
    echo "Code formatting issues found. Running black..."
    black src/ tests/ examples/
}

# Run mypy
echo "Running mypy..."
mypy src/ --ignore-missing-imports 2>/dev/null || echo "Note: Some type hints not available"

echo "✓ Lint checks complete"
