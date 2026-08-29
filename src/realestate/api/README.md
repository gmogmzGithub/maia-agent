# API Routers

This package is Maia's controller layer.

Routers authenticate the caller, parse HTTP/form input, call Product-domain
interfaces, and render the response. They should not own business rules,
database invariants, retry policy, provider policy, or cross-Organization
authorization.

Use `operator.py` for operator authentication helpers and `ui.py` for shared
server-rendered HTML primitives.
