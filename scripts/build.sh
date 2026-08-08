#!/bin/bash
# Build script

set -e

echo "Building LLM Cost Observability SDK..."

# Install build dependencies
pip install build

# Build wheel and source distribution
python -m build

echo "✓ Build complete"
echo "Artifacts in: dist/"
ls -lh dist/
