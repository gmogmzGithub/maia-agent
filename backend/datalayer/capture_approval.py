"""Commercial approval identity shared by contract copies, retries and delivery."""


def commercial_data(data):
    """Exclude temporary provider references from durable commercial snapshots."""
    return {key: value for key, value in data.items() if key != "location_ref" or not value}


def approval_matches(capture, snapshot):
    """A queued copy remains valid only for its unchanged, current approval.

    A refreshed provider reference is not a commercial correction. Do not compare
    the mutable capture revision: preparing a retry need not change the approval.
    """
    return bool(
        capture
        and capture.status == "approved"
        and capture.verified_at
        and commercial_data(capture.data) == snapshot.get("data")
        and capture.verified_at.isoformat() == snapshot.get("reviewed_at")
    )
