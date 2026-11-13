---
title: Client surfaces
description: Register per-turn client display context without changing user text or the system prefix.
---

# Client surfaces

Use `ctx.register_client_surface(name, note)` when a client needs to tell the model
which renderer is displaying one turn. This is display context, not permission to
use tools or accounts. The server plugin owns the note; the client sends only a name.

```python
def register(ctx):
    if hasattr(ctx, "register_client_surface"):
        ctx.register_client_surface("example-v1", "This turn is shown by the example renderer.")
```

Names must match `[a-z][a-z0-9-]{0,31}`. Built-in `hud` and `voice-live` names cannot
be replaced, and duplicate registrations raise `ValueError`. Notes are strings or
synchronous callables `note(committed, valid_tool_names) -> str`. The callable gets
a copy of the committed surface fields and the executing agent's available tool
names. Rendered plugin notes are truncated to 6000 characters. A callback exception
or non-string result is logged and omits the note without failing the turn.

The returned `PluginRegistration` supports `dispose()`. Disable, unload, failed load,
and force reload use the existing ownership ledger to release registrations. Each
profile has its own registry; another profile's registration is neither advertised
nor accepted. Ordinary isolated plugin hosts support the same API.

Clients query `gateway.capabilities` (with their optional `profile`) and check the
sorted `client_surfaces` list before sending `prompt.submit` with `surface: "example-v1"`.
Cache the advertisement only for that authenticated connection and profile. When a
name is absent, use the client's legacy behavior. Do not send an unregistered name:
the canonical transport rejects it with `invalid_params`; the legacy transport
clears it. `session.redirect` and `session.steer` do not accept this parameter.

Canonical admission commits `surface_v1` for that turn. The note is projected onto
the model-bound user-message sidecar; persisted user `content` and the frozen system
prefix remain unchanged. Install and enable the plugin for both intake and execution
processes. Admission, capability lookup and managed-worker restoration perform
idempotent discovery in the owning profile before consulting the registry.
`voice_context` remains restricted to the built-in `voice-live` surface.
