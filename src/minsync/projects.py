"""Project-level helpers: detect how to install/build/test per profile.
Returns (argv, shell) pairs - execution always goes through TaskManager."""
from __future__ import annotations

from pathlib import Path

from .errors import InvalidArgument
from .profiles import Profile


def _has(root: Path, name: str) -> bool:
    return (root / name).exists()


def install_command(profile: Profile, root: Path) -> tuple[list[str] | None, str | None]:
    n = profile.name
    if n == "python":
        if _has(root, "requirements.txt"):
            return None, "pip install --no-cache-dir -r requirements.txt"
        if _has(root, "pyproject.toml"):
            return None, "pip install --no-cache-dir ."
        raise InvalidArgument("no requirements.txt or pyproject.toml found")
    if n == "node":
        if _has(root, "package.json"):
            return None, "if [ -f package-lock.json ]; then npm ci; else npm install; fi"
        raise InvalidArgument("no package.json found")
    if n == "go":
        return ["go", "mod", "download"], None
    if n == "rust":
        return ["cargo", "fetch"], None
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", "-DskipTests", "dependency:go-offline"], None
        raise InvalidArgument("no pom.xml found (Gradle offline prefetch not supported)")
    return None, "echo 'no dependency installation needed for this profile'"


def build_command(profile: Profile, root: Path) -> tuple[list[str] | None, str | None]:
    n = profile.name
    if n == "cpp":
        if _has(root, "CMakeLists.txt"):
            return None, "cmake -S . -B build -G Ninja && cmake --build build"
        if _has(root, "Makefile"):
            return ["make"], None
        # single-file fallback: compile every .cpp/.c into ./app
        srcs = sorted([p.name for p in root.glob("*.cpp")] + [p.name for p in root.glob("*.c")])
        if srcs:
            compiler = "g++" if any(s.endswith(".cpp") for s in srcs) else "gcc"
            return [compiler, "-O2", "-o", "app", *srcs], None
        raise InvalidArgument("no CMakeLists.txt, Makefile or *.cpp/*.c found")
    if n == "node":
        return None, "node -e \"const p=require('./package.json');process.exit(p.scripts&&p.scripts.build?0:42)\" && npm run build || echo 'no build script; nothing to build'"
    if n == "go":
        return ["go", "build", "./..."], None
    if n == "rust":
        return ["cargo", "build"], None
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", "-DskipTests", "package"], None
        srcs = sorted(p.name for p in root.glob("*.java"))
        if srcs:
            return None, "mkdir -p out && javac -d out " + " ".join(srcs)
        raise InvalidArgument("no pom.xml or *.java found")
    if n == "dotnet":
        return ["dotnet", "build"], None
    if n == "python":
        return None, "python3 -m compileall -q ."
    return None, "echo 'nothing to build for this profile'"


def test_command(profile: Profile, root: Path) -> tuple[list[str] | None, str | None]:
    n = profile.name
    if n == "python":
        return None, "python3 -m pytest -q"
    if n == "node":
        return None, "npm test"
    if n == "cpp":
        return None, "ctest --test-dir build --output-on-failure || ./app"
    if n == "go":
        return ["go", "test", "./..."], None
    if n == "rust":
        return ["cargo", "test"], None
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", "test"], None
        raise InvalidArgument("no pom.xml; run your program with run_command instead")
    if n == "dotnet":
        return ["dotnet", "test"], None
    return None, "echo 'no test framework configured for this profile'"
