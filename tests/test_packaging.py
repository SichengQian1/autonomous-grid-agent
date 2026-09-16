from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from tools.package_submission import ROOT, PROFILES, MODULES, build_archive, collect_files


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        for name in [*(f"solution/{m}.py" for m in MODULES),
                     *(f"config/{p}.json" for p in PROFILES)]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.output = Path(self.temp.name) / "submission.tar.gz"

    def test_archive_has_sdk_entry_and_only_runtime_files(self):
        # Synthetic forbidden extras must never enter the archive, even .py files.
        for name in ("all/sample.py", "local/request.json", "solution/private_notes.py",
                     "solution/__pycache__/main.pyc", ".git/config", "SDK-v1.0.pdf"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("synthetic extra")
        digest, count = build_archive(self.root, "frontline", self.output)
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        with tarfile.open(self.output) as archive:
            self.assertEqual(count, len(MODULES) + 3)
            expected = {"CoreGeek/main3.py", "CoreGeek/run.sh", "CoreGeek/config/strategy.json"}
            expected.update(f"CoreGeek/solution/{m}.py" for m in MODULES)
            self.assertEqual(set(archive.getnames()), expected)
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual((member.uid, member.gid, member.mtime, member.uname, member.gname),
                                 (0, 0, 0, "", ""))
            self.assertEqual(archive.getmember("CoreGeek/run.sh").mode, 0o755)
            config = json.load(archive.extractfile("CoreGeek/config/strategy.json"))
            self.assertEqual(config["defense_layout"], "frontline")
            self.assertTrue(config["wall_maintenance_enabled"])

    def test_same_content_produces_identical_archive(self):
        build_archive(self.root, "frontline", self.output)
        first = self.output.read_bytes()
        (self.root / "solution/main.py").touch()
        other = self.output.with_name("another-name.tar.gz")
        build_archive(self.root, "frontline", other)
        self.assertEqual(first, other.read_bytes())

    def test_embedded_log_key_enables_directory_and_stays_deterministic(self):
        build_archive(self.root, "frontline", self.output, log_key="synthetic-key")
        with tarfile.open(self.output) as archive:
            main3 = archive.extractfile("CoreGeek/main3.py").read().decode()
        self.assertIn('os.environ.setdefault("AGENT_TURN_LOG", str(ROOT / "logs"))', main3)
        self.assertIn(
            'os.environ.setdefault("AGENT_TURN_LOG_KEY", "synthetic-key")', main3
        )
        other = self.output.with_name("same-key.tar.gz")
        build_archive(self.root, "frontline", other, log_key="synthetic-key")
        self.assertEqual(self.output.read_bytes(), other.read_bytes())
        third = self.output.with_name("other-key.tar.gz")
        build_archive(self.root, "frontline", third, log_key='we"ird\\key')
        self.assertNotEqual(self.output.read_bytes(), third.read_bytes())
        with tarfile.open(third) as archive:
            escaped = archive.extractfile("CoreGeek/main3.py").read().decode()
        self.assertIn('AGENT_TURN_LOG_KEY", "we\\"ird\\\\key"', escaped)

    def test_default_package_does_not_enable_turn_log(self):
        build_archive(self.root, "frontline", self.output)
        with tarfile.open(self.output) as archive:
            main3 = archive.extractfile("CoreGeek/main3.py").read().decode()
        self.assertNotIn("AGENT_TURN_LOG", main3)
        self.assertNotIn("AGENT_TURN_LOG_KEY", main3)

    def test_turn_log_flag_enables_plaintext_directory(self):
        build_archive(self.root, "frontline", self.output, turn_log=True)
        with tarfile.open(self.output) as archive:
            main3 = archive.extractfile("CoreGeek/main3.py").read().decode()
        self.assertIn('os.environ.setdefault("AGENT_TURN_LOG", str(ROOT / "logs"))', main3)
        self.assertNotIn("AGENT_TURN_LOG_KEY", main3)

    def test_all_profiles_are_valid_in_isolated_runtime(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                build_archive(self.root, profile, self.output)
                with tarfile.open(self.output) as archive:
                    self.assertEqual(archive.extractfile("CoreGeek/config/strategy.json").read(),
                                     (self.root / f"config/{profile}.json").read_bytes())

    def test_missing_import_fails_without_replacing_previous_archive(self):
        self.output.write_bytes(b"previous package")
        main = self.root / "solution/main.py"
        main.write_text("from .missing_runtime_module import start\n")
        with self.assertRaisesRegex(ValueError, "isolated runtime"):
            build_archive(self.root, "frontline", self.output)
        self.assertEqual(self.output.read_bytes(), b"previous package")

    def test_invalid_config_and_syntax_do_not_create_archive(self):
        config = self.root / "config/frontline.json"
        config.write_text('{"wall_budget_fraction": 2}')
        with self.assertRaisesRegex(ValueError, "isolated runtime"):
            build_archive(self.root, "frontline", self.output)
        self.assertFalse(self.output.exists())
        config.write_text('{}')
        (self.root / "solution/main.py").write_text("def invalid(:\n")
        with self.assertRaises(SyntaxError):
            build_archive(self.root, "frontline", self.output)
        self.assertFalse(self.output.exists())

    def test_missing_or_symlinked_inputs_are_rejected(self):
        path = self.root / "solution/main.py"
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            collect_files(self.root, "frontline")
        path.symlink_to(ROOT / "solution/main.py")
        with self.assertRaisesRegex(ValueError, "symlink"):
            collect_files(self.root, "frontline")

    def test_symlinked_source_directory_is_rejected(self):
        (self.root / "solution").rename(self.root / "source-copy")
        (self.root / "solution").symlink_to(self.root / "source-copy", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            collect_files(self.root, "frontline")
