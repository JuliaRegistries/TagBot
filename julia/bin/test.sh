#!/bin/bash
# Run tests for TagBot.jl
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running TagBot.jl tests..."
julia --project=. -e '
    using Pkg
    Pkg.instantiate()
    Pkg.test()
'
