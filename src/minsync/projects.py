"""Project-level helpers: detect how to install/build/test per profile.
Returns (argv, shell) pairs - execution always goes through TaskManager.

One-shot containers are ephemeral, so dependency installs must land in
the WORKSPACE to survive into build/test tasks:
- python: pip --target /workspace/.minsync_deps (+ PYTHONPATH set by backend)
- node:   node_modules/ in workspace (default npm behaviour)
- go:     module/build caches under /workspace/.cache (env set by backend)
- rust:   CARGO_HOME under /workspace/.cache (env set by backend)
- java:   Maven local repo .cache/m2 (explicit -Dmaven.repo.local)
- dotnet: NUGET_PACKAGES under /workspace/.cache (env set by backend)

Shell snippets must NOT mask failures (`cmd || echo ok` anti-pattern):
a failing build/test keeps its non-zero exit code.
"""

from __future__ import annotations

from pathlib import Path

from .errors import InvalidArgument
from .profiles import Profile

_MVN_LOCAL = "-Dmaven.repo.local=.cache/m2"


def _has(root: Path, name: str) -> bool:
    return (root / name).exists()


def install_command(profile: Profile, root: Path) -> tuple[list[str] | None, str | None]:
    n = profile.name
    if n == "python":
        target = "--target /workspace/.minsync_deps --upgrade"
        if _has(root, "requirements.txt"):
            return None, f"python3 -m pip install --no-cache-dir {target} -r requirements.txt"
        if _has(root, "pyproject.toml"):
            return None, f"python3 -m pip install --no-cache-dir {target} ."
        raise InvalidArgument("no requirements.txt or pyproject.toml found")
    if n == "node":
        if _has(root, "package.json"):
            return None, "if [ -f package-lock.json ]; then npm ci; else npm install; fi"
        raise InvalidArgument("no package.json found")
    if n == "go":
        if _has(root, "go.mod"):
            return ["go", "mod", "download"], None
        raise InvalidArgument("no go.mod found")
    if n == "rust":
        if _has(root, "Cargo.toml"):
            return ["cargo", "fetch"], None
        raise InvalidArgument("no Cargo.toml found")
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", _MVN_LOCAL, "-DskipTests", "dependency:go-offline"], None
        raise InvalidArgument("no pom.xml found (Gradle offline prefetch not supported)")
    if n == "dotnet":
        return None, (
            "ls *.sln *.csproj >/dev/null 2>&1 && dotnet restore "
            "|| echo 'no .sln/.csproj at workspace root; nothing to restore'"
        )
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
        if not _has(root, "package.json"):
            raise InvalidArgument("no package.json found")
        return None, (
            "if node -e \"const p=require('./package.json');"
            'process.exit(p.scripts&&p.scripts.build?0:1)"; '
            "then npm run build; else echo 'no build script; nothing to build'; fi"
        )
    if n == "go":
        return ["go", "build", "./..."], None
    if n == "rust":
        return ["cargo", "build"], None
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", _MVN_LOCAL, "-DskipTests", "package"], None
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
        if not _has(root, "package.json"):
            raise InvalidArgument("no package.json found")
        return None, "npm test"
    if n == "cpp":
        return None, (
            "if [ -f build/CTestTestfile.cmake ]; then "
            "ctest --test-dir build --output-on-failure; "
            "elif [ -x ./app ]; then ./app; "
            "else echo 'no tests found (no CTest, no ./app)'; exit 2; fi"
        )
    if n == "go":
        return ["go", "test", "./..."], None
    if n == "rust":
        return ["cargo", "test"], None
    if n == "java":
        if _has(root, "pom.xml"):
            return ["mvn", "-q", _MVN_LOCAL, "test"], None
        raise InvalidArgument("no pom.xml; run your program with run_command instead")
    if n == "dotnet":
        return ["dotnet", "test"], None
    return None, "echo 'no test framework configured for this profile'"
