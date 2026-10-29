#!/bin/sh
# Snapshot every branch and tag into one verified git bundle, outside the repo.
#
#     sh tools/backup.sh [directory]     (default: ../Memory-backups)
#
# Restore with:  git clone <bundle> amberlog
set -e
root=$(git rev-parse --show-toplevel)
dest=${1:-"$root/../Memory-backups"}
mkdir -p "$dest"
git fetch --all --prune --quiet
stamp=$(date +%Y-%m-%dT%H%M)
bundle="$dest/amberlog-$stamp.bundle"
# Remote-tracking refs too, so branches never checked out here are included.
git bundle create "$bundle" HEAD --branches --tags --remotes --quiet
git bundle verify "$bundle" >/dev/null
echo "$bundle ($(git bundle list-heads "$bundle" | wc -l) refs, verified)"
