# Event System

An in-process, synchronous publish/subscribe system used to decouple the
runtime's lifecycle from anything that wants to react to it.

## Event

`runtime.events.event.Event` is the base class for every event. It is a
frozen (immutable) dataclass with these fields:

| Field | Type | Description |
|---|---|---|
| `source` | `str` | What emitted the event, e.g. `"runtime"`. |
| `payload` | `dict[str, Any]` | Optional extra data. Defaults to `{}`. |
| `event_id` | `UUID` | Unique per event, auto-generated. |
| `timestamp` | `datetime` | UTC, auto-generated. |
| `name` | `str` (property) | The event's class name. |

Concrete events are plain subclasses with no new fields, e.g.:

```python
@dataclass(frozen=True)
class ApplicationStarting(Event):
    """Emitted when the runtime begins startup."""
```

### Built-in events

Defined in `runtime.events.lifecycle_events`:

- `ApplicationStarting`
- `ApplicationStarted`
- `ApplicationStopping`
- `ApplicationStopped`
- `ApplicationStartupFailed` — startup failed for a non-configuration reason
  (e.g. a missing required folder); `payload["reason"]` holds the message.
- `ConfigurationLoaded`
- `ConfigurationLoadFailed` — `payload["reason"]` holds the parse error.

## EventBus

`runtime.events.bus.EventBus` dispatches events to listeners subscribed to
their exact type.

```python
bus.subscribe(ApplicationStarted, on_started)
bus.emit(ApplicationStarted(source="runtime"))
bus.unsubscribe(ApplicationStarted, on_started)
bus.clear()
```

- **Type-exact dispatch.** A listener subscribed to `ApplicationStarted`
  is only called for `ApplicationStarted` instances, not subclasses or
  siblings.
- **Subscription order is preserved.** Listeners run in the order they
  were subscribed.
- **Duplicate subscriptions are allowed.** Subscribing the same listener
  twice means it runs twice per `emit`; call `unsubscribe` once per
  `subscribe` to fully remove it.
- **Exception isolation.** If a listener raises, the bus logs the failure
  (via the logger passed to `EventBus`, or `logging.getLogger("zenith.events")`
  by default) and continues to the next listener. `emit` never raises
  because of a listener.
- **Synchronous only.** No asyncio, threads, or queues — `emit` calls
  every listener on the calling thread before returning.

`unsubscribe` raises `EventBusError` if the listener was never subscribed
to that event type.

## EventLogger

`runtime.events.event_logger.EventLogger` writes one INFO-level log line
per event, containing its timestamp, name, and source. `EventBus` owns an
`EventLogger` internally and calls it at the start of every `emit`, so
every event that passes through the bus is logged automatically — no
extra wiring is required.

## Runtime integration

`Runtime` never calls a listener directly. It only ever calls
`context.events.emit(...)`; the bus is the sole path from "something
happened" to "listeners find out." See `architecture.md` for exactly
which events fire at which point in the lifecycle.
