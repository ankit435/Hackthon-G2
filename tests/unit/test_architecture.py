"""Layer dependencies point inward only: api -> application -> domain <- infra (PLAN.md §5)."""
import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
LAYERS = {"domain", "application", "infra", "api"}
FORBIDDEN = {
    "domain": {"application", "infra", "api"},
    "application": {"infra", "api"},
    "infra": {"application", "api"},
    "api": set(),  # composition root: may import everything
}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def modules(layer: str) -> list[Path]:
    return sorted((SRC / layer).rglob("*.py"))


@pytest.mark.parametrize("layer", sorted(LAYERS))
def test_layer_imports_point_inward(layer):
    violations = {str(p.relative_to(SRC)): sorted(imported_roots(p) & FORBIDDEN[layer]) for p in modules(layer)}
    assert not {k: v for k, v in violations.items() if v}


def test_domain_is_stdlib_only():
    allowed = set(sys.stdlib_module_names) | {"domain", "__future__"}
    third_party = {str(p.relative_to(SRC)): sorted(imported_roots(p) - allowed) for p in modules("domain")}
    assert not {k: v for k, v in third_party.items() if v}


def test_sql_lives_only_in_infra():
    keywords = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "CREATE TABLE")
    offenders = [str(p.relative_to(SRC)) for layer in ("domain", "application")
                 for p in modules(layer) if any(k in p.read_text() for k in keywords)]
    assert not offenders
