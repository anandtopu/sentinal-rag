"""FastAPI app for standalone ingestion-service smoke checks."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel
from sentinelrag_shared.chunking import ChunkingStrategy

from sentinelrag_ingestion_service.connectors.registry import build_default_registry


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "sentinelrag-ingestion-service"


class CapabilitiesResponse(BaseModel):
    parsing_strategies: list[str]
    chunking_strategies: list[str]
    source_connectors: list[str]


app = FastAPI(
    title="SentinelRAG Ingestion Service",
    version="0.1.0",
    description="Standalone health and capability surface for ingestion.",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        parsing_strategies=["fast", "hi_res", "ocr_only", "auto"],
        chunking_strategies=[strategy.value for strategy in ChunkingStrategy],
        source_connectors=[
            connector.name for connector in build_default_registry().connectors
        ],
    )
