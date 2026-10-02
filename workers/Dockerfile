# Analysis worker (plan Phase 5): FROM geotools, so processes see the same GDAL/PROJ, R and Python as make r / make py.
ARG ROCKER_TAG
FROM spatial/geotools:${ROCKER_TAG}

# PySAL for spatial statistics; the newest releases that still support numpy<2 (GDAL 3.8 bindings need numpy 1.x).
RUN pip install --no-cache-dir "numpy<2" esda==2.9.0 libpysal==4.14.1

WORKDIR /opt/workers
COPY worker ./worker
COPY processes ./processes
COPY rlib ./rlib
COPY --from=contracts process.v1.schema.json project-manifest.v1.schema.json validate.py ./contracts/

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WORKER_HOME=/opt/workers HOME=/tmp
ENTRYPOINT []
CMD ["python", "-m", "worker"]
