# PostgreSQL runtime Sets and legacy SQLite compatibility

This document defines the non-negotiable rules for PostgreSQL-backed Scipion runtime Sets.

The purpose of the compatibility layer is to allow legacy or third-party protocols that explicitly require `Set.getFileName()` to continue working without restoring SQLite as runtime persistence.

## Source of truth

PostgreSQL is the only authoritative persistence layer for runtime Sets.

The authoritative data includes:

* Set metadata and properties.
* Root Set items.
* Nested logical-table items.
* Streaming state.
* Item schemas.
* Runtime relations and object identities.

A compatibility SQLite file is never the authoritative output of a protocol.

Deleting a compatibility SQLite file must not cause any persistent data loss.

## When SQLite compatibility is allowed

A SQLite compatibility snapshot may be created only when legacy code explicitly requests a filename through APIs such as:

```python
runtimeSet.getFileName()
```

Normal runtime operations must continue using the PostgreSQL mapper directly.

Do not create compatibility SQLite files proactively for every PostgreSQL Set.

Do not use compatibility SQLite as the active mapper or persistent storage of a protocol output.

## Temporary-file location

Compatibility SQLite files must be created only under:

```text
/tmp/postgresql-runtime-sets/worker-<PID>/
```

or the equivalent path rooted at `tempfile.gettempdir()`.

They must never be created inside:

```text
Runs/
extra/
project root/
```

or any other persistent project directory.

The filename must include a worker-local unique component. A path based only on `setId` or `tableId` is forbidden.

A typical path is:

```text
/tmp/postgresql-runtime-sets/worker-31001/SetOfParticles-set-4210-a31f6c.sqlite
```

## Consumer isolation and concurrency

Each protocol worker owns its compatibility SQLite files.

Two different consumer workers reading the same PostgreSQL Set must receive different SQLite paths.

For example:

```text
PostgreSQL setId 4210
    ├── worker 31001 → SQLite A
    ├── worker 31042 → SQLite B
    ├── worker 31103 → SQLite C
    └── worker 31177 → SQLite D
```

The consumers share PostgreSQL, not SQLite.

A producer protocol must never write into a consumer's compatibility SQLite file.

Different workers must never rebuild, delete, open for writing, or otherwise manage the same compatibility SQLite path.

The worker PID directory and unique filename component are part of the concurrency contract and must not be removed during cleanup or refactoring.

## Stable path inside one consumer

A legacy streaming protocol may request `getFileName()` once, store the returned path, and reopen that same path repeatedly.

Therefore, inside one worker:

* The first materialization creates the compatibility path.
* Later refreshes must reuse the same path.
* The contents of that path must be rebuilt when PostgreSQL changes.
* A refresh must not return a new filename.

Changing the path during streaming would leave legacy protocols reading an obsolete snapshot.

## Streaming refresh contract

A compatibility SQLite file is a snapshot, not a live database.

Before a managed compatibility path is reopened, the compatibility layer must:

1. Refresh the PostgreSQL runtime Set state.
2. Obtain the current PostgreSQL revision token.
3. Compare it with the revision used for the cached SQLite snapshot.
4. Rebuild the SQLite file at the same path if the revision changed.
5. Open the SQLite file only after the rebuild has completed.

The revision token must change when relevant PostgreSQL content changes, including:

* Root item count.
* Maximum root item identifier.
* Root item update timestamps.
* Set update timestamp.
* Logical-table update timestamps.
* Nested item update timestamps.

An unchanged revision should reuse the current snapshot without copying all items again.

## Streaming cursor stability

A full SQLite rebuild must not cause a legacy streaming consumer to process old items again or miss new items.

Compatibility item creation timestamps must therefore be stable across rebuilds.

The compatibility cursor is derived from the persistent Scipion item identifier, not from:

* Materialization time.
* PostgreSQL query time.
* The order in which rows were copied.
* A newly generated timestamp.

The same item identifier must receive the same compatibility creation value on every rebuild.

