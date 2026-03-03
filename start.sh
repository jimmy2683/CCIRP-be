#!/bin/bash

# CCIRP Backend Start Script
# Ensures the server runs within the virtual environment context to avoid ModuleNotFoundErrors.

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment (.venv) not found."
    echo "Please run 'python3 -m venv .venv' and install requirements first."
    exit 1
fi

echo "🚀 Starting CCIRP Backend Server..."
./.venv/bin/python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
