---
status: accepted
---

# Use Garage for local S3-compatible storage

Sandbox uses a persistent single-node Garage service for Listing Media because the MinIO container images are no longer reliably available from their configured registry. Product continues to use its existing S3 adapter; Garage initializes private buckets and a separate Product key with access limited to those buckets. Pilot and Public remain on AWS S3. A one-time migration copies existing MinIO objects with SHA-256 verification and retains the source volume; Garage's local permissions are not a substitute for AWS IAM policy testing.
