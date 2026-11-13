"""A registered surface changes the API sidecar, never the visible user row or system prefix."""
from unittest.mock import patch

from gateway.session_surface import arm_surface_turn, surface_turn_scope
from hermes_cli import plugins
from hermes_state import SessionDB
from tests.agent.test_plugin_live_notes_delivery import _agent, _response, _script, _sent_text


def test_surface_note_reaches_model_and_only_the_persisted_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.title_generator.maybe_auto_title', lambda *args, **kwargs: None)
    manager = plugins.get_plugin_manager()
    manager.discover_and_load()
    ctx = plugins.PluginContext(plugins.PluginManifest(name='example-surface'), manager)
    handle = ctx.register_client_surface('example-v1', 'Server-owned display note')
    db = SessionDB(db_path=tmp_path / 'state.db')
    agent = _agent()
    agent._session_db = db
    agent._session_db_created = False
    requests = _script(agent, _response('done'), _response('again'))
    text = 'original user words'
    try:
        with patch.object(agent, '_save_trajectory'), patch.object(agent, '_cleanup_task_resources'):
            with surface_turn_scope({'surface': 'example-v1'}):
                arm_surface_turn(agent)
                first = agent.run_conversation(text)
            arm_surface_turn(agent)
            agent.run_conversation('next turn', conversation_history=first['messages'])
        assert 'Server-owned display note' in _sent_text(requests[0][-1])
        assert 'Server-owned display note' not in _sent_text(requests[1][-1])
        assert requests[0][0] == requests[1][0]
        rows = db.get_messages(agent.session_id)
        user = next(row for row in rows if row['role'] == 'user')
        assert user['content'] == text
        assert 'Server-owned display note' in user['api_content']
    finally:
        handle.dispose()
        db.close()
