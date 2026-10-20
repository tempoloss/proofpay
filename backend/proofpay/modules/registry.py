"""Module registry: the single place where all modules are listed.

Routers, DI providers and model modules are all collected from this one
list, so a new module cannot be wired into one place and forgotten in
another. The list is ordered bottom-up along the dependency graph.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from dishka import Provider
    from litestar import Router

# Module package name -> database schema the module owns.
# The schema is used by Alembic: it only manages schemas listed here.
MODULES: Final[dict[str, str]] = {"bounties": "bounty"}

MODULE_NAMES: Final[tuple[str, ...]] = tuple(MODULES)


def _load(module: str, attr: str) -> object:
    return getattr(import_module(f"proofpay.modules.{module}.{attr}"), attr)


def all_routers() -> list[Router]:
    """Routers of all modules in dependency-graph order."""
    return [_load(name, "router") for name in MODULE_NAMES]  # type: ignore[misc]


def all_providers() -> list[Provider]:
    """DI providers of all modules."""
    return [_load(name, "provider") for name in MODULE_NAMES]  # type: ignore[misc]


def all_model_modules() -> list[str]:
    """Import paths of model modules - for Alembic."""
    return [f"proofpay.modules.{name}.infrastructure.models" for name in MODULE_NAMES]
