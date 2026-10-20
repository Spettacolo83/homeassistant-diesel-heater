#!/usr/bin/env bash
# Pre-release safeguards — run before any `gh release create v*`.
#
# Prevents the known emergency classes:
#
# 1. PyPI pin drift — manifest.json requires `diesel-heater-ble>=X.Y.Z` but
#    the version actually on PyPI is missing a symbol the integration
#    imports (symptom: `ImportError` on HA module load, user sees broken
#    install). Caused beta.3/beta.4.
#
# 2. Invalid BT matcher — manifest.json has a local_name matcher HA's
#    bluetooth startup validator rejects (symptom: entire HA bluetooth
#    component fails startup, cascades to every BLE integration).
#    Caused beta.6/beta.7.
#
# 3. Integration setup regression — logic unit tests pass but the real
#    `async_setup_entry` fails. Partial coverage via existing coordinator
#    tests; this script runs the deterministic manifest + PyPI + lint
#    checks that would already have blocked the known classes.
#
# 4. Monorepo bundled-src incompleteness — the `diesel_heater_ble/src/`
#    tree is missing one of the modules the integration imports, so a
#    local `python -m build` from this repo produces a wheel that is
#    missing __init__.py or const.py or protocol.py and silently uploads
#    broken to PyPI. Caused the 0.3.7 publish on 2026-10-15. Covered by
#    the new [4/4] step below.
#
# Fail loudly: `set -euo pipefail`. Any non-zero exit MUST block the
# release pipeline.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/custom_components/diesel_heater/manifest.json"
INTEGRATION_PATH="$REPO_ROOT/custom_components/diesel_heater"

echo "=== pre-release-check for $(python3 -c "import json; print(json.load(open('$MANIFEST'))['version'])") ==="
echo

# ---------------------------------------------------------------------------
# 1. Manifest safeguards (pytest reproduces HA startup validators)
# ---------------------------------------------------------------------------

echo "[1/4] manifest safeguards (local_name validator + requirement pin)..."
python3 -m pytest "$REPO_ROOT/tests/test_manifest.py" -q --tb=short
echo "    OK"
echo

# ---------------------------------------------------------------------------
# 2. PyPI pin consistency
#
# Resolve the manifest's `diesel-heater-ble>=X.Y.Z` pin, install THAT
# version from PyPI into an isolated venv (NOT the bundled source), then
# verify every `from diesel_heater_ble...` import the integration uses
# resolves against the installed package. This catches the "renamed a
# symbol in bundled src/ without a PyPI publish" class of bug.
# ---------------------------------------------------------------------------

echo "[2/4] PyPI pin consistency (install pinned diesel-heater-ble from index + verify imports)..."

