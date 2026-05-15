#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
VENV_PATH="${1:-/tmp/industrial_sandbox_ml_training_v0_1_venv}"

mkdir -p "${UV_CACHE_DIR}"

env UV_CACHE_DIR="${UV_CACHE_DIR}" uv venv "${VENV_PATH}" --python 3.10
source "${VENV_PATH}/bin/activate"
export UV_PROJECT_ENVIRONMENT="${VENV_PATH}"
env UV_CACHE_DIR="${UV_CACHE_DIR}" uv sync --active --no-install-project

cat <<EOF
uv bootstrap completed.
project_root=${PROJECT_ROOT}
venv_path=${VENV_PATH}
cache_dir=${UV_CACHE_DIR}
uv_project_environment=${VENV_PATH}

next_steps:
  source "${VENV_PATH}/bin/activate"
  export UV_PROJECT_ENVIRONMENT="${VENV_PATH}"
  env UV_CACHE_DIR="${UV_CACHE_DIR}" uv run --active python scripts/generate_dataset.py --profile training_normal_v1
EOF
