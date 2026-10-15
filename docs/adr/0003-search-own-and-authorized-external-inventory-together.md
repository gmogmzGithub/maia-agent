---
status: accepted
---

# Search own and authorized external inventory together

Property discovery searches the brokerage's own stock and authorized EasyBroker
stock together, ranking customer fit first and preferring own listings when
suitability is comparable, while removing confirmed duplicates. Source preference
must not cause a materially worse own listing to outrank a better external match.
This replaces the earlier external-fallback-only policy to provide customers
with matching authorized options in one search. For duplicated properties, the
brokerage's published information remains authoritative; external descriptions
must not silently fill missing local facts. This decision does not select a
retrieval engine or prescribe live connector calls on every customer turn.
