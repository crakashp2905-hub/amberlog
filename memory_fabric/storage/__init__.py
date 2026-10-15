"""Storage backends for the event log.

The SQLite `EventLog` in `memory_fabric.eventlog` is the default and needs no
dependencies. `postgres.PostgresEventLog` is the multi-writer backend and needs
`psycopg`, which is an optional extra: importing this package does not import
it, so the core stays dependency-free.
"""
