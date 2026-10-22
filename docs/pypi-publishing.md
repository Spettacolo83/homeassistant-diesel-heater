# Publishing `diesel-heater-ble`

This guide is the release procedure for the bundled `diesel-heater-ble` library.

## Release Sequence

1. Make the library change in `diesel_heater_ble/src/diesel_heater_ble/` and update its version in `diesel_heater_ble/pyproject.toml`.
2. Update `custom_components/diesel_heater/manifest.json` to require that same version.
3. Build and validate the wheel from the reviewed PR commit.
4. Publish that exact wheel to PyPI.
5. Confirm the new wheel is available from PyPI, then run `bash scripts/pre-release-check.sh`.
6. Merge the PR and create the integration release only after the check succeeds.

The pre-release check compares the bundled library package with the PyPI wheel
when their versions match. It rejects a source change that reuses an already
published version, even when every import still resolves. A higher local library
version is allowed only while awaiting its first PyPI publication.

## Required Pre-Publish Check

Run:

```bash
bash scripts/pre-release-check.sh
```

The script:

- validates the integration manifest and Bluetooth matcher safeguards;
- confirms the manifest requirement resolves from PyPI;
- runs the protocol and library import tests;
- builds a wheel from the monorepo source and checks its package contents;
- installs that built wheel in an isolated environment and verifies every integration import.

Do not bypass a failed step. The wheel check specifically prevents publishing a wheel that omits required source modules.

## Publishing

Build and upload from the library directory:

```bash
cd diesel_heater_ble
python -m build
twine check dist/*
twine upload dist/*
```

After upload, verify the exact released version is installable from PyPI:

```bash
python -m pip install --no-cache-dir --index-url https://pypi.org/simple/ "diesel-heater-ble==X.Y.Z"
python -c "import diesel_heater_ble; print(diesel_heater_ble.__file__)"
```

Then update the integration requirement and complete the second pre-release check.

## Failure Handling

If the pre-release check fails, do not publish or tag a release.
Fix the reported source, packaging, requirement, or import problem first.
Rerun the complete check after the repair.

Never upload a wheel merely to satisfy an integration requirement pin.