## Stream state and Set metadata

Every rebuild must copy the current Set-level metadata required by native Scipion code, including the stream state.

When the PostgreSQL producer closes its stream, the next compatibility refresh must expose `Set.STREAM_CLOSED` to the legacy consumer.

Set-level properties that are missing but recoverable from persisted items, such as an image sampling rate, may be hydrated on the detached runtime object.

This hydration must remain runtime-only unless normal output persistence explicitly stores the property.

## Parent protocol and output immutability

Reading or materializing an input must never modify its parent protocol or canonical parent output.

The compatibility layer must not:

* Save the parent protocol.
* Store the parent output.
* Repair the parent output in PostgreSQL.
* Change the parent output's persistent mapper.
* Attach new persistent children to the parent protocol.
* Backfill the parent output as a side effect of a child protocol execution.

Runtime hydration may modify only the detached in-memory object reconstructed for the consumer worker.
Consumer isolation is transitive. Any PostgreSQL runtime Set reached through a detached input, including nested Set items and Set-valued Pointer or PointerList targets, must also remain detached and read-only. A consumer must not regain PostgreSQL write capability by traversing or cloning an input object graph.
The same isolation applies when the root runtime input is not a Set. A structured Pointer nested inside a generic PostgreSQL input object must resolve Set targets through the consumer-owned detached input resolver and must never restore access through the canonical parent protocol.
Generic PostgreSQL object hydration must preserve nested parent identity through Scipion `_objParentId` values without synthesizing strong `_objParent` links between reconstructed attributes. Native Scipion object mappers do not create those strong links, and doing so introduces cyclic object graphs that break recursive operations such as `Object.copy()` and `Volume.copyInfo()`.

## Materialization synchronization

Rebuilding one managed compatibility path must be serialized inside its worker.

The materializer lock must cover:

* Revision inspection.
* Removal of the stale SQLite file and its sidecars.
* Schema creation.
* Metadata copying.
* Item copying.
* Final SQLite write and close.

The legacy consumer must not open the SQLite file until the writer has closed it.

Recursive materialization of the same runtime Set must fail immediately instead of deadlocking.

Native nested Set implementations may call `load()` internally from `append()`, `_insertItem()`, or equivalent item-mapper setup methods. Every destination Set created while constructing a compatibility snapshot must carry the compatibility-build marker until its nested data has been copied and its mapper detached.

This marker applies only to native destination objects being written into the temporary SQLite snapshot. It must never be used to suppress recursive materialization of the PostgreSQL source runtime Set.

## Managed-path registration

A materialized path must be registered only in the memory of its worker process.

The registry maps:

```text
managed SQLite path → PostgreSQL runtime Set
```

The registry must not be persisted to PostgreSQL or the project.

Weak references should be used so registration does not keep an otherwise unused runtime Set alive.

A path that is not registered in the current worker must be treated as an ordinary SQLite path and must not trigger PostgreSQL compatibility refreshes.

## Lifecycle

Compatibility SQLite files are disposable worker-local artifacts.

They may be removed when:

* The worker exits.
* The runtime Set is released.
* The temporary directory is cleaned.
* A stale snapshot is rebuilt.

No persistent code may rely on one of these files existing after the worker finishes.

The persistent PostgreSQL data must always be sufficient to reconstruct the snapshot again.

Each protocol worker must attempt to remove only its own `worker-<PID>` compatibility directory after closing its project and runtime mappers. This cleanup must run after successful execution, failed execution, and normal exception handling.

Cleanup must never remove another worker's directory. A cleanup failure must be logged but must not replace the protocol's actual execution result.

Abrupt process termination such as `SIGKILL`, host failure, or power loss cannot execute Python finalizers and may leave stale worker directories. Those stale directories remain disposable and may be removed later by operating-system temporary-directory cleanup or a dedicated stale-worker scavenger.

## Required regression tests

Changes to PostgreSQL runtime Sets, materialization, `Set.load()`, `getFileName()`, streaming, or output restoration must preserve tests for all of the following:

