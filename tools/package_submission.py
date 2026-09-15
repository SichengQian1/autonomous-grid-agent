#!/usr/bin/env python3
"""Build a deterministic, source-only submission with the SDK entry point."""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("baseline", "balanced", "frontline", "frontline-balanced")
# Deliberate allowlist: adding a runtime module requires updating this list.
MODULES = (
    "__init__", "actions", "ballistics", "combat", "configuration", "defense",
    "economy", "engine", "geometry", "layout", "main", "maintenance", "models",
    "navigation", "planning", "protocol", "resources", "rules", "state",
    "strategy", "tasks", "validation",
)
ENTRY_POINT = b'''from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
# The upload always uses the configuration selected when building the archive.
os.environ["AGENT_CONFIG"] = str(ROOT / "config" / "strategy.json")

from solution.main import main

if __name__ == "__main__":
    main()
'''
LAUNCHER = b'''#!/usr/bin/env bash
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/main3.py" "$@"
'''


def read_source(root: Path, relative: str) -> bytes:
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"symlink is not a submission source: {relative}")
    if not path.is_file():
        raise ValueError(f"missing submission source: {relative}")
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError(f"submission source is unexpectedly large: {relative}")
    return data


def collect_files(root: Path, profile: str) -> dict[str, bytes]:
    if profile not in PROFILES:
        raise ValueError("unknown strategy profile")
    files = {
        "CoreGeek/main3.py": ENTRY_POINT,
        "CoreGeek/run.sh": LAUNCHER,
    }
    for module in MODULES:
        relative = f"solution/{module}.py"
        files[f"CoreGeek/{relative}"] = read_source(root, relative)
    config = read_source(root, f"config/{profile}.json")
    if len(config) > 16384 or not isinstance(json.loads(config), dict):
        raise ValueError("configuration must be a JSON object of at most 16 KiB")
    files["CoreGeek/config/strategy.json"] = config
    for name, data in files.items():
        if name.endswith(".py"):
            ast.parse(data, filename=name, feature_version=(3, 11))
            compile(data, name, "exec")
    return files


def verify_runtime(files: dict[str, bytes]) -> None:
    """Check only the collected files, with no repository/PYTHONPATH fallback."""
    with tempfile.TemporaryDirectory(prefix="submission-check-") as directory:
        root = Path(directory)
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        probe = '''import runpy, sys
runpy.run_path(sys.argv[1], run_name="submission_check")
from solution.configuration import load_config
from solution.engine import AgentEngine
assert AgentEngine(load_config()).decide({}) == {"roleCommandMap": {}}
'''
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", probe, str(root / "CoreGeek/main3.py")],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            # Avoid copying local paths or arbitrary runtime output into reports.
            raise ValueError("isolated runtime check failed; check imports and strategy configuration")


def verify_archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if [m.name for m in members] != sorted(files):
            raise ValueError("archive file list does not match the allowlist")
        for member in members:
            mode = 0o755 if member.name.endswith("/run.sh") else 0o644
            if (not member.isfile() or member.mode != mode or member.uid != 0
                    or member.gid != 0 or member.uname or member.gname or member.mtime != 0):
                raise ValueError("unexpected archive metadata")
            stream = archive.extractfile(member)
            if stream is None or stream.read() != files[member.name]:
                raise ValueError("archive content verification failed")


def build_archive(root: Path, profile: str, output: Path) -> tuple[str, int]:
    if sys.version_info[:2] != (3, 11):
        raise ValueError("build with Python 3.11 to match the target minor version")
    if not output.name.endswith(".tar.gz"):
        raise ValueError("output filename must end in .tar.gz")
    files = collect_files(root, profile)
    verify_runtime(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after verification; a failed build leaves the previous package intact.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".submission-", delete=False) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    for name, data in sorted(files.items()):
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        info.mode = 0o755 if name.endswith("/run.sh") else 0o644
                        archive.addfile(info, io.BytesIO(data))
        verify_archive(temporary, files)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, output)
        return digest, len(files)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=PROFILES, default="frontline", help="strategy profile (default: frontline)")
    parser.add_argument("--output", type=Path, help="archive path; an existing archive is replaced after checks pass")
    args = parser.parse_args()
    output = args.output or ROOT / "artifacts" / f"submission-{args.config}.tar.gz"
    try:
        digest, count = build_archive(ROOT, args.config, output)
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1
    print(f"Package: {output.resolve()}")
    print(f"Strategy: {args.config}; files: {count}; bytes: {output.stat().st_size}")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
