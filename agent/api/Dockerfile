# Concho data API (P5.4) for the compose bundle (P6.6). Build context: the repository root.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY engines ./engines
COPY dashboards ./dashboards
RUN pip install ".[api]" && rm -rf /src
# the team repo is mounted read-only at /team, the SQLite database lives in the /db volume
RUN mkdir /db && chown nobody /db
USER nobody
WORKDIR /db
EXPOSE 8000
CMD ["concho-api", "serve", "--repo", "/team", "--db", "/db/concho.db", "--host", "0.0.0.0", "--port", "8000"]
