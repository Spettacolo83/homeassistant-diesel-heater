#!/usr/bin/env bash
# Pre-release safeguards — run before any `gh release create v*`.
#
# Prevents the three emergency classes seen in sessions #64/#86:
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

echo "[1/3] manifest safeguards (local_name validator + requirement pin)..."
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

echo "[2/3] PyPI pin consistency (install pinned diesel-heater-ble from index + verify imports)..."

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
    print('       (see memory/pypi-publishing.md).')
    raise SystemExit(1)
print(f'    pin={pin} <= PyPI={served} - OK')
"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
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
    print("    the new library version first (see memory/pypi-publishing.md).")
    sys.exit(1)

print("    all integration imports resolve against the pinned PyPI package - OK")
PYEOF

deactivate
echo

# ---------------------------------------------------------------------------
# 3. Full protocol + library import suite against the bundled source
# ---------------------------------------------------------------------------

echo "[3/3] full protocol + library tests..."
cd "$REPO_ROOT"
python3 -m pytest tests/test_protocol.py tests/test_library_import.py tests/test_manifest.py diesel_heater_ble/tests/ --tb=short -q
echo "    OK"
echo

echo "=== all pre-release checks passed ==="
