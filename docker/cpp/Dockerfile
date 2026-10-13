FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ clang make cmake ninja-build && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
