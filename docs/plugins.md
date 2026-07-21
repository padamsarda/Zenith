# Plugin Framework

The plugin architecture: what a plugin is, how Zenith discovers and
loads one from disk, and how it communicates with the registries it
contributes to. `PluginRegistry` itself only stores and drives plugins
it is handed — discovery and import are `PluginLoader`'s job (ADR 0017),
kept separate so a test can still construct and register a `Plugin`
directly without touching the filesystem.

## Overview

```
PluginManifest      declarative metadata: id, name, version, description, author
Plugin               abstract base class every plugin implements
PluginState          the plugin's lifecycle state
PluginContext        what a plugin's hooks can see
PluginRegistry        stores plugins and orchestrates their lifecycle
PluginLoader          discovers plugin.py files under plugins/ and registers them
```

## PluginManifest

`runtime.plugins.manifest.PluginManifest` (frozen dataclass) is a
plugin's metadata — nothing behavioral:

| Field | Type | Description |
|---|---|---|
| `plugin_id` | `str` | Required. Stable, author-chosen identifier. |
| `name` | `str` | Required. Display name. |
| `version` | `str` | Required. Basic semantic version (`MAJOR.MINOR.PATCH`, optional `-prerelease`/`+build`). |
| `description` | `str \| None` | Optional. |
| `author` | `str \| None` | Optional. |

Unlike `Command.command_id` (auto-generated per instance, since commands
are created constantly), `plugin_id` is chosen by the plugin author and
stays the same across every run — it is how the same plugin is
recognized run over run. Constructing a `PluginManifest` does not
validate it; that happens at the framework boundary (see Validation
below), the same pattern `Config` and `Command` already follow.

## Plugin

`runtime.plugins.plugin.Plugin` (`abc.ABC`) is the base class every
plugin subclasses. It pairs a fixed `PluginManifest` with a mutable
`PluginState`:

| Member | Kind | Description |
|---|---|---|
| `manifest` | property | The plugin's `PluginManifest`. |
| `id`, `name`, `version`, `description`, `author` | properties | Delegate to `manifest`. |
| `state` | property | Current `PluginState`. |
| `enabled` | property | `state is PluginState.ENABLED`. |
| `transition_to(new_state)` | method | Validated state change — see Validation. |
| `initialize(context)` | abstract | Set up the plugin's own resources. |
| `shutdown(context)` | abstract | Tear down the plugin's own resources. |
| `register(registry)` | abstract | Register the plugin's own capabilities. |
| `unregister(registry)` | abstract | Reverse `register`. |

`Plugin` cannot be instantiated directly — `abc.ABC` enforces that every
subclass implements all four hooks. Nothing about `id`/`name`/`version`/
`description`/`author` can be reassigned after construction (there is no
setter); only `state` changes, and only through `transition_to`.

## PluginState

`runtime.plugins.state.PluginState`:

```
CREATED -> INITIALIZED -> REGISTERED -> ENABLED <-> DISABLED
                       \-> STOPPED           \-> STOPPED
Any non-terminal state -> FAILED
```

`STOPPED` and `FAILED` are terminal (`runtime.plugins.state.TERMINAL_STATES`)
— no further transition is valid from either. A plugin never moves
backward except between `ENABLED` and `DISABLED`.

## PluginContext

`runtime.plugins.context.PluginContext` (frozen dataclass) is built
fresh by `PluginRegistry` for each `register`/`unregister` call and
passed to `initialize`/`shutdown`:

| Field | Type | Description |
|---|---|---|
| `application_context` | `ApplicationContext` | The shared runtime context. |
| `manifest` | `PluginManifest` | The plugin's own manifest. |
| `registry` | `PluginRegistry` | The registry running this lifecycle call. |

## PluginRegistry

`runtime.plugins.registry.PluginRegistry` stores plugins by ID and
orchestrates their lifecycle. It mirrors `ServiceRegistry`'s role as a
simple, explicit lookup table, extended with the hook invocation and
event emission plugins additionally need.

```python
registry.register(plugin, application_context)
registry.enable(plugin, application_context)
registry.disable(plugin, application_context)
registry.unregister(plugin, application_context)

registry.get("my-plugin")     # -> Plugin, raises PluginNotFoundError if missing
registry.has("my-plugin")     # -> bool, never raises
registry.list()               # -> list[Plugin], a snapshot
```

`register`, `unregister`, `enable`, and `disable` take the `Plugin`
object itself — matching `Plugin`'s own hook signatures (`register(registry)`
takes the registry the same way `PluginRegistry.register(plugin)` takes
the plugin). `get` and `has` take a plugin ID string, since a lookup by
definition doesn't yet have the object in hand.

