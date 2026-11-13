"""Client surface callbacks work through the ordinary isolated plugin host."""
import pytest

from tests.hermes_cli.test_plugin_host import _home_with_plugins


@pytest.mark.platforms('any')
@pytest.mark.parametrize('isolation', ['host', 'in_process'])
def test_surface_callback_and_unload_in_either_isolation_mode(tmp_path, monkeypatch, isolation):
    from gateway.session_surface import client_surfaces, surface_note
    from hermes_cli import plugins
    _home_with_plugins(tmp_path, monkeypatch, {'surfaceprobe': '''
def register(ctx):
    ctx.register_client_surface("example-v1", lambda committed, tools:
        committed["surface"] + ":" + ",".join(sorted(tools or [])))
'''}, isolation=isolation)
    plugins._reset_plugin_managers_for_tests()
    manager = plugins.get_plugin_manager()
    try:
        assert 'example-v1' in client_surfaces(), manager._plugins['surfaceprobe'].error
        assert surface_note({'surface': 'example-v1'}, {'b', 'a'}) == 'example-v1:a,b'
        manager.unload('surfaceprobe')
        assert 'example-v1' not in client_surfaces()
    finally:
        plugins._reset_plugin_managers_for_tests()
