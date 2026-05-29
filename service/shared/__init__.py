"""Shared helper namespace for MLP Lambda handlers.

Keep package exports lazy so handlers importing a narrow helper such as
``mlp.shared.http`` do not eagerly pull settings or other heavier runtime
dependencies during cold start.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "MLPSettings": ("service.shared.settings", "MLPSettings"),
    "build_log_payload": ("service.shared.logging", "build_log_payload"),
    "error_response": ("service.shared.http", "error_response"),
    "json_response": ("service.shared.http", "json_response"),
    "log_info": ("service.shared.logging", "log_info"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    return getattr(module, attr_name)
