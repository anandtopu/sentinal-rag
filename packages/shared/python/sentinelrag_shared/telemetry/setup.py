"""OpenTelemetry SDK setup.

Wires up:
    - Trace provider with OTLP exporter (gRPC by default).
    - Metric provider with periodic OTLP exporter.
    - Resource attributes (service.name, deployment.environment, version).

FastAPI / SQLAlchemy / asyncpg / httpx instrumentation is opt-in and called
from each service's startup separately, since the instrumented objects must
exist before instrumentation runs.
"""

from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_telemetry(
    *,
    service_name: str,
    service_version: str = "0.1.0",
    environment: str = "local",
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OTel trace + metric providers.

    Args:
        service_name: ``service.name`` resource attribute.
        service_version: ``service.version`` resource attribute.
        environment: ``deployment.environment`` resource attribute.
        otlp_endpoint: OTLP collector endpoint. If ``None``, exporters fall back
            to the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var.
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": environment,
        }
    )

    # --- Tracing ---
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = (
        OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        if otlp_endpoint
        else OTLPSpanExporter(insecure=True)
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_exporter = (
        OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        if otlp_endpoint
        else OTLPMetricExporter(insecure=True)
    )
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
