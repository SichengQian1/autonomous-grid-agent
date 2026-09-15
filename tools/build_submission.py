#!/usr/bin/env python3
"""Build and validate a deterministic competition submission archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


VERSION_PATTERN = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)$")
ARCHIVE_ROOT = PurePosixPath("CoreGeek")
ENTRYPOINT = b"""from solution.main import main


if __name__ == "__main__":
    main()
"""


def read_version(project_root: Path) -> str:
    return (project_root / "VERSION").read_text(encoding="utf-8").strip()


def validate_version(version: str) -> re.Match[str]:
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError("version must use the form v<major>.<minor>, for example v0.1")
    return match


def default_output(project_root: Path, version: str) -> Path:
    match = validate_version(version)
    major = f"v{match.group('major')}"
    return project_root / "submissions" / major / f"submission-{version}.tar.gz"


def _tar_info(name: PurePosixPath, *, size: int = 0, directory: bool = False) -> tarfile.TarInfo:
    archive_name = name.as_posix() + ("/" if directory else "")
    info = tarfile.TarInfo(archive_name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o755 if directory else 0o644
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _add_directory(archive: tarfile.TarFile, name: PurePosixPath) -> None:
    archive.addfile(_tar_info(name, directory=True))


def _add_bytes(archive: tarfile.TarFile, name: PurePosixPath, content: bytes) -> None:
    archive.addfile(_tar_info(name, size=len(content)), io.BytesIO(content))


def runtime_sources(project_root: Path) -> list[Path]:
    source_dir = project_root / "solution"
    sources = sorted(source_dir.glob("*.py"), key=lambda path: path.name)
    if not sources or not (source_dir / "__init__.py").is_file():
        raise FileNotFoundError("solution package is missing or incomplete")
    return sources


def build_archive(project_root: Path, output: Path, version: str) -> Path:
    validate_version(version)
    sources = runtime_sources(project_root)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                _add_directory(archive, ARCHIVE_ROOT)
                _add_bytes(archive, ARCHIVE_ROOT / "main3.py", ENTRYPOINT)
                _add_directory(archive, ARCHIVE_ROOT / "solution")
                for source in sources:
                    _add_bytes(
                        archive,
                        ARCHIVE_ROOT / "solution" / source.name,
                        source.read_bytes(),
                    )

    try:
        validate_archive(temporary_path, sources)
        temporary_path.replace(output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output


def validate_archive(archive_path: Path, sources: list[Path]) -> None:
    expected_files = {
        "CoreGeek/main3.py",
        *(f"CoreGeek/solution/{source.name}" for source in sources),
    }
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = {member.name.rstrip("/") for member in members}
        files = {member.name for member in members if member.isfile()}

        if files != expected_files:
            missing = sorted(expected_files - files)
            unexpected = sorted(files - expected_files)
            raise ValueError(f"archive file mismatch: missing={missing}, unexpected={unexpected}")
        if "CoreGeek" not in names or "CoreGeek/solution" not in names:
            raise ValueError("archive must contain the CoreGeek/solution directory tree")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("CoreGeek",):
                raise ValueError(f"unsafe archive path: {member.name}")
            if "__pycache__" in path.parts or path.name in {".DS_Store", ".git"}:
                raise ValueError(f"forbidden archive entry: {member.name}")

        entrypoint = archive.extractfile("CoreGeek/main3.py")
        if entrypoint is None or entrypoint.read() != ENTRYPOINT:
            raise ValueError("entrypoint wrapper is missing or incorrect")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="override VERSION (form: v0.1)")
    parser.add_argument("--output", type=Path, help="override archive output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    version = args.version or read_version(project_root)
    output = args.output or default_output(project_root, version)
    archive_path = build_archive(project_root, output.resolve(), version)
    print(f"archive={archive_path}")
    print(f"sha256={sha256_file(archive_path)}")


if __name__ == "__main__":
    main()
