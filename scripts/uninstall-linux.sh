#!/usr/bin/env bash
set -Eeuo pipefail
INSTALL_DIR=""
YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR=$2; shift 2 ;;
    --yes) YES=1; shift ;;
    -h|--help) printf 'Usage: %s --install-dir DIR --yes\n' "$0"; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ -n "$INSTALL_DIR" ]] || { printf '%s\n' '--install-dir is required' >&2; exit 2; }
TARGET=$(realpath -m -- "$INSTALL_DIR")
[[ "$TARGET" != "/" && "$TARGET" != "$HOME" && "$TARGET" != "$(pwd)" ]] || { printf 'Refusing unsafe uninstall target: %s\n' "$TARGET" >&2; exit 1; }
[[ -d "$TARGET" ]] || { printf 'Nothing to remove: %s\n' "$TARGET"; exit 0; }
if [[ "$YES" -ne 1 ]]; then
  printf 'Remove only %s? Type REMOVE to continue: ' "$TARGET"
  read -r answer
  [[ "$answer" == REMOVE ]] || { printf 'Cancelled.\n'; exit 1; }
fi
rm -rf -- "$TARGET"
printf 'Removed %s. User project folders outside this directory were not touched.\n' "$TARGET"
