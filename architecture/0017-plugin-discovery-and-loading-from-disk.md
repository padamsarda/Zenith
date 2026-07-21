# 0017 — Plugin discovery and loading from disk

- Status: Accepted
- Date: 2026-07-20

## Context

The plugin framework (ADR — see `docs/plugins.md`) shipped the full
contract — `Plugin`, `PluginManifest`, `PluginState`, `PluginContext`,
`PluginRegistry` — and said so explicitly: "this milestone deliberately
does not implement how a `Plugin` instance comes to exist in the first
place." Every plugin in the test suite was constructed directly by the
test itself. `plugins/` held nothing but a `.gitkeep`. `Plugin.register(registry)`
was, in ADR 0013's own words, "the natural distribution mechanism" for
tools and skills — a claim nothing in the repository exercised, because
nothing ever called it outside a test.

This made two things simultaneously true: the registries a loader would
call (`PluginRegistry`, `ToolRegistry`, `SkillRegistry`) already existed
and were fully tested, and there was no way for a plugin authored as a
file on disk to ever reach them. The roadmap's "Zenith runtime > Plugin
loading" item named this precisely: "Discovery/import from `plugins/`
into the existing `PluginRegistry`; the framework and events already
exist. This is what makes `Plugin.register(registry)` the real
distribution mechanism... rather than a hook nothing calls."

Separately, the roadmap's "First real tools and skills" item shipped
five tools (ADR 0016) but left skills at zero: "Skills remain unstarted;
the first genuine skill (as opposed to a tool) is the next piece of this
item." A loader with nothing real to load would prove only that the
mechanism runs, not that it is worth having.

## Decision

**`PluginLoader`** (`runtime/plugins/loader.py`) implements exactly the
strategy `docs/plugins.md` reserved: it scans `plugins_dir`'s immediate
subdirectories for a `plugin.py` file, imports each with
`importlib.util.spec_from_file_location` (not a package-relative
`import`, which would require `plugins/` to be on `sys.path` and would
make `runtime/` statically depend on plugin code — exactly the
dependency direction the framework forbids), calls its module-level
`create_plugin() -> Plugin` factory, and hands the result to
`PluginRegistry.register`. `create_plugin` is a plain function call, not
a decorator or metaclass hook — the framework's "no magic registration"
rule extends to how plugins declare themselves.

**Failures never stop the runtime.** A plugin directory that fails to
import, has no `create_plugin`, whose factory raises, or whose factory
returns something other than a `Plugin` is caught, logged, and reported
as the new `PluginLoadFailed` event — then skipped. A plugin that
imports fine but fails `PluginRegistry.register` itself (validation,
`initialize`/`register` raising) is likewise caught and skipped;
`PluginRegistry` already emits `PluginFailed` for that case, so the
loader does not double-report it. One broken plugin degrades to "one
fewer capability," never "the runtime does not start."

**`Runtime.start()` calls it unconditionally**, after
`_initialize_assistant`, against `base_path / "plugins"` — the same
directory `_verify_required_folders` already requires to exist.
No configuration flag gates this: `plugins/` empty of `plugin.py` files
(the shipped default before this ADR) loads zero plugins and changes
nothing, the same way `AllowAllPolicy` costs nothing when no tool is
registered. This is deliberately unlike `ClaudeProvider` (ADR 0015) and
the ADR 0016 tool suite, which an integrator opts into explicitly:
plugin *discovery* is infrastructure with no side effect on its own,
where registering a real provider or a filesystem/shell tool grants
concrete capability that should never appear by default.

**`plugins/engineering_workflow/`** is the first plugin loaded this way
and the first genuine `Skill` (ADR 0013's `Tool`/`Skill` split had only
ever shipped tools until now). `EngineeringWorkflowSkill` teaches a
provider a safe order of operations — inspect before writing, keep
changes minimal, review the diff, run tests, leave a clean tree —
referencing the ADR 0016 tool suite by `tool_id` where relevant, but
staying correct even where that suite is not registered. Deliberately
**skill-only, no tool**: `Plugin.register(registry)` reaches
`ApplicationContext.skills`/`.tools` through the `ApplicationContext`
captured in `initialize` (the signature `register(self, registry:
PluginRegistry)` only carries the plugin registry itself, so a plugin
contributing capabilities must retain the `PluginContext` it was
initialized with). A skill is inert text with no permission question
(ADR 0013); a tool is not. Auto-loading a plugin that contributed a
tool would hand it to whatever `PermissionPolicy` a deployment has —
`AllowAllPolicy` by default — without the deployment ever having chosen
that tool. This plugin is the proof the mechanism works without also
being the thing that makes auto-loading unsafe in general; a future
tool-contributing plugin is exactly where an integrator's choice of
`PermissionPolicy` starts to matter, same as it already does for
`runtime.tools`.

## Consequences

- `PluginRegistry`, `ToolRegistry`, `SkillRegistry`, and the assistant
  pipeline needed zero changes — `PluginLoader` only calls
  `PluginRegistry.register`, exactly as a test double always has.
- `Plugin.register(registry)` is now exercised by a real plugin on every
  `python main.py` run, not only by test doubles.
- Skills went from zero to one real implementation, closing the
  remaining half of ADR 0013's split. A second genuine skill (or the
  first genuine tool shipped via a plugin, which will need to reckon
  with the default `AllowAllPolicy`) is the next pressure test.
- `plugins/` is now an importable package (`plugins/__init__.py`,
  `plugins/engineering_workflow/__init__.py`) so its own code is
  directly unit-testable; `PluginLoader` never imports it that way
  itself, so this is a testing convenience, not a dependency the loader
  relies on.
- `PluginLoadFailed` joins `PluginFailed` as the framework's second
  failure event, distinguishing "a `Plugin` never came to exist" from
  "a `Plugin` existed and one of its hooks raised" — useful for anyone
  debugging why an expected capability did not show up.
- Plugin *enabling* (`PluginRegistry.enable`) is still never called by
  the loader — loaded plugins land in `REGISTERED`, exactly where a
  directly-constructed test plugin lands today. Nothing in the framework
  gates capability availability on `PluginState.ENABLED` (a registered
  plugin's `register(registry)` hook has already run), so this is
  consistent with existing behavior, not a gap this ADR leaves open.
