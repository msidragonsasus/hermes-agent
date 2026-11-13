"""A real plugin's per-turn note survives discovery, unload and worker restoration."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gateway.session_surface import (
    admit_surface, arm_surface_turn, client_surfaces, restore_surface, surface_note, surface_turn_scope,
)
from hermes_cli import plugins
from hermes_state_runtime import RuntimeStoreError


@pytest.fixture
def registered(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    plugin = home / 'plugins' / 'surface-example'
    plugin.mkdir(parents=True)
    (plugin / 'plugin.yaml').write_text('name: surface-example\nversion: 1.0.0\n', encoding='utf-8')
    (plugin / '__init__.py').write_text(
        'def register(ctx):\n'
        '    ctx.register_client_surface("example-v1", "Server-owned display note")\n', encoding='utf-8')
    (home / 'config.yaml').write_text('plugins:\n  enabled: [surface-example]\n', encoding='utf-8')
    empty = tmp_path / 'no-bundled'
    empty.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('HERMES_BUNDLED_PLUGINS', str(empty))
    plugins._reset_plugin_managers_for_tests()
    yield home
    plugins._reset_plugin_managers_for_tests()


def test_discovery_lifecycle_and_profile_isolation(registered, tmp_path):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    assert 'example-v1' in client_surfaces()
    committed = admit_surface({'surface': 'example-v1'})['surface_v1']
    assert restore_surface(committed) == committed
    agent = SimpleNamespace(valid_tool_names=set())
    with surface_turn_scope(committed):
        arm_surface_turn(agent)
    assert agent._gateway_turn_context_notes == 'Server-owned display note'
    arm_surface_turn(agent)
    assert agent._gateway_turn_context_notes == ''
    other = tmp_path / 'other'
    other.mkdir()
    token = set_hermes_home_override(other)
    try:
        assert 'example-v1' not in client_surfaces()
        with pytest.raises(RuntimeStoreError):
            restore_surface(committed)
    finally:
        reset_hermes_home_override(token)
    manager = plugins.get_plugin_manager()
    manager.unload('surface-example')
    assert 'example-v1' not in client_surfaces()
    manager.discover_and_load(force=True)
    assert surface_note(committed) == 'Server-owned display note'


def test_registration_validation_budget_failure_and_disposal(registered, caplog):
    client_surfaces()
    ctx = plugins.PluginContext(plugins.PluginManifest(name='test'), plugins.get_plugin_manager())
    for name in ('hud', 'voice-live', 'example-v1', '', 'A', 'a_b', 'a' * 33, [], None):
        with pytest.raises(ValueError):
            ctx.register_client_surface(name, 'bad')
    with pytest.raises(TypeError):
        ctx.register_client_surface('invalid-note', 123)
    seen = []
    def note(committed, tools):
        seen.append((committed, tools))
        return 'x' * 6001
    handle = ctx.register_client_surface('bounded', note)
    assert len(surface_note({'surface': 'bounded'}, {'tool'})) == 6000
    assert seen == [({'surface': 'bounded'}, {'tool'})]
    handle.dispose()
    handle.dispose()
    assert 'bounded' not in client_surfaces()
    def broken(committed, tools):
        raise ValueError('synthetic failure')
    ctx.register_client_surface('broken', broken)
    assert surface_note({'surface': 'broken'}) == ''
    assert 'Client surface broken note failed' in caplog.text
    for params in ({'surface': 'missing'}, {'surface': []},
                   {'surface': 'example-v1', 'voice_context': 'not permitted'}):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            admit_surface(params)


@pytest.mark.platforms('any')
def test_fresh_worker_restores_after_its_own_discovery(registered):
    frame = {'policy': {'request_json': json.dumps({'turn_v1': {
        'finite': False, 'unattended': False, 'yolo': False,
        'surface_v1': {'surface': 'example-v1'},
    }})}, 'scope': {'execution_id': 'test-execution'}}
    result = subprocess.run(
        [sys.executable, '-c',
         'import json,sys\n'
         'from types import SimpleNamespace\n'
         'from gateway.session_managed_worker import worker_turn_scope\n'
         'from gateway.session_surface import surface_turn_note\n'
         'with worker_turn_scope(json.loads(sys.argv[1])):\n'
         '    print(surface_turn_note(SimpleNamespace(valid_tool_names=set())))\n', json.dumps(frame)],
        cwd=Path(__file__).resolve().parents[2], env=dict(os.environ),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'Server-owned display note' in result.stdout


def test_legacy_advertisement_and_unknown_surface(registered):
    from tests.tui_gateway.test_hud_surface_note import _session
    from tui_gateway import server
    result = server._methods['gateway.capabilities']('probe', {})['result']
    assert result['client_surfaces'] == client_surfaces()
    session = _session(running=True)
    server._sessions['surface-test'] = session
    try:
        for name, expected in [('example-v1', 'example-v1'), ('unknown', '')]:
            server._methods['prompt.submit']('submit', {
                'session_id': 'surface-test', 'text': 'unchanged user words', 'queued': True, 'surface': name,
            })
            assert session['client_surface'] == expected
            assert server._hud_surface_note(session) == ('Server-owned display note' if expected else '')
    finally:
        server._sessions.pop('surface-test', None)


@pytest.mark.asyncio
async def test_canonical_admission_keeps_text_and_commits_registered_surface(registered, monkeypatch):
    from tests.gateway.test_surface_admission import _authority
    from gateway.session_controls import AuthorityConnection
    from gateway.session_surface import surface_turn_note
    from hermes_state_runtime import list_session_admissions
    seen = []
    async def answer(event):
        seen.append((event.text, surface_turn_note(SimpleNamespace(valid_tool_names=set()))))
        return 'done'
    authority = await _authority(registered, monkeypatch, answer)
    connection = AuthorityConnection(authority, object(), {'user_id': 'owner'})
    try:
        await connection.dispatch({'id': 1, 'method': 'session.resume', 'params': {'session_id': 's'}})
        reply = await connection.dispatch({'id': 2, 'method': 'prompt.submit', 'params': {
            'session_id': 's', 'submission_id': 'registered-surface', 'text': 'original words',
            'surface': 'example-v1'}})
        assert reply['result']['status'] == 'queued', reply
        await authority.sessions['s'].task
        rows = list_session_admissions(authority.db, session_id='s', pending_only=False)
        row = next(row for row in rows if row['request_id'] == 'registered-surface')
        assert row['payload']['surface_v1'] == {'surface': 'example-v1'}
        assert seen == [('original words', 'Server-owned display note')]
    finally:
        await connection.close()
