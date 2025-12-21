# Stage 1: Build with precompilation
FROM julia:1.12 AS builder

WORKDIR /app

# Copy project files
COPY Project.toml ./

# Install dependencies
RUN julia --project=. -e 'using Pkg; Pkg.instantiate()'

# Copy source code
COPY src/ src/

# Precompile the package (this triggers PrecompileTools workload)
RUN julia --project=. -e '
    using Pkg
    Pkg.precompile()
    # Force loading to trigger all precompilation
    using TagBot
    println("TagBot v$(TagBot.VERSION) precompiled successfully")
'

# Stage 2: Minimal runtime image
FROM julia:1.12

LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot
LABEL org.opencontainers.image.description "TagBot - Creates tags and releases for Julia packages"

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        gnupg \
        openssh-client \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy from builder
COPY --from=builder /app/Project.toml /app/
COPY --from=builder /app/src /app/src
COPY --from=builder /root/.julia /root/.julia

# Verify the installation works
RUN julia --project=. -e 'using TagBot; println("TagBot ready")'

# Entry point
CMD ["julia", "--project=.", "-e", "using TagBot; TagBot.main()"]
