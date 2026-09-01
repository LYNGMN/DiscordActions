#!/usr/bin/env bash
set -euo pipefail

REQUIRED_PIP_TOOLS_VERSION="7.6.1"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.12" ]]; then
  echo "Dependency locking requires Python 3.12; found $python_version." >&2
  exit 1
fi

pip_tools_version="$("$PYTHON_BIN" -c 'import importlib.metadata; print(importlib.metadata.version("pip-tools"))' 2>/dev/null || true)"
if [[ "$pip_tools_version" != "$REQUIRED_PIP_TOOLS_VERSION" ]]; then
  echo "Install pip-tools==$REQUIRED_PIP_TOOLS_VERSION in the Python 3.12 environment." >&2
  exit 1
fi

CUSTOM_COMPILE_COMMAND="python -m piptools compile --generate-hashes --index-url=https://pypi.org/simple --output-file=.github/requirements.txt --strip-extras .github/requirements.in" \
  "$PYTHON_BIN" -m piptools compile \
  --generate-hashes \
  --index-url=https://pypi.org/simple \
  --output-file=.github/requirements.txt \
  --strip-extras \
  .github/requirements.in

CUSTOM_COMPILE_COMMAND="python -m piptools compile --generate-hashes --index-url=https://pypi.org/simple --output-file=.github/requirements-youtube.txt --strip-extras .github/requirements-youtube.in" \
  "$PYTHON_BIN" -m piptools compile \
  --generate-hashes \
  --index-url=https://pypi.org/simple \
  --output-file=.github/requirements-youtube.txt \
  --strip-extras \
  .github/requirements-youtube.in
