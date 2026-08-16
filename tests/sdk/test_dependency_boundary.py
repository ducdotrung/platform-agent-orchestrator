from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / "src" / "platform_agent_orchestrator" / "core",
    ROOT / "src" / "platform_agent_orchestrator" / "sdk",
    ROOT / "src" / "platform_agent_orchestrator" / "policy",
)
FORBIDDEN = {"langchain", "langgraph"}
FORBIDDEN_PUBLIC_TYPES = {
    "Command",
    "CompiledGraph",
    "END",
    "StateGraph",
}
FORBIDDEN_IMPLEMENTATION_PREFIXES = {"platform_agent_orchestrator.registry"}


def imported_root(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.partition(".")[0] for alias in node.names}
    if node.module is None:
        return set()
    return {node.module.partition(".")[0]}


def imported_modules(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    return {node.module} if node.module is not None else set()


def test_contract_and_policy_layers_do_not_import_langchain_or_langgraph() -> None:
    violations: list[str] = []

    for target in TARGETS:
        for path in target.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    forbidden_imports = imported_root(node) & FORBIDDEN
                    for module in sorted(forbidden_imports):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")

    assert violations == [], "forbidden public-contract imports:\n" + "\n".join(violations)


def test_contract_and_policy_layers_do_not_expose_runtime_specific_types() -> None:
    violations: list[str] = []

    for target in TARGETS:
        for path in target.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                annotations: list[ast.expr] = []
                if isinstance(node, ast.arg) and node.annotation is not None:
                    annotations.append(node.annotation)
                elif isinstance(node, ast.AnnAssign):
                    annotations.append(node.annotation)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns is not None:
                        annotations.append(node.returns)

                for annotation in annotations:
                    exposed = {
                        part for part in FORBIDDEN_PUBLIC_TYPES if part in ast.unparse(annotation)
                    }
                    for public_type in sorted(exposed):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: {public_type}"
                        )

    assert violations == [], "runtime-specific public types:\n" + "\n".join(violations)


def test_contract_and_policy_layers_do_not_import_registry_implementations() -> None:
    violations: list[str] = []

    for target in TARGETS:
        for path in target.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for module in imported_modules(node):
                    if any(
                        module == prefix or module.startswith(f"{prefix}.")
                        for prefix in FORBIDDEN_IMPLEMENTATION_PREFIXES
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")

    assert violations == [], "implementation imports in core/sdk:\n" + "\n".join(violations)
