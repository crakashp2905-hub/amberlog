#!/bin/sh
# Start the dashboard with content keys kept outside the database.
#
# New stores put their keys in $MEMORY_FABRIC_KEYS (/keys, its own volume), so a
# copy of the database volume alone cannot read content. A store created before
# this image changed keeps its keys inside the database; pointing it at an empty
# key directory would make it unreadable, so it starts the old way, with a
# warning that says how to move the keys out.
set -eu

db="${MEMORY_FABRIC_DB:-/data/store.db}"
keys="${MEMORY_FABRIC_KEYS:-}"

if [ -n "$keys" ] && [ -f "$db" ] && [ -z "$(ls -A "$keys" 2>/dev/null)" ]; then
    echo "memory-fabric: $db keeps its content keys INSIDE the database." >&2
    echo "  Move them to the key volume (verified before anything is removed):" >&2
    echo "    docker exec -e MEMORY_FABRIC_KEYS= <container> memory-fabric --db $db migrate-keys $keys" >&2
    echo "  Starting with the in-database keys until then." >&2
    unset MEMORY_FABRIC_KEYS
elif [ -n "$keys" ]; then
    echo "memory-fabric: content keys in $keys. Mount it as its own volume and back it up separately." >&2
fi

exec memory-fabric --db "$db" --create serve --host 0.0.0.0 --port 8765 "$@"
