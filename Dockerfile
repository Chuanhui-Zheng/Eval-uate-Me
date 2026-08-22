FROM python:3.12-slim

# No data leaves the container unless you allow it: run with `--network none` for a hard guarantee
# (enforced by Docker, unlike the declaration-based privacy.local_only check).
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 evaluser

USER evaluser
WORKDIR /work
ENTRYPOINT ["evalharness"]
CMD ["--help"]
