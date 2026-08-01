#!/usr/bin/env bash
# Build the AgentVigilante sandbox image (with strace) and verify Docker is available.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-agentvigilante-sandbox:local}"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker CLI not found. Install Docker Desktop or the Docker Engine first." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker daemon is not running or not reachable." >&2
  exit 1
fi

echo "Building sandbox image: ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" -f "${ROOT}/docker/Dockerfile.sandbox" "${ROOT}"
echo "Setup complete. Run: python run.py"
echo "  (host git is required for Time Machine checkpoints)"
