# Builder image for cgp Linux binaries.
#
# Usage (x86_64):
#   docker build -t cgp-builder .
#   docker run --rm -v $(pwd)/out:/out cgp-builder
#
# The release build uses Rocky 8 plus CPython 3.9 with a shared library so the
# generated bundle stays runnable on our oldest supported Linux targets.

FROM rockylinux:8

ENV PYBIN=python3.9

RUN dnf install -y -q python39 python39-devel python39-pip binutils tar gzip && \
    dnf clean all

WORKDIR /build
COPY . .

RUN ${PYBIN} -m pip install -U pip setuptools wheel pyinstaller certifi && \
    ${PYBIN} -m pip install -e .

CMD ["sh", "-c", \
     "${PYBIN} -m PyInstaller --clean -n cgp --collect-data certifi \
       --specpath /tmp/_spec --distpath /tmp/_dist --workpath /tmp/_build \
       cursor_gui_patch/__main__.py && \
      tar -C /tmp/_dist -czf /out/cgp-linux-x86_64.tar.gz cgp"]
