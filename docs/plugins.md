# Plugin Framework

The core plugin architecture: what a plugin is, and how Zenith
communicates with it. This milestone defines the contract and the
bookkeeping — it does not discover, load, or import plugins from disk.
Plugins are instantiated directly by whatever creates them (currently:
tests).

## Overview

```
PluginManifest      declarative metadata: id, name, version, description, author
Plugin               abstract base class every plugin implements
PluginState          the plugin's lifecycle state
PluginContext        what a plugin's hooks can see
PluginRegistry        stores plugins and orchestrates their lifecycle
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

## Interaction with Runtime and ApplicationContext

`ApplicationContext` owns one `PluginRegistry` (`context.plugins`),
created the same way it owns `services`, `events`, and `commands` — a
`field(default_factory=PluginRegistry)`. `Runtime` itself does not
register any plugin in this milestone; the lifecycle it owns (`start` /
`stop`) has nothing to load yet. What this milestone establishes is the
path a future loading step will use:

```
Runtime -> ApplicationContext.plugins (PluginRegistry)
             .register(plugin, application_context)
               -> emits PluginRegistered / PluginFailed on ApplicationContext.events
```

Anything that wants to react to plugin lifecycle changes — logging,
future UI, other plugins — subscribes to these events on
`context.events`, exactly as it would for lifecycle or command events.

## Future loading strategy (out of scope here)

This milestone deliberately does not implement how a `Plugin` instance
comes to exist in the first place. Filesystem discovery, dynamic
imports (`importlib`), loading from `plugins/`, ZIP or remote plugins,
inter-plugin dependencies, permissions, sandboxing, plugin configuration
files, hot reload, and auto-discovery are all out of scope. A future
milestone can add a loader that scans `plugins/`, imports each module,
constructs a `Plugin`, and calls `PluginRegistry.register` — everything
that loader would need (the `Plugin` contract, `PluginManifest`,
`PluginRegistry`, the events) already exists as of this milestone.
