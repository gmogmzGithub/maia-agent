# Workers

This package owns background orchestration.

Workers may claim due work, pace expensive passes, call domain interfaces, and
hand results to channel adapters. They should not define Product policy. If a
worker needs to decide whether an action is allowed, move that decision into
`realestate.domain` and call it from the worker.
