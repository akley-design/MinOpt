"""Execution profiles. A profile maps to ONE internally-defined image.
MCP clients can never supply an image name, mount, or docker flag."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import UnknownProfile


@dataclass(frozen=True)
class Profile:
    name: str
    image: str
    dockerfile_dir: str  # under docker/ in the MinSync repo/install
    tools: tuple[str, ...]
    description: str
    dependency_files: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[str, Profile] = {
    "python": Profile(
        "python",
        "minsync/python:3.12",
        "python",
        ("python3", "pip", "pytest"),
        "Python 3.12 (slim) with pip and pytest",
        ("requirements.txt", "pyproject.toml"),
    ),
    "cpp": Profile(
        "cpp",
        "minsync/cpp:1",
        "cpp",
        ("gcc", "g++", "clang", "cmake", "ninja", "make"),
        "GCC/Clang, CMake, Ninja",
        ("CMakeLists.txt", "Makefile"),
    ),
    "node": Profile(
        "node",
        "minsync/node:22",
        "node",
        ("node", "npm", "npx", "tsc"),
        "Node.js 22 with TypeScript compiler",
        ("package.json",),
    ),
    "go": Profile(
        "go",
        "minsync/go:1",
        "go",
        ("go", "gofmt"),
        "Go toolchain",
        ("go.mod",),
    ),
    "rust": Profile(
        "rust",
        "minsync/rust:1",
        "rust",
        ("rustc", "cargo"),
        "Rust toolchain",
        ("Cargo.toml",),
    ),
    "java": Profile(
        "java",
        "minsync/java:21",
        "java",
        ("java", "javac", "mvn", "gradle"),
        "OpenJDK 21 with Maven and Gradle",
        ("pom.xml", "build.gradle"),
    ),
    "dotnet": Profile(
        "dotnet",
        "minsync/dotnet:8",
        "dotnet",
        ("dotnet",),
        ".NET 8 SDK (Linux containers; not Windows/.NET Framework)",
        ("*.csproj", "*.sln"),
    ),
    "bash": Profile(
        "bash",
        "minsync/bash:1",
        "bash",
        ("bash", "sh", "coreutils"),
        "Minimal Debian shell environment",
        (),
    ),
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise UnknownProfile(f"unknown profile: {name!r}", details={"known": sorted(PROFILES)}) from None


def list_profiles() -> list[dict]:
    return [
        {
            "name": p.name,
            "image": p.image,
            "tools": list(p.tools),
            "description": p.description,
            "dependency_files": list(p.dependency_files),
        }
        for p in PROFILES.values()
    ]
