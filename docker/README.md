# Docker Runtime

This directory contains the Compose-built runtime images and entrypoints.

- `product.Dockerfile` builds Maia Product.
- `hermes.Dockerfile` builds the Hermes runtime container used by Maia.
- `hermes-entrypoint.sh` materializes Hermes runtime configuration.

Docker Compose remains the canonical local runtime. Do not add parallel startup
scripts that install dependencies or run Product/Hermes another way.
