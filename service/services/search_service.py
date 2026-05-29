"""Thin search service — delegates to RAGService for the full pipeline."""

from service.rag.service import RAGSearchResult
from service.services.contracts import SearchRequest


class SearchService:
    def __init__(self, rag_service) -> None:
        self._rag_service = rag_service

    async def search(self, request: SearchRequest) -> RAGSearchResult:
        if request.client_id is None:
            return await self._rag_service.search(request.query, request.top_k)
        return await self._rag_service.search(
            request.query, request.top_k, client_id=request.client_id
        )