`register`/`unregister`/`enable`/`disable` also take an
`application_context: ApplicationContext` parameter, following the same
shape `CommandExecutor.execute` already uses (see `commands.md`):
`PluginRegistry` cannot hold a reference to the `ApplicationContext`
that owns it (it's built via `field(default_factory=PluginRegistry)`,
with no arguments, before the rest of the context exists), so the
caller supplies it — this is also what gives `PluginRegistry` access to
the `EventBus` it emits on.

### register

1. `validate_plugin(plugin)` — structural checks on the manifest.
2. Duplicate-ID check — raises `PluginRegistrationError` if `plugin.id`
   is already registered.
3. Build a `PluginContext`.
4. `plugin.transition_to(INITIALIZED)`, then `plugin.initialize(context)`.
5. `plugin.transition_to(REGISTERED)`, then `plugin.register(self)`.
6. Store `plugin` and emit `PluginRegistered`.

If step 4 or 5 raises anything, the plugin transitions to `FAILED` (if
not already terminal), `PluginFailed` is emitted, and the original
exception is wrapped and re-raised as `PluginLifecycleError`. `plugin`
is never stored on failure — steps 1–5 all complete before step 6.

### unregister

The reverse order of `register` — undo registration before undoing
setup:

1. Confirm `plugin.id` is registered (`PluginNotFoundError` otherwise).
2. Build a `PluginContext`.
3. `plugin.unregister(self)`, then `plugin.shutdown(context)`, then
   `plugin.transition_to(STOPPED)`.
4. Remove `plugin` and emit `PluginUnregistered`.

Failures in step 3 follow the same `FAILED` + `PluginFailed` +
`PluginLifecycleError` path as `register`; `plugin` stays registered.

### enable / disable

Pure state transitions — `plugin.transition_to(ENABLED)` /
`plugin.transition_to(DISABLED)` plus the matching event. Neither calls
a plugin hook, because `Plugin` exposes no `enable`/`disable` hook.
Both raise `PluginNotFoundError` if `plugin.id` isn't registered, and
let `PluginValidationError` propagate directly if the current state
can't make that transition (e.g. `disable` on a plugin that was never
`enable`d) — unlike `register`/`unregister`, there's no plugin-authored
hook code involved here that could fail for an arbitrary reason, so
there's nothing to wrap in `PluginLifecycleError`.

### Validation

`runtime.plugins.validation` raises `PluginValidationError` for:

- `manifest.plugin_id` / `manifest.name` empty, whitespace-only, or
  padded with whitespace.
- `manifest.version` not matching the basic semver pattern
  (`MAJOR.MINOR.PATCH`, optional `-prerelease`/`+build`).
- `manifest.description` / `manifest.author` present but not a `str`.
- An invalid `PluginState` transition (checked inside
  `Plugin.transition_to`, e.g. `STOPPED -> ENABLED`).

Duplicate-ID and not-found checks live on `PluginRegistry` itself (as
`PluginRegistrationError` / `PluginNotFoundError`), not in
`runtime.plugins.validation` — like duplicate command-ID detection in
`CommandExecutor`, both require tracking plugins across calls, which a
stateless validation function can't do.

## Plugin events

Defined in `runtime.plugins.events`, all `Event` subclasses emitted by
`PluginRegistry` with `source="plugin_registry"`:

- `PluginRegistered` — payload: `plugin_id`, `name`.
- `PluginEnabled` — payload: `plugin_id`, `name`.
- `PluginDisabled` — payload: `plugin_id`, `name`.
- `PluginUnregistered` — payload: `plugin_id`, `name`.
- `PluginFailed` — payload: `plugin_id`, `reason`.

`PluginLoadFailed` (payload: `path`, `reason`) is the one plugin event
*not* emitted by `PluginRegistry` — `PluginLoader` emits it, with
`source="plugin_loader"`, for a plugin directory that never produced a
`Plugin` to hand the registry (see PluginLoader, below).

Same rules as every other event on the bus (see `events.md`): type-exact
dispatch, subscription order preserved, a failing listener is logged and
does not stop the others.

## Exceptions

Added to `runtime.exceptions`, all under `PluginError(ZenithError)`:

- `PluginRegistrationError` — duplicate ID on `register`.
- `PluginNotFoundError` — `get`/`unregister`/`enable`/`disable` on an ID
  that isn't registered. Mirrors `ServiceNotFoundError`.
- `PluginValidationError` — manifest/version/id format, or an invalid
  state transition.
- `PluginLifecycleError` — a hook raised during `register` or
  `unregister`. Wraps the original exception (`__cause__`).
