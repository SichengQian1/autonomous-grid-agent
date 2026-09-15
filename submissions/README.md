# Submission Artifacts

This directory stores the exact archives prepared for manual competition upload.

Version policy:

- `codex/v0` contains the `v0.x` iteration line.
- Minor compatible updates increment the suffix: `v0.1`, `v0.2`, and so on.
- A major architecture or strategy generation starts a new branch such as
  `codex/v1` and resets the package suffix to `v1.0`.
- `VERSION` is the source of truth for the next generated artifact name.

Build the current package from the repository root:

```powershell
python tools/build_submission.py
```

The output path is `submissions/<major>/submission-<version>.tar.gz`. Archives
contain only the platform runtime tree under top-level `CoreGeek/`. Do not edit an
archive manually; update `solution/`, advance `VERSION`, and rebuild it.
