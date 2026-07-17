# Service Registry

`runtime.registry.ServiceRegistry` is a small, named lookup table for
shared service objects.

## What it is

```python
registry = ServiceRegistry()
registry.register("clock", my_clock)
registry.has("clock")      # True
registry.get("clock")      # my_clock
registry.unregister("clock")
```

- `register(name, service)` — stores `service` under `name`. Raises
  `ValidationError` if `name` is invalid (empty, or has leading/trailing
  whitespace), and `ServiceAlreadyRegisteredError` if `name` is already
  taken.
- `unregister(name)` — removes the entry. Raises `ServiceNotFoundError`
  if `name` isn't registered.
- `get(name)` — returns the stored object. Raises `ServiceNotFoundError`
  if `name` isn't registered.
- `has(name)` — returns `True`/`False`, never raises.

## What it is NOT

This is explicitly not a dependency-injection framework:

- It does not construct services.
- It does not resolve constructor arguments.
- It does not perform any wiring or auto-discovery.
- There are no decorators and no magic — registration is one explicit
  method call.

It exists so that future subsystems have one obvious, explicit place to
publish and retrieve shared objects, instead of relying on globals or
passing long constructor argument lists around.

## Where it lives

Each `ApplicationContext` owns its own `ServiceRegistry`
(`context.services`), so registries are never shared implicitly between
two `Runtime`/`ApplicationContext` instances (this matters for tests,
which create a fresh context per test).
