import json
from pathlib import Path


def test_bluetooth_local_name_matchers_have_fixed_prefixes():
    manifest_path = Path(__file__).parents[1] / 'custom_components/diesel_heater/manifest.json'
    manifest = json.loads(manifest_path.read_text())

    for matcher in manifest['bluetooth']:
        local_name = matcher.get('local_name')
        if local_name:
            assert '*' not in local_name[:3]
            assert '[' not in local_name[:3]


def test_heatgenie_discovery_uses_valid_name_matchers():
    manifest_path = Path(__file__).parents[1] / 'custom_components/diesel_heater/manifest.json'
    manifest = json.loads(manifest_path.read_text())

    assert {'connectable': True, 'local_name': 'C1:*:FE:*'} in manifest['bluetooth']
    assert {'connectable': True, 'local_name': 'boygu*'} in manifest['bluetooth']
    assert {'connectable': True, 'local_name': 'BOYGU*'} in manifest['bluetooth']
    assert not any('service_uuid' in matcher for matcher in manifest['bluetooth'])
