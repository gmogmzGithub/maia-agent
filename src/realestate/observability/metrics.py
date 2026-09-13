"""Small in-process metrics registry with deliberately bounded labels."""

from __future__ import annotations

from collections import Counter

from realestate.observability.events import TelemetryEvent


class OperationalMetrics:
    """Aggregates traces without retaining interaction or customer identifiers."""

    def __init__(self) -> None:
        self._events: Counter[tuple[str, str, str, str]] = Counter()
        self._durations: Counter[tuple[str, str, str, float]] = Counter()

    def record(self, event: TelemetryEvent) -> None:
        channel = event.context.channel or "unknown"
        self._events[(event.stage, channel, event.outcome.value, event.error_code or "none")] += 1
        if event.duration_ms is not None:
            seconds = event.duration_ms / 1000
            for bound in (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")):
                if seconds <= bound:
                    self._durations[(event.stage, channel, event.outcome.value, bound)] += 1

    def render_prometheus(self) -> str:
        """Render a scrape-compatible view without high-cardinality labels."""
        lines = [
            "# HELP maia_operational_events_total Redacted operational lifecycle events.",
            "# TYPE maia_operational_events_total counter",
        ]
        for (stage, channel, outcome, error_code), value in sorted(self._events.items()):
            labels = _labels(
                stage=stage,
                channel=channel,
                outcome=outcome,
                error_code=error_code,
            )
            lines.append(f"maia_operational_events_total{labels} {value}")
        lines.extend(
            (
                "# HELP maia_operational_duration_seconds_bucket Redacted stage duration buckets.",
                "# TYPE maia_operational_duration_seconds_bucket counter",
            )
        )
        for (stage, channel, outcome, bound), value in sorted(
            self._durations.items(), key=lambda item: item[0]
        ):
            labels = _labels(
                stage=stage,
                channel=channel,
                outcome=outcome,
                le="+Inf" if bound == float("inf") else str(bound),
            )
            lines.append(f"maia_operational_duration_seconds_bucket{labels} {value}")
        return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    escaped = ",".join(
        f'{name}="{_escape(value)}"'
        for name, value in values.items()
    )
    return "{" + escaped + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
