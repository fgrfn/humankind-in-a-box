# The web frontend is committed in built form (src/hiab/web), so no Node is needed here.
FROM python:3.13-slim

# Which commit this image is built from, shown in the interface:
#   docker build --build-arg HIAB_COMMIT=$(git rev-parse --short HEAD) -t hiab .
ARG HIAB_COMMIT=unknown
ENV HIAB_COMMIT=$HIAB_COMMIT \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HIAB_DATA=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 1000 hiab && mkdir /data && chown hiab /data

USER hiab
VOLUME /data
EXPOSE 2222
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:2222/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["hiab", "run"]
