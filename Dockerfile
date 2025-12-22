FROM julia:1.12
LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gnupg \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set up Julia environment
WORKDIR /app
COPY julia/* ./
RUN julia --color=yes --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'

# Set entrypoint
ENV JULIA_PROJECT=/app
CMD ["julia", "--project=/app", "-e", "using TagBot; TagBot.main()"]
