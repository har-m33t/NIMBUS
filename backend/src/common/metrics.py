"""EMF metrics. Namespace NIMBUS/Pipeline."""

from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

metrics = Metrics(namespace="NIMBUS", service="Pipeline")

__all__ = ["metrics", "MetricUnit"]
