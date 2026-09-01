#!/usr/bin/env bash
# Build the V2 stylesheet with the standalone Tailwind binary (no node).
# Usage: scripts/build-css.sh [--watch]
set -euo pipefail

TAILWIND_VERSION="v4.3.3"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/tmp/bin"
WEB="$ROOT/src/theswarm/presentation/web"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  ASSET="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) ASSET="tailwindcss-macos-x64" ;;
  Linux-aarch64) ASSET="tailwindcss-linux-arm64" ;;
  Linux-x86_64)  ASSET="tailwindcss-linux-x64" ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

BIN="$BIN_DIR/tailwindcss-$TAILWIND_VERSION"
if [ ! -x "$BIN" ]; then
  mkdir -p "$BIN_DIR"
  echo "Fetching Tailwind $TAILWIND_VERSION ($ASSET)…" >&2
  curl -fsSL -o "$BIN" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/$TAILWIND_VERSION/$ASSET"
  chmod +x "$BIN"
fi

exec "$BIN" -i "$WEB/static/v2/input.css" -o "$WEB/static/v2/app.css" \
  --minify "${1:-}"
