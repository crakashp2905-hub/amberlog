#!/bin/sh
# Install the repository's git hooks into this clone (see tools/hooks/).
set -e
root=$(git rev-parse --show-toplevel)
hooks=$(git rev-parse --git-path hooks)
for hook in "$root"/tools/hooks/*; do
    cp "$hook" "$hooks/$(basename "$hook")"
    chmod +x "$hooks/$(basename "$hook")"
    echo "installed $(basename "$hook")"
done
