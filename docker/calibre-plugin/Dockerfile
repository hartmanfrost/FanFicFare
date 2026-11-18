# Delivery image for the FanFicFare FB2 calibre plugin: /FanFicFare.zip plus a
# copy entrypoint. It is never run as a service: the calibre pod runs it as an
# initContainer that copies the zip into a shared volume (default /plugins/)
# and exits; calibre's init step then installs it with calibre-customize -a.
#
# Built from the repository root by the ash cluster CI (app-ci, .ash-ci.yaml):
#   docker build -f docker/calibre-plugin/Dockerfile -t fanficfare-calibre-plugin .
# Dockerfile.dockerignore next to this file keeps local junk out of the context.

# ---- build: unit tests, translations, plugin zip ----------------------------
# The zip is the same for every platform, so this stage runs on the builder's.
FROM --platform=$BUILDPLATFORM python:3.14.10-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# The only step that needs the network: exact pins, no dependency resolution.
# The registry build cache keeps this layer until the list changes.
COPY docker/calibre-plugin/requirements-build.txt /tmp/requirements-build.txt
RUN pip install --no-deps --only-binary=:all: -r /tmp/requirements-build.txt

WORKDIR /src
COPY makeplugin.py makezip.py ./
COPY included_dependencies/ included_dependencies/
COPY fanficfare/ fanficfare/
COPY calibre-plugin/ calibre-plugin/
COPY tests/ tests/
COPY docker/calibre-plugin/build_plugin.py docker/calibre-plugin/build_plugin.py

# A red test means no image, so a broken upstream sync never reaches calibre.
RUN python -m pytest -q -p no:cacheprovider tests

# Compiles the translations, runs makeplugin.py and checks the zip;
# writes /out/FanFicFare.zip, FanFicFare.zip.sha256 and FanFicFare.version.
RUN python docker/calibre-plugin/build_plugin.py --out /out

# ---- delivery image ----------------------------------------------------------
FROM busybox:1.37.0@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec

LABEL org.opencontainers.image.source=https://github.com/hartmanfrost/FanFicFare
LABEL org.opencontainers.image.title="FanFicFare FB2 calibre plugin"
LABEL org.opencontainers.image.description="FanFicFare calibre plugin with FB2 output and FB2 update (/FanFicFare.zip), copied into /plugins/ by the entrypoint"

COPY --from=build --chmod=0644 /out/FanFicFare.zip /out/FanFicFare.zip.sha256 /out/FanFicFare.version /
COPY --chmod=0755 docker/calibre-plugin/copy-plugin.sh /copy-plugin.sh

# No arguments: copy to /plugins/FanFicFare.zip. Kubernetes `args` replace
# the CMD, so args: ["/plugins/"] (or any directories) work the same way.
ENTRYPOINT ["/copy-plugin.sh"]
CMD ["/plugins/"]
