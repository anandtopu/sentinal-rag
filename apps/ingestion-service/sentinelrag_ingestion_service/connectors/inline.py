"""Inline text connector for demos, tests, and small operator-provided snippets."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from sentinelrag_ingestion_service.connectors.base import FetchedDocument


class InlineTextConnector:
    """Fetch text encoded directly in a source URI.

    Supported forms:
    - ``text://hello%20world``
    - ``inline://hello%20world``
    """

    name = "inline"

    def supports(self, source_uri: str) -> bool:
        return urlparse(source_uri).scheme in {"text", "inline"}

    async def fetch(self, source_uri: str) -> FetchedDocument:
        parsed = urlparse(source_uri)
        text = unquote(f"{parsed.netloc}{parsed.path}")
        return FetchedDocument(
            content=text.encode("utf-8"),
            source_uri=source_uri,
            filename="inline.txt",
            mime_type="text/plain; charset=utf-8",
            metadata={"connector": self.name},
        )
