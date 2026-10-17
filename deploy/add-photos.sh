#!/usr/bin/env bash
# Put photos a maker sent you on their page (from your own machine, in the repository root):
#   deploy/add-photos.sh lobi-lampu ~/Downloads/willemieke/*.jpg
#   deploy/add-photos.sh lobi-lampu --no-profile extra1.jpg extra2.jpg   # album only
# The photos go into an album at the end of the page. Unless --no-profile, the first file
# (alphabetically) becomes the profile photo and the second the page photo at the top.
# Uses deploy/deploy.conf, like deploy.sh. JPEG, PNG or WebP.
set -euo pipefail
cd "$(dirname "$0")/.."
SLUG=${1:?usage: deploy/add-photos.sh SLUG [--no-profile] PHOTO...}
shift
EXTRA=()
if [ "${1:-}" = "--no-profile" ]; then EXTRA=(--no-profile); shift; fi
[ $# -gt 0 ] || { echo "No photos given." >&2; exit 1; }
. deploy/deploy.conf
SSH=${SSH:-ssh -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-createur-%C -o ControlPersist=2m}

# Copy under safe names that keep the alphabetical order, so the server needs no quoting.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
for f in "$@"; do [ -f "$f" ] || { echo "Not a file: $f" >&2; exit 1; }; done
i=0
while IFS=$'\t' read -r -d '' _ f; do  # sorted on the file name, ignoring case and folder
  i=$((i + 1))
  ext=$(printf '%s' "${f##*.}" | tr 'A-Z' 'a-z')
  cp "$f" "$STAGE/$(printf '%02d' "$i").$ext"
  echo "  $(printf '%02d' "$i"): $(basename "$f")"
done < <(for f in "$@"; do printf '%s\t%s\0' "$(basename "$f" | tr 'A-Z' 'a-z')" "$f"; done | sort -z)

DIR=".incoming-photos-$$"
echo "==> Uploading $i photos (STRATO may ask for your SSH password)"
tar -C "$STAGE" -cf - . | $SSH "$STRATO_SSH" "mkdir -p ~/private/$DIR && tar -xf - -C ~/private/$DIR"
echo "==> Adding them to /$SLUG"
$SSH "$STRATO_SSH" "~/app/flask add-photos '$SLUG' ${EXTRA[*]:-} ~/private/$DIR/*; s=\$?; rm -rf ~/private/$DIR; exit \$s" </dev/null
