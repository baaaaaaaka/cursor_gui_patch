# Builder image for cgp Linux binaries.
#
# Usage (x86_64):
#   docker build -t cgp-builder .
#   docker run --rm -v $(pwd)/out:/out cgp-builder
#
# The release build pins a manylinux_2_28 base so the generated bundle stays
# runnable on our oldest supported Linux targets (for example Rocky 8).

FROM quay.io/pypa/manylinux_2_28_x86_64

ENV PYBIN=/opt/python/cp311-cp311/bin

WORKDIR /build
COPY . .

RUN ${PYBIN}/python -m pip install -U pip setuptools wheel pyinstaller certifi && \
    ${PYBIN}/python -m pip install -e .

CMD ["sh", "-c", \
     "${PYBIN}/python -m PyInstaller --clean -n cgp --collect-data certifi \
       --specpath /tmp/_spec --distpath /tmp/_dist --workpath /tmp/_build \
       cursor_gui_patch/__main__.py && \
      tar -C /tmp/_dist -czf /out/cgp-linux-x86_64.tar.gz cgp"]
