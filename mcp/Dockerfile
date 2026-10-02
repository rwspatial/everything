# MCP servers (plan Phase 4). One image, one module per server; Claude Code runs them over stdio.
FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY spatial_mcp ./spatial_mcp
COPY tests ./tests

USER nobody
CMD ["python", "-m", "spatial_mcp.spatial_db"]
