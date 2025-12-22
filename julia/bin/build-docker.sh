#!/bin/bash
# Build and test the Julia TagBot Docker image
set -euo pipefail

IMAGE_NAME="tagbot-julia"
IMAGE_TAG="${1:-latest}"

echo "Building TagBot.jl Docker image..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo ""
echo "Testing that image loads successfully..."
docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" julia --color=yes --project=. -e '
    using TagBot
    println("✓ TagBot v$(TagBot.VERSION) loaded successfully")
    println("  Exports: $(join(names(TagBot), ", "))")
'

echo ""
echo "Image built successfully: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To push to GHCR:"
echo "  docker tag ${IMAGE_NAME}:${IMAGE_TAG} ghcr.io/juliaregistries/${IMAGE_NAME}:${IMAGE_TAG}"
echo "  docker push ghcr.io/juliaregistries/${IMAGE_NAME}:${IMAGE_TAG}"
