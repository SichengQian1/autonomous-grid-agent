from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.build_submission import ENTRYPOINT, build_archive, default_output, runtime_sources


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SubmissionBuildTests(unittest.TestCase):
    def test_default_output_follows_version_line(self) -> None:
        self.assertEqual(
            default_output(PROJECT_ROOT, "v0.7"),
            PROJECT_ROOT / "submissions" / "v0" / "submission-v0.7.tar.gz",
        )

    def test_archive_contains_only_entrypoint_and_all_runtime_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "submission-v0.1.tar.gz"
            build_archive(PROJECT_ROOT, output, "v0.1")

            expected_files = {
                "CoreGeek/main3.py",
                *(f"CoreGeek/solution/{path.name}" for path in runtime_sources(PROJECT_ROOT)),
            }
            with tarfile.open(output, mode="r:gz") as archive:
                files = {member.name for member in archive.getmembers() if member.isfile()}
                self.assertEqual(files, expected_files)
                entrypoint = archive.extractfile("CoreGeek/main3.py")
                self.assertIsNotNone(entrypoint)
                assert entrypoint is not None
                self.assertEqual(entrypoint.read(), ENTRYPOINT)

    def test_invalid_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                build_archive(
                    PROJECT_ROOT,
                    Path(temporary_directory) / "bad.tar.gz",
                    "release-1",
                )


if __name__ == "__main__":
    unittest.main()
