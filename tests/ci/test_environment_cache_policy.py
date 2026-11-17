"""Cache policy may change setup cost, never locked synchronization."""
from pathlib import Path

import yaml


def test_environment_cache_opt_out_retains_locked_sync():
    action = yaml.safe_load(Path('actions/setup-cached-uv/action.yml').read_text())
    steps = action['runs']['steps']
    restore = next(s for s in steps if s.get('id') == 'restore')
    save = next(s for s in steps if 'actions/cache/save@' in s.get('uses', ''))
    sync = next(s for s in steps if s.get('run', '').endswith(' sync'))
    assert action['inputs']['cache-environment']['default'] == 'true'
    assert "inputs.cache-environment == 'true'" in restore['if']
    assert "inputs.cache-environment == 'true'" in save['if']
    assert 'if' not in sync


def test_caller_uv_version_controls_install_and_environment_identity():
    action = yaml.safe_load(Path('actions/setup-cached-uv/action.yml').read_text())
    assert action['inputs']['uv-version']['default'] == '0.11.19'
    steps = action['runs']['steps']
    install = next(s for s in steps if 'astral-sh/setup-uv@' in s.get('uses', ''))
    assert install['with']['version'] == '${{ inputs.uv-version }}'
    identity = next(s for s in steps if s.get('id') == 'identity')
    assert '${{ inputs.uv-version }}' in identity['env']['CACHE_VARIANT']


def test_uv_cache_location_is_caller_owned_and_defaults_to_setup_uv():
    """An empty path keeps setup-uv's own choice; a caller path reaches it unchanged."""
    action = yaml.safe_load(Path('actions/setup-cached-uv/action.yml').read_text())
    assert action['inputs']['uv-cache-path']['default'] == ''
    install = next(s for s in action['runs']['steps'] if 'astral-sh/setup-uv@' in s.get('uses', ''))
    assert install['with']['cache-local-path'] == '${{ inputs.uv-cache-path }}'
    assert install['with']['enable-cache'] is True
