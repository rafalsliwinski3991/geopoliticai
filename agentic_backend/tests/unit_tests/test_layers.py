import ast
from pathlib import Path

import pytest

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


def _find_project_imports(tree: ast.AST) -> list[tuple[int, str]]:
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


def find_violations(src: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(src.rglob("*.py")):
        relative = path.relative_to(src)
        layer = relative.parts[0].removesuffix(".py")
        if layer not in ALLOWED_IMPORTS:
            violations.append(f"{relative} is in a layer missing from ALLOWED_IMPORTS")
            continue
        for line, package in _find_project_imports(ast.parse(path.read_text())):
            if package not in ALLOWED_IMPORTS[layer]:
                violations.append(f"{relative}:{line} imports {package}")
    return violations


def test_each_layer_imports_only_the_layers_below_it() -> None:
    """The layers only stay layers if a test refuses the upward import: without it
    a shared module quietly imports an agent and the dependency rule is prose."""
    # Arrange
    source_files = sorted(SRC.rglob("*.py"))

    # Act
    violations = find_violations(SRC)

    # Assert
    assert source_files, f"no source files under {SRC}"
    assert violations == []


def test_an_upward_import_is_reported_with_its_file_and_line(tmp_path: Path) -> None:
    """The layer test only means something if it goes red on the import it forbids."""
    # Arrange
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "leak.py").write_text("x = 1\nfrom agents import graph\n")

    # Act
    violations = find_violations(tmp_path)

    # Assert
    assert violations == ["shared/leak.py:2 imports agents"]


def test_a_top_level_package_outside_the_layer_table_is_reported(
    tmp_path: Path,
) -> None:
    """A new top-level package must get a row in the table, or it would escape the
    rule unseen."""
    # Arrange
    (tmp_path / "newlayer").mkdir()
    (tmp_path / "newlayer" / "mod.py").write_text("x = 1\n")

    # Act
    violations = find_violations(tmp_path)

    # Assert
    assert violations == ["newlayer/mod.py is in a layer missing from ALLOWED_IMPORTS"]


@pytest.mark.parametrize(
    "import_line",
    [
        "from agents import graph",
        "import agents.graph",
        "from agents.graph import build",
    ],
    ids=["from import", "import module", "from submodule import"],
)
def test_each_form_of_an_upward_import_is_reported(
    tmp_path: Path, import_line: str
) -> None:
    """`from x import y`, `import x.y` and `from x.y import z` all reach a layer."""
    # Arrange
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "leak.py").write_text(import_line + "\n")

    # Act
    violations = find_violations(tmp_path)

    # Assert
    assert violations == ["shared/leak.py:1 imports agents"]


def test_a_relative_import_is_not_reported(tmp_path: Path) -> None:
    """A relative import stays inside its own package, so it cannot go up a layer."""
    # Arrange
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "ok.py").write_text("from . import sibling\n")

    # Act
    violations = find_violations(tmp_path)

    # Assert
    assert violations == []
