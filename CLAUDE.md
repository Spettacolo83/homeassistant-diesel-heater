# Claude Code Memory - Diesel Heater Integration

## Release Workflow

### Versioning Rules

1. **Beta/Pre-release versions** for:
   - New features not yet tested in production
   - Protocol implementations awaiting user feedback
   - Any changes that need real-world validation
   - Format: `vX.Y.Z-beta.N` (e.g., `v2.1.4-beta.1`)

2. **Stable releases** only for:
   - Bug fixes for issues reported by users
   - Features that have been tested and confirmed working
   - Documentation-only changes

### How to Create Releases

**Beta release:**
```bash
gh release create v2.1.4-beta.1 --prerelease --title "v2.1.4-beta.1 - Feature Name" --notes "..."
```

**Stable release:**
```bash
gh release create v2.1.4 --title "v2.1.4 - Feature Name" --notes "..."
```

## Project Structure

- `custom_components/diesel_heater/` - Home Assistant integration
- `diesel_heater_ble/` - PyPI library (monorepo, published to pypi.org)
- `tests/` - Test files
- `docs/protocols/` - Protocol documentation

## PyPI Publishing

Library: `diesel-heater-ble` on PyPI
- Build: `cd diesel_heater_ble && python -m build`
- Upload: `python -m twine upload dist/diesel_heater_ble-X.Y.Z*`
- Requires manual authentication (no stored credentials)

## GitHub Repos

- Integration: `Spettacolo83/homeassistant-diesel-heater`
- Brands PR target: `home-assistant/brands`
- Docs PR target: `home-assistant/home-assistant.io`
- Core PR target: `home-assistant/core`

## Current Status

- Hcalory MVP1/MVP2: In testing (awaiting user feedback)
- Sunster V2.1: Implemented, awaiting testing
- HA Core submission: PR #162647 open, awaiting review