1. PostgreSQL remains the active runtime mapper.
2. `getFileName()` creates a readable temporary SQLite snapshot.
3. No compatibility SQLite is created inside the project.
4. The same consumer keeps a stable compatibility path.
5. An unchanged PostgreSQL revision does not rebuild the snapshot.
6. A changed PostgreSQL revision rebuilds the same path.
7. Newly persisted streaming items appear after refresh.
8. `STREAM_CLOSED` appears after the producer closes.
9. Stable item cursors prevent duplicate processing after rebuilds.
10. Different workers cannot share a compatibility SQLite path.
11. Ordinary SQLite Sets are not intercepted.
12. Recursive materialization fails without hanging.
13. Materialization does not mutate or persist parent protocols or parent outputs.
14. Heterogeneous item schemas remain readable after materialization.
15. Set-level properties required by native Scipion code are available in the detached runtime Set.
16. Native nested Set loads triggered by snapshot construction bypass managed-path refresh without disabling real recursive-materialization detection.
17. Worker finalization removes only the current worker's SQLite snapshots after closing mappers, on both successful and failed protocol execution.
18. Detached consumer input graphs remain transitively read-only through nested Sets, Set-valued pointers, and further clones.
19. Structured pointers inside generic PostgreSQL runtime inputs resolve and refresh through the same consumer-owned detached target resolver without restoring canonical parent protocol access; the transient resolver is removed when the consumer input lifecycle ends.
20. Generic PostgreSQL runtime object hydration and `updateFrom()` preserve `_objParentId` without introducing strong `_objParent` cycles and remain safe for native recursive copy operations.
21. Normal PostgreSQL mapper reads restore structured generic-object pointers through read-only PostgreSQL references, while consumer runtime reads keep using their separate detached resolvers; recursive pointer graphs fail without unbounded recursion.
22. Generic PostgreSQL object-tree persistence distinguishes recursive cycles from shared object references: cycles are cut, while the same Scipion object reused at multiple valid paths is persisted at every path using that path's canonical `scipionObjId`; output identity preparation and object-tree storage must use the same path-to-id mapping, including legacy Sets that fall back to detached object-tree persistence when their backing artifact is missing.
23. Temporary canonical `scipionObjId` and parent-id preparation for PostgreSQL output persistence is transactional with respect to the in-memory Scipion object tree: successful persistence restores the original runtime identity afterward, and partial preparation failures restore every object already modified before propagating the error.
24. Structured PostgreSQL pointers to direct outputs and Set items preserve semantic owner identity in addition to raw runtime ids: legacy in-memory output ids may be restored after persistence, but pointer hydration resolves the canonical PostgreSQL output through its owning protocol and output name before resolving a Set item by `scipionItemId`.
25. Structured Pointer serialization uses the same semantic reference contract for generic object trees and PostgreSQL Set item values, including PointerList entries; detached PostgreSQL runtime parents are discovered through their weak runtime parent references without restoring strong `_objParent` links.
26. PostgreSQL Set-item Pointer hydration consumes the same semantic owner identity persisted by generic and Set serializers: when a raw parent Set id is legacy or unavailable, the runtime Set factory resolves the canonical PostgreSQL Set through the owning protocol id and output name, then resolves the target by `scipionItemId`; pointer caches are keyed by the canonical PostgreSQL Set id.
27. Structured PostgreSQL Pointer owner identity is authoritative when semantic protocol/output identity is available: protocol id plus output name is resolved before any raw runtime object id, and raw ids remain compatibility fallbacks only for references that cannot be resolved semantically; this prevents restored legacy ids that collide with valid PostgreSQL runtime ids from binding Pointers to the wrong output or Set item.
28. PostgreSQL object-tree persistence errors are never interpreted as mapper-signature compatibility failures: `storeObjectTree()` is invoked once with the canonical runtime persistence contract, and internal `TypeError` exceptions propagate through normal output-persistence error handling without retrying or partially replaying the tree write.
29. Runtime paths that already possess a Scipion protocol id obtained from a Scipion runtime protocol must resolve it exclusively through `protocols.protocolId`; they must never reinterpret that known Scipion id as `protocols.id`. The dual-namespace protocol resolver remains valid only at boundaries that genuinely accept either PostgreSQL database ids or Scipion runtime protocol ids.
30. PostgreSQL object-tree persistence must never interpret failure to enumerate `getAttributesToStore()` as an empty object tree. Attribute-enumeration errors must propagate and abort the persistence transaction before stale object-tree paths are deleted, preventing transient serialization failures from deleting previously valid persisted children.
31. PostgreSQL `updateFrom()` refreshes must be transactional with respect to the in-memory runtime object. Snapshot capture failures must abort the refresh before mutation, and any failed or incomplete generic-object refresh must restore the previous object identity, metadata and mutable nested values instead of leaving partially refreshed consumer state.
32. Once PostgreSQL `updateFrom()` has identified a supported generic runtime object and found its persisted PostgreSQL representation, refresh failure is an execution error rather than an unsupported-object condition. The previous in-memory state must be restored and the refresh error must propagate; it must never fall through to the generic `NotImplementedError` path.
33. PostgreSQL `updateFrom()` rollback failures must never be swallowed. If restoring any captured mutable runtime value fails, the mapper must raise an explicit rollback error preserving the underlying restoration exception, because the in-memory object can no longer be considered transactionally restored.
34. PostgreSQL `updateFrom()` snapshot capture must never reinterpret a `TypeError` raised by a Scipion object's `get()` implementation as a getter-signature compatibility failure. Runtime values are read through the standard zero-argument `get()` contract exactly once, and any getter failure must propagate before refresh mutation begins.
35. Once a PostgreSQL generic runtime refresh is operating on a supported object, exceptions raised while applying the stored value or enumerating the stored object's attributes are refresh failures and must propagate with their original exception identity after rollback. They must never be collapsed into a boolean `False` result that replaces the root cause with a generic refresh error.
36. Temporary canonical output-identity preparation must never interpret failure to enumerate a runtime object's persisted attributes as the end of the object tree. Attribute-enumeration failures must abort preparation, restore every temporary `scipionObjId` and parent id already modified, and propagate the original error instead of returning a partially prepared path-to-id mapping.
37. Temporary canonical output-identity restoration must attempt every captured object id and parent id even when one restoration operation fails. A restoration failure must propagate explicitly with its underlying cause after all remaining snapshot values have been attempted; one broken runtime setter must never leave unrelated objects carrying temporary canonical persistence identities.
38. Temporary canonical output-identity preparation must capture each runtime object's original object id and parent id strictly before allocating or assigning canonical persistence identities. If an available `getObjId()` or `getObjParentId()` fails, the error must propagate before mutation; best-effort identity reads must never fabricate rollback state such as `None` or fallback ids.
39. PostgreSQL reset validation must determine every candidate protocol's runtime status successfully before any stop, output cleanup, input-ref cleanup, working-directory cleanup or protocol reset mutation occurs. A status-read failure must be reported as a validation error; it must never be converted into an empty or unknown status that could allow an active worker to bypass the stop barrier.

## Historical failure mode

Before PostgreSQL became authoritative, a streaming consumer could retain the filename of the producer's persistent SQLite database and observe new items because the producer continued writing to that same file.

After removing persistent SQLite output storage, `getFileName()` returned a point-in-time compatibility snapshot instead.

Legacy protocols that cached the filename continued reopening the same unchanged snapshot and therefore stopped seeing newly persisted PostgreSQL items.

The correct solution is not to restore a shared persistent SQLite database.

The correct solution is:

```text
shared concurrent PostgreSQL storage
+
one refreshable temporary SQLite snapshot per consumer worker
```

Any cleanup that removes revision-aware refresh, worker isolation, stable paths, or stable streaming cursors will reintroduce this failure.
