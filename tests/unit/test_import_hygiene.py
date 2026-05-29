"""Import hygiene guardrails — freeze PR #57 compliance as executable policy.

PR #57 renamed ``mlp/`` to ``service/`` and converted ``src/`` to a proper package.
Any future reintroduction of ``mlp.*`` imports is pre-refactor debt and must be
blocked at CI time. Function-body imports under ``service/mcp_server/`` caused a
production runtime bomb before PR #57; we block that pattern there specifically.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCAN_DIRS = ("src", "service", "tests", "scripts")
_EXCLUDE_DIR_PARTS = {
    "__pycache__",
    ".venv",
    "node_modules",
    "docs",
    ".pytest_cache",
    ".aws-sam",
    "dist",
    "build",
}
_EXCLUDE_FILES = {
    # Lambda artifact smoke test uses a string-literal sys.path.insert targeting
    # the built dist directory — unrelated to the mlp/ shim banned elsewhere.
    "service/build/smoke.py",
}


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_DIRS:
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(_REPO_ROOT)
            if any(part in _EXCLUDE_DIR_PARTS for part in rel.parts):
                continue
            if str(rel) in _EXCLUDE_FILES:
                continue
            files.append(path)
    return files


def test_no_mlp_imports_in_code_tree() -> None:
    """No ``from mlp.*`` or ``import mlp`` anywhere under src/ service/ tests/ scripts/."""
    offenders: list[str] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "mlp" or module.startswith("mlp."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} from {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "mlp" or alias.name.startswith("mlp."):
                        offenders.append(
                            f"{path.relative_to(_REPO_ROOT)}:{node.lineno} import {alias.name}"
                        )
    assert not offenders, "mlp.* imports forbidden post-PR #57:\n" + "\n".join(offenders)


def test_no_function_body_imports_in_mcp_server() -> None:
    """service/mcp_server/*.py must not contain Import/ImportFrom inside function bodies.

    TYPE_CHECKING-guarded imports under ``if TYPE_CHECKING:`` live at module level
    and are allowed. This guardrail blocks the specific pattern that caused the
    pre-PR-57 production runtime bomb at ``service/mcp_server/local_app.py:78``.
    """
    mcp_server_dir = _REPO_ROOT / "service" / "mcp_server"
    if not mcp_server_dir.exists():
        pytest.skip("service/mcp_server not present")
    offenders: list[str] = []
    for path in mcp_server_dir.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(func):
                if sub is func:
                    continue
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{sub.lineno} in {func.name}")
    assert not offenders, (
        "function-body imports forbidden under service/mcp_server/:\n" + "\n".join(offenders)
    )
