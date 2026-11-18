#!/bin/sh
# Entrypoint of ghcr.io/hartmanfrost/fanficfare-calibre-plugin
# (docker/calibre-plugin/Dockerfile).
#
#   (no arguments)  copy the plugin to /plugins/FanFicFare.zip (the image's CMD)
#   DIR...          copy it to DIR/FanFicFare.zip for each DIR, creating DIR
#   -               write the zip to stdout:
#                     docker run --rm IMAGE - > FanFicFare-FB2.zip
#   --version       print the plugin name, version and the zip's sha256
#
# A copy is written under a temporary name and then renamed, so nothing
# reading DIR sees a half-written zip. Messages go to stderr.
set -eu

ZIP=/FanFicFare.zip
info() { echo "$(cat /FanFicFare.version) sha256 $(cut -d' ' -f1 /FanFicFare.zip.sha256)"; }
log() { echo "fanficfare-calibre-plugin: $*" >&2; }

[ "$#" -gt 0 ] || set -- /plugins/

case "$1" in
  --version)
    info
    exit 0 ;;
  -)
    [ "$#" -eq 1 ] || { log "'-' takes no other arguments"; exit 2; }
    cat "$ZIP"
    log "$(info) written to stdout"
    exit 0 ;;
esac

for dest in "$@"; do
  dir=${dest%/}
  dir=${dir:-/}
  mkdir -p "$dir"
  cp "$ZIP" "$dir/.FanFicFare.zip.tmp"
  chmod 0644 "$dir/.FanFicFare.zip.tmp"
  mv -f "$dir/.FanFicFare.zip.tmp" "$dir/FanFicFare.zip"
  log "$(info) -> $dir/FanFicFare.zip"
done
