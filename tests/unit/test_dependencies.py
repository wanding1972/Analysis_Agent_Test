"""Static dependency audit of the entire current production tree."""

import ast
from graphlib import TopologicalSorter
from importlib.util import resolve_name
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src"


def test_dependency_boundaries_and_dag():
    graph = {}
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        package = module if parts[-1] == "__init__" else module.rpartition(".")[0]
        imports = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                imports.add(resolve_name(target, package) if node.level else target)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "__import__"}
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"import_module", "exec_module"}
        graph[module] = {item for item in imports if item.startswith("agent_test")}
        if ".domains." in module:
            domain = module.split(".")[2]
            for target in imports:
                assert ".infrastructure" not in target
                if ".domains." in target and target.split(".")[2] != domain:
                    assert target.endswith(".api")
                if domain == "evaluation" and ".domains." in target:
                    assert target.split(".")[2] in {"evaluation", "canonical", "rules", "assets"}
                if domain == "generation" and ".domains." in target:
                    assert target.split(".")[2] in {"generation", "canonical", "rules"}
        standard = {"enum", "typing", "logging", "collections", "decimal", "pathlib", "string", "hashlib", "json", "dataclasses", "urllib", "csv", "io", "html", "zipfile", "xml"}
        if ".common" in module:
            assert not any(target.startswith(("agent_test.domains", "agent_test.application",
                                               "agent_test.presentation",
                                               "agent_test.infrastructure"))
                           for target in imports)
        allowed = standard | {"agent_test", "pydantic"}
        if ".infrastructure." in module:
            allowed.update({"yaml", "openpyxl", "json", "xml", "zipfile", "sqlite3", "contextlib"})
            allowed.update({"allpairspy", "anthropic", "itertools"})
        assert all(target.split(".")[0] in allowed for target in imports)
    tuple(TopologicalSorter(graph).static_order())
    print(f"Dependency audit: {len(graph)} production modules, DAG and boundaries PASS")
    assert not list(ROOT.glob("*.py"))
    assert not list((ROOT / "agent_test").glob("*.py")) or all(
        path.name == "__init__.py" for path in (ROOT / "agent_test").glob("*.py")
    )
