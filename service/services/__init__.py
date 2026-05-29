"""Shared service wrappers for MLP Lambda handlers.

Keep package exports lazy so catalog/dashboard/register imports do not eagerly pull
search/index/bridge dependencies during Lambda cold start.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BridgeService": ("service.services.bridge_service", "BridgeService"),
    "ExecuteRequest": ("service.services.contracts", "ExecuteRequest"),
    "IndexRequest": ("service.services.contracts", "IndexRequest"),
    "SearchRequest": ("service.services.contracts", "SearchRequest"),
    "ExecuteService": ("service.services.execute_service", "ExecuteService"),
    "IndexService": ("service.services.index_service", "IndexService"),
    "SearchService": ("service.services.search_service", "SearchService"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    return getattr(module, attr_name)
