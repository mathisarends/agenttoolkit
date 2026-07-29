#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tag=${1:-agenttoolkit-connected:latest}

docker build \
    --tag "$tag" \
    --file "$project_root/experiments/sandboxing/connected_sandbox.Dockerfile" \
    "$project_root"
