import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PROJECT_PACKAGES = {"agents", "api", "db", "models", "services", "shared"}
# Layer (top-level package or module of `src/`) -> project packages it may import.
ALLOWED_IMPORTS: dict[str, set[str]] = {
    "models": set(),
    "shared": {"shared", "models"},
    "db": {"db", "shared"},
    "services": {"services", "shared", "models"},
    "agents": {"agents", "services", "shared", "models"},
    "api": PROJECT_PACKAGES,
}


def _imported_project_packages(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in PROJECT_PACKAGES:
                found.append((node.lineno, top))
    return found


def test_each_layer_imports_only_the_layers_below_it() -> None:
    """The layers only stay layers if a test refuses the upward import: without it
    a shared module quietly imports an agent and the dependency rule is prose."""
    # Arrange
    violations: list[str] = []

    # Act
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        layer = relative.parts[0].removesuffix(".py")
        if layer not in ALLOWED_IMPORTS:
            continue
        tree = ast.parse(path.read_text())
        for line, package in _imported_project_packages(tree):
            if package not in ALLOWED_IMPORTS[layer]:
                violations.append(f"{relative}:{line} imports {package}")

    # Assert
    assert violations == []
