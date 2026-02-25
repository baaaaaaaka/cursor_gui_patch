# Builder image for cgp Linux binaries.
#
# Usage (x86_64):
#   docker build -t cgp-builder .
#   docker run --rm -v $(pwd)/out:/out cgp-builder
#
# The build script (scripts/build_linux_binary_docker.sh) uses python:3.11-slim
# directly. This Dockerfile is provided as an alternative for custom builds.

FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y -qq binutils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .

RUN pip install -U pip setuptools wheel pyinstaller certifi && \
    pip install -e .

CMD ["sh", "-c", \
     "python -m PyInstaller --clean -n cgp --collect-data certifi \
       --specpath /tmp/_spec --distpath /tmp/_dist --workpath /tmp/_build \
       cursor_gui_patch/__main__.py && \
      tar -C /tmp/_dist -czf /out/cgp-linux-x86_64.tar.gz cgp"]