PIN=$(python3 -c "
import json
req = json.load(open('$MANIFEST'))['requirements'][0]
for op in ('>=', '==', '~='):
    if op in req:
        _, ver = req.split(op, 1)
        print(ver.strip())
        break
")

if [ -z "$PIN" ]; then
    echo "ERROR: could not extract pin from manifest requirements"
    exit 1
fi

PYPI_VER=$(curl -s https://pypi.org/pypi/diesel-heater-ble/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])")

python3 -c "
from packaging.version import Version
pin = Version('$PIN')
served = Version('$PYPI_VER')
if served < pin:
    print(f'ERROR: PyPI serves diesel-heater-ble $PYPI_VER but manifest requires >={pin}')
    print('       Publish the new library to PyPI BEFORE releasing the integration')
    print('       (see docs/pypi-publishing.md).')
    raise SystemExit(1)
print(f'    pin={pin} <= PyPI={served} - OK')
"

TMPDIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMPDIR" "${WHEEL_TMP:-}"
}
trap cleanup EXIT
python3 -m venv "$TMPDIR/venv"
# shellcheck disable=SC1091
source "$TMPDIR/venv/bin/activate"
pip install -q --upgrade pip
# --no-cache-dir + explicit index-url bypasses stale pip mirror cache that lags
# behind the authoritative /pypi/.../json API we checked above (seen 2026-10-06:
# the JSON API served 0.3.6 immediately after `twine upload`, but the pip simple
# index took several minutes to see it).
pip install -q --no-cache-dir --index-url https://pypi.org/simple/ "diesel-heater-ble==$PYPI_VER"

python3 - "$INTEGRATION_PATH" <<'PYEOF'
import ast
import importlib
import pathlib
import sys

INTEGRATION = pathlib.Path(sys.argv[1])
missing: list[tuple[str, str, str]] = []

for py_file in sorted(INTEGRATION.rglob("*.py")):
    source = py_file.read_text()
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as e:
        print(f"  SKIP {py_file}: {e}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("diesel_heater_ble"):
            try:
                mod = importlib.import_module(node.module)
            except ImportError as e:
                missing.append((py_file.name, node.module, f"module not importable: {e}"))
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not hasattr(mod, alias.name):
                    missing.append((py_file.name, f"{node.module}.{alias.name}", "symbol not exported by installed package"))

if missing:
    print("    FAILURES:")
    for src, sym, reason in missing:
        print(f"      {src} -> {sym}: {reason}")
    print()
    print("    This is the beta.3/beta.4 class of bug: the integration imports a")
    print("    symbol that doesn't exist in the version of diesel-heater-ble on")
    print("    PyPI. Either downgrade the import, bump the manifest pin, or publish")
    print("    the new library version first (see docs/pypi-publishing.md).")
    sys.exit(1)

print("    all integration imports resolve against the pinned PyPI package - OK")
PYEOF

deactivate
echo

# ---------------------------------------------------------------------------
# 3. Full protocol + library import suite against the bundled source
# ---------------------------------------------------------------------------

echo "[3/4] full protocol + library tests..."
cd "$REPO_ROOT"
python3 -m pytest tests/test_protocol.py tests/test_library_import.py tests/test_manifest.py diesel_heater_ble/tests/ --tb=short -q
echo "    OK"
echo

# ---------------------------------------------------------------------------
# 4. Monorepo-built wheel is complete
#
# Builds the diesel-heater-ble wheel from the bundled src/ tree, inspects
# its contents, installs it into an isolated venv, and imports every
# `diesel_heater_ble.<name>` the integration references. If any Python
# module in src/ is missing (as happened on 2026-10-15 when __init__.py
# and const.py were never committed), the wheel is incomplete and this
# step fails — before the broken wheel can be `twine upload`-ed.
# ---------------------------------------------------------------------------

echo "[4/4] bundled-library wheel completeness (prevents 0.3.7-class incident)..."

LIB_DIR="$REPO_ROOT/diesel_heater_ble"
LIB_VER=$(python3 -c "
import re, pathlib
toml = pathlib.Path('$LIB_DIR/pyproject.toml').read_text()
m = re.search(r'^version = \"([^\"]+)\"', toml, re.M)
print(m.group(1) if m else '')
")

if [ -z "$LIB_VER" ]; then
    echo "ERROR: could not extract library version from pyproject.toml"
    exit 1
fi

WHEEL_TMP=$(mktemp -d)

# Build in a copy so we don't pollute the repo's dist/ dir
cp -r "$LIB_DIR" "$WHEEL_TMP/build-src"
cd "$WHEEL_TMP/build-src"
rm -rf dist/ build/ src/diesel_heater_ble.egg-info 2>/dev/null || true

python3 -m venv "$WHEEL_TMP/buildenv"
# shellcheck disable=SC1091
source "$WHEEL_TMP/buildenv/bin/activate"
pip install -q --upgrade pip build
python3 -m build --wheel --outdir "$WHEEL_TMP/dist" 2>&1 | tail -3
deactivate

WHEEL=$(ls "$WHEEL_TMP/dist"/*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
    echo "ERROR: build did not produce a wheel"
    exit 1
fi
echo "    built wheel: $(basename "$WHEEL")"

# Required files inside the wheel — if any is missing, the publish will be
# as broken as 2026-10-15's 0.3.7.
python3 - "$WHEEL" <<'PYEOF'
import sys, zipfile

wheel_path = sys.argv[1]
# Must-have Python modules at package root
REQUIRED = ["__init__.py", "const.py", "protocol.py"]

with zipfile.ZipFile(wheel_path) as zf:
    names = zf.namelist()

missing = []
for mod in REQUIRED:
    if not any(n.endswith(f"diesel_heater_ble/{mod}") for n in names):
        missing.append(mod)

if missing:
    print(f"    FAILURES:")
    for m in missing:
        print(f"      diesel_heater_ble/{m}: not present in wheel")
    print()
    print("    This is the 2026-10-15 0.3.7-class incident: the monorepo src/")
    print("    tree is missing one of the modules. A `twine upload` of this")
    print("    wheel would ship a package without the required module.")
    print()
    print("    Fix: commit the missing file(s) back to")
    print(f"      $REPO_ROOT/diesel_heater_ble/src/diesel_heater_ble/")
    print("    then re-run this script.")
    sys.exit(1)

print(f"    wheel contains all {len(REQUIRED)} required modules - OK")
PYEOF

# Also: install the built wheel into a venv and verify every top-level
# symbol from the published __all__ actually imports. Catches the case
# where files exist but, say, __init__.py doesn't re-export a symbol
# that the integration imports from the package root.
python3 -m venv "$WHEEL_TMP/testenv"
# shellcheck disable=SC1091
source "$WHEEL_TMP/testenv/bin/activate"
pip install -q "$WHEEL"

python3 - "$INTEGRATION_PATH" <<'PYEOF'
import ast
import importlib
import pathlib
import sys

INTEGRATION = pathlib.Path(sys.argv[1])
missing: list[tuple[str, str, str]] = []
for py_file in sorted(INTEGRATION.rglob("*.py")):
    source = py_file.read_text()
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("diesel_heater_ble"):
            try:
                mod = importlib.import_module(node.module)
            except ImportError as e:
                missing.append((py_file.name, node.module, f"module not importable: {e}"))
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not hasattr(mod, alias.name):
                    missing.append((py_file.name, f"{node.module}.{alias.name}", "symbol not re-exported by built wheel"))

if missing:
    print("    FAILURES against built-from-monorepo wheel:")
    for src, sym, reason in missing:
        print(f"      {src} -> {sym}: {reason}")
    sys.exit(1)
print("    all integration imports resolve against the built-from-monorepo wheel - OK")
PYEOF

deactivate
echo

echo "=== all pre-release checks passed ==="