- `PluginLoadError` — raised internally by `PluginLoader` for a plugin
  directory that never produced a `Plugin` (import failure, missing
  `create_plugin`, or a factory that didn't return one).
  `PluginLoader.load_all` always catches this itself; it does not
  escape to callers.

## PluginLoader

`runtime.plugins.loader.PluginLoader` (ADR 0017) is how a `Plugin`
instance comes to exist from a file on disk, rather than from a test
constructing one directly.

**Convention:** every immediate subdirectory of `plugins/` is a
candidate plugin. A candidate is loaded if it contains a `plugin.py`
file with a module-level factory function:

```python
# plugins/my_plugin/plugin.py
from runtime.plugins.plugin import Plugin

class MyPlugin(Plugin):
    ...

def create_plugin() -> Plugin:
    return MyPlugin()
```

No decorator, no metaclass, no registration side effect on import —
`create_plugin` is called explicitly, once, by the loader.

```python
loader = PluginLoader(plugins_dir)
loaded = loader.load_all(registry, application_context)   # -> list[Plugin]
```

`load_all`:

1. Discovers `plugin.py` files directly under `plugins_dir`'s immediate
   subdirectories, sorted by directory name (`plugins_dir` not existing
   discovers nothing — not an error).
2. Imports each with `importlib.util.spec_from_file_location` (a
   file-path import, not a package-relative one — `runtime/` never
   statically imports `plugins/` or anything under it).
3. Calls the module's `create_plugin()` and hands the result to
   `registry.register(plugin, application_context)`.

**Failures never propagate out of `load_all`.** A plugin directory that
fails to import, has no `create_plugin`, whose factory raises, or whose
factory returns something other than a `Plugin` is logged and reported
as `PluginLoadFailed` (payload: `path`, `reason`), then skipped. A
plugin that imports fine but fails `PluginRegistry.register` itself
(bad manifest, an `initialize`/`register` hook raising) is also caught
and skipped — `PluginRegistry` already emitted `PluginFailed` for that
case, so the loader does not double-report it. One broken plugin never
prevents the rest, or the runtime, from starting.

## Interaction with Runtime and ApplicationContext

`ApplicationContext` owns one `PluginRegistry` (`context.plugins`),
created the same way it owns `services`, `events`, and `commands` — a
`field(default_factory=PluginRegistry)`. `Runtime.start()` calls
`PluginLoader(base_path / "plugins").load_all(context.plugins, context)`
unconditionally, after the assistant subsystem is ready — `plugins/` is
already a required top-level folder (`REQUIRED_FOLDERS`), so this
requires no new configuration:

```
Runtime.start()
  -> PluginLoader(base_path / "plugins")
       .load_all(context.plugins, context)
         -> for each plugin.py: import, create_plugin(), registry.register(plugin, context)
              -> emits PluginRegistered / PluginFailed / PluginLoadFailed on context.events
```

An empty `plugins/` (no `plugin.py` files) loads nothing and changes
nothing — discovery itself has no side effect. This is unlike
registering `ClaudeProvider` (ADR 0015) or an ADR 0016 tool, which an
integrator opts into explicitly because doing so grants real capability;
a plugin that only contributes a `Skill` is inert text with no
permission question (ADR 0013) and is safe to auto-load, but a plugin
that contributes a `Tool` hands it to whatever `PermissionPolicy` is
configured — `AllowAllPolicy` by default. An integrator loading
untrusted plugins should pair it with a `ToolAllowlistPolicy`, the same
seam that already governs directly-registered tools.

Anything that wants to react to plugin lifecycle or load changes —
logging, future UI, other plugins — subscribes to these events on
`context.events`, exactly as it would for lifecycle or command events.

## Reaching other registries from a plugin

`Plugin.register(self, registry: PluginRegistry)` only carries the
plugin registry itself — not `ApplicationContext`, so not
`context.tools`/`context.skills` directly. A plugin that contributes a
tool or skill captures the `ApplicationContext` in `initialize` (which
does receive a `PluginContext`) and uses it from `register`:

```python
def initialize(self, context: PluginContext) -> None:
    self._application_context = context.application_context

def register(self, registry: PluginRegistry) -> None:
    self._application_context.skills.register(my_skill, self._application_context)

def unregister(self, registry: PluginRegistry) -> None:
    self._application_context.skills.unregister(my_skill.skill_id, self._application_context)
```

`PluginRegistry.register` always calls `initialize` before `register`,
so the captured context is available by the time `register` runs.
`plugins/engineering_workflow/plugin.py` is a real, tested example of
this shape — see ADR 0017.

## Out of scope

ZIP or remote plugins, inter-plugin dependencies, plugin permissions or
sandboxing beyond a tool's own `PermissionPolicy`, plugin-specific
configuration files, and hot reload remain unimplemented. Nothing about
`PluginLoader`'s discovery convention forecloses any of them — a future
change extends the loader, not the framework underneath it.
