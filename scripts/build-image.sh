#!/usr/bin/env bash
# Use when the host can reach PyPI but Docker build networking cannot.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
python -c 'import sys, platform; assert sys.version_info[:2] == (3, 12) and platform.system() == "Linux", "Use Python 3.12 on Linux for this wheel build"'
stage=$(mktemp -d "${TMPDIR:-/tmp}/quantmesh-wheels.XXXXXX")
trap 'rm -rf "$stage"' EXIT
python -m pip wheel -c constraints.txt --wheel-dir "$stage" .
docker build --build-context "wheels=$stage" -f Dockerfile.offline -t "${1:-quantmesh:local}" .
