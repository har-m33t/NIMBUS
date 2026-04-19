"""EMF metrics. Namespace NIMBUS/Pipeline."""

from __future__ import annotations

from collections.abc import Callable

try:
    from aws_lambda_powertools import Metrics as _PowertoolsMetrics
    from aws_lambda_powertools.metrics import MetricUnit
except ImportError:
    _PowertoolsMetrics = None

    class MetricUnit:
        Count = "Count"
        Milliseconds = "Milliseconds"


class _FallbackMetrics:
    def __init__(self) -> None:
        self.values: list[tuple[str, str, float]] = []

    def add_metric(self, name: str, unit: str, value: float) -> None:
        self.values.append((name, unit, value))

    def log_metrics(self, func: Callable):
        return func


metrics = (
    _PowertoolsMetrics(namespace="NIMBUS", service="Pipeline")
    if _PowertoolsMetrics is not None
    else _FallbackMetrics()
)

__all__ = ["metrics", "MetricUnit"]
