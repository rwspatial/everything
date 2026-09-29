# syntax=docker/dockerfile:1
# geotools: GDAL CLI + R + Python 3, all linked against ONE system GDAL/PROJ.
# Base: rocker/geospatial (Ubuntu 24.04 "noble"; GDAL 3.8.x, PROJ 9.4, GEOS, sf/terra/stars/spdep/gstat).
# Phase 5 workers-r / workers-py will be built FROM this image.
ARG ROCKER_TAG=4.6.1
FROM rocker/geospatial:${ROCKER_TAG}

LABEL org.opencontainers.image.description="Spatial app geotools: GDAL + R + Python 3 on one GDAL/PROJ build"

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH} \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PROJ_DIR=/usr

# Python 3 venv at /opt/venv via rocker's own script (also installs R 'reticulate'),
# plus the PostgreSQL client for psql, and proj-bin (the `proj` CLI that pyproj's
# source build calls to detect the system PROJ version; also gives cs2cs/projinfo).
RUN /rocker_scripts/install_python.sh \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client proj-bin \
 && rm -rf /var/lib/apt/lists/*

# R: database access. The spatial packages already ship with rocker/geospatial.
RUN install2.r --error --skipinstalled DBI RPostgres yaml

# Python: GDAL bindings pinned to the exact system GDAL version, then the
# GDAL/PROJ/GEOS-linking packages built from source (--no-binary) so they use the
# system libraries instead of bundling their own copies.
COPY requirements.txt /tmp/requirements.txt
RUN pip install "numpy<2" setuptools wheel \
 && pip install --no-build-isolation "GDAL==$(gdal-config --version)" \
 && pip install --no-binary pyogrio,rasterio,pyproj,shapely -r /tmp/requirements.txt \
 && python -c "from osgeo import gdal; import pyogrio, rasterio, pyproj; \
print('GDAL', gdal.__version__, '| pyogrio', pyogrio.__gdal_version_string__, \
'| rasterio', rasterio.__gdal_version__, '| PROJ', pyproj.proj_version_str)"

COPY entrypoint.sh /usr/local/bin/geotools-entrypoint
RUN chmod 0755 /usr/local/bin/geotools-entrypoint

ENTRYPOINT ["/usr/local/bin/geotools-entrypoint"]
CMD ["bash"]
