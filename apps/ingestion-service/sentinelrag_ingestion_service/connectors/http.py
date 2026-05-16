"""HTTP(S) source connector."""

from __future__ import annotations

import asyncio
import mimetypes
from email.message import Message
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from sentinelrag_ingestion_service.connectors.base import ConnectorError, FetchedDocument


class HttpConnector:
    """Fetch documents from HTTP(S) URLs using the standard library."""

    name = "http"

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = "SentinelRAG/0.1",
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    def supports(self, source_uri: str) -> bool:
        return urlparse(source_uri).scheme in {"http", "https"}

    async def fetch(self, source_uri: str) -> FetchedDocument:
        return await asyncio.to_thread(self._fetch_sync, source_uri)

    def _fetch_sync(self, source_uri: str) -> FetchedDocument:
        request = Request(source_uri, headers={"User-Agent": self._user_agent})  # noqa: S310
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                content = response.read()
                headers = Message()
                for key, value in response.headers.items():
                    headers[key] = value
        except HTTPError as exc:
            raise ConnectorError(f"HTTP fetch failed with status {exc.code}: {source_uri}") from exc
        except URLError as exc:
            raise ConnectorError(f"HTTP fetch failed: {source_uri}") from exc

        path_name = PurePosixPath(unquote(urlparse(source_uri).path)).name
        filename = path_name or "download"
        content_type = headers.get_content_type()
        if content_type == "text/plain" and filename != "download":
            content_type = mimetypes.guess_type(filename)[0] or content_type

        return FetchedDocument(
            content=content,
            source_uri=source_uri,
            filename=filename,
            mime_type=content_type,
            metadata={
                "connector": self.name,
                "content_length": str(len(content)),
            },
        )
