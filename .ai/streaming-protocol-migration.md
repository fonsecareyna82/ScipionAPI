# MASTER GUIDE TO MIGRATING, AUDITING, HARDENING AND OPTIMIZING STREAMING PROTOCOLS IN SCIPION

## 0. OVERALL OBJECTIVE

We are systematically migrating legacy Scipion/Xmipp streaming protocols to a modern, robust, resumable, incremental, efficient model that is completely agnostic to persistence.

The objective is NOT merely to make a protocol “work in streaming mode”.

We want every protocol to reach this standard:

> A transactionally robust, resumable, idempotent, incremental, efficient, portable streaming protocol that withstands interruptions and can correctly reconstruct its state using only durable information.

The same plugin implementation must work unchanged across the supported Scipion configurations.

The process must address all of the following together:

- migration to modern streaming;
- scientific correctness;
- durable persistence;
- Continue/Resume;
- ambiguous publication;
- idempotence;
- correct closure;
- worker failures;
- persistence failures;
- terminal reconciliation;
- late-visible IDs;
- polling optimization;
- elimination of historical rescans;
- multiple streaming inputs;
- safe cleanup;
- compatibility with existing projects;
- deterministic RED/GREEN tests;
- full regression coverage;
- independence from internal storage details.

The final objective is to leave no relevant weak spots in the protocol.

## 1. WORKING CONTEXT AND DIRECTORIES

Main local repositories:

Classic Scipion:

    /home/yunior/Yunior/Projects/Scipion/scipion-em/

ScipionWeb core:

    /home/yunior/Yunior/Projects/ScipionWeb/scipion/scipion-em/

Plugins:

    /home/yunior/Yunior/Projects/Plugins/

Current example plugin:

    /home/yunior/Yunior/Projects/Plugins/scipion-em-xmipp

Usual Scipion environment:

    /home/yunior/miniconda3/envs/scipion3

Observed version:

    Scipion v3.8.3 - Eugenius

When working on a plugin:

    cd /home/yunior/Yunior/Projects/Plugins/<plugin>

All patches delivered to the user must be downloadable Python scripts in:

    /mnt/data/

The user normally downloads them to:

    /home/yunior/Downloads/

And runs them from the root of the corresponding repository:

    python3 /home/yunior/Downloads/<patch>.py

## 2. ABSOLUTE RULES FOR PATCHES

Patches must ALWAYS be delivered as scripts:

    .py

NOT:

    .patch
    .diff

Example:

    01_add_protocol_late_visible_RED.py
    02_fix_protocol_late_visible_GREEN.py

Scripts must:

- modify only the necessary files;
- run from the repository root;
- use paths relative to the repository;
- be deterministic;
- verify that they find exactly the code they expect;
- abort without writing if the context does not match;
- validate syntax when modifying Python;
- create no backups;
- create no auxiliary files inside the repository;
- leave no `.bak`, `.orig`, copies or junk;
- avoid reformatting entire files;
- leave unrelated code untouched;
- make no commits;
- clearly report which file they modified.

Recommended pattern:

    TARGET = Path("xmipp3/protocols/protocol_xxx.py")

    if not TARGET.exists():
        raise SystemExit(...)

Where reasonable, use:

    ast.parse(source)

before the change and:

    ast.parse(result)

before writing.

If the script cannot apply the change safely:

    No changes applied.

It is better for the patch to fail than to make an incorrect modification.

## 3. PATCH NAMING

Use incremental numbering per protocol/thread.

Example:

    01_add_extract_particles_missing_pos_RED.py
    02_fix_extract_particles_missing_pos_GREEN.py
    03_add_extract_particles_missing_xmd_RED.py
    04_fix_extract_particles_missing_xmd_GREEN.py

If the patch itself needs correction:

    04v2_fix_...
    04v3_fix_...

Do not silently reuse the same name when the content has changed significantly.

## 4. WORKING METHOD: ONE CONTRACT AT A TIME

ALWAYS follow:

    EVIDENCE
        ↓
    RED
        ↓
    CONFIRM RED
        ↓
    MINIMAL GREEN
        ↓
    FOCUSED TEST
        ↓
    REGRESSION
        ↓
    FUNCTIONAL TEST
        ↓
    NEXT CONTRACT

Never fix five conceptually different things in the same patch.

A patch must answer one specific question.

Example:

    “Can a micrograph with a missing .pos file end up FINISHED?”

RED.

Then:

    “It must fail explicitly.”

GREEN.

Then continue.

## 5. DO NOT ASSUME THE BUG: PROVE IT

Before modifying production code:

1. Study the code.
2. Reconstruct the state machine.
3. Identify a concrete risk.
4. Write a deterministic RED test.
5. Run the test.
6. Verify that it fails for the expected reason.

Do not accept a harness failure as RED.

Example:

    AttributeError: fake missing method

This is NOT the contract's RED failure.

First complete the harness until the test reaches the actual behavior we want to demonstrate.

## 6. DO NOT MODIFY PRODUCTION CODE TO FIX A HARNESS

If a fake-based test fails because it lacks:

    getBoxScale()
    error()
    loadAllProperties()
    getAcquisition()
    etc.

complete the harness.

Do not modify production code to accommodate an incomplete fake.

## 7. CODING STYLE

Strong user preference:

DO NOT split code across several lines when it fits comfortably on one.

Simple assignments, calls, conditions and expressions should remain on one line whenever they are still readable.

PREFERRED:

    self.classificationRound = max(self.classificationRound, finishedRounds + 1)

NOT:

    self.classificationRound = max(
        self.classificationRound,
        finishedRounds + 1
    )

PREFERRED:

    particles = self._loadLogicalSetItemsByIds(inputSet, particleIds)

NOT:

    particles = self._loadLogicalSetItemsByIds(
        inputSet,
        particleIds,
    )

The same applies to:

- calls;
- small lists;
- arguments;
- conditions;
- assignments;
- simple comprehensions.

Do not follow PEP8 dogmatically when it makes the code harder to read.

Do not introduce large-scale automatic formatting.

Do not perform unnecessary cosmetic refactoring during functional fixes.

## 8. COMMENTS

Comments should explain:

    WHY

more than:

    WHAT

Useful example:

    # Durable ids beyond the completed watermark prove that one
    # additional serialized publication round committed.

Avoid obvious comments.

Very important:

In production code and tests, DO NOT introduce comments or names that depend on a specific persistence implementation.

Use terms such as:

    logical Set
    durable state
    persisted output
    Set implementation
    portable query
    storage-independent behavior

Do not explicitly reference specific backends in plugin comments/tests.

The implementation must be conceptually agnostic.

## 9. CYS

When the user writes:

    cys
    cys!!!
    cys!!!!

it means they have already committed/synced, and we must acknowledge/refresh the current repository state.

DO NOT respond by suggesting a commit.

DO NOT continue blindly relying on an earlier diff.

Reread/refresh the code when necessary.

## 10. TESTS: ALWAYS PROVIDE THE EXACT COMMAND

After every patch, provide the exact command.

Example:

    scipion3 test xmipp3.tests.test_protocol_extract_particles_streaming_regression.TestXmippExtractParticlesStreamingRegression.testRetrySkipsParticlesAlreadyDurableInOutput

Once the contract is complete:

    scipion3 test xmipp3.tests.test_protocol_extract_particles_streaming_regression

Then:

    scipion3 test xmipp3.tests.test_protocols_xmipp_mics.TestXmippExtractParticles

or the corresponding functional suite.

Never merely say:

    “run the tests”.

Provide the full command.

## 11. TEST HIERARCHY

Order:

1. Focused test.
2. New regression module.
3. Original functional test.
4. Protocol test class/suite.
5. Larger suites where appropriate.

Do not run enormous suites after every tiny patch.

First complete the local contract.

## 12. CENTRAL PHILOSOPHY: DURABLE STATE IS THE AUTHORITY

Fundamental rule:

    DURABLE STATE > VOLATILE STATE

Never assume:

    step FINISHED == durable output

Never assume:

    step FAILED == output not persisted

The following can happen:

    scientific work finishes
        ↓
    output is written
        ↓
    commit occurs
        ↓
    relation/state/protocol update fails
        ↓
    step FAILED

The output may be fully durable.

Therefore:

    persisted output
    persisted IDs
    persisted relations
    persisted properties

are stronger authorities than the process's volatile state.

## 13. DISTINGUISH ITEM PHASES

A streaming item can pass through:

    discovered
    pending
    scheduled
    worker running
    scientific artifact produced
    worker finished
    publication pending
    durable
    acknowledged

Do not confuse:

    worker finished

with:

    item durable

## 14. EVERY ITEM MUST END IN A DEFINED STATE

Every discovered/dequeued item must end in exactly one of these states:

- durable;
- consumed;
- requeued;
- pending;
- released;
- intentionally discarded;
- explicitly failed.

It must never accidentally disappear.

## 15. MIGRATION TO MODERN STREAMING

Where appropriate, use:

    ProtStreamingBase

and, for Xmipp:

    XmippStreamingBase

General pattern:

    class Protocol(
        XmippStreamingBase,
        ProtStreamingBase,
        ...
    ):

A modern protocol usually implements:

    _prepareStreamingGenerator()
    stepsGeneratorStep()
    _checkNewInput()
    _checkNewOutput()

The generator must be resumable and check for global failures.

Conceptual pattern:

    self._prepareStreamingGenerator()

    while not self.finished:
        if self._streamingMustStop():
            break

        self._checkNewInput()
        self._checkNewOutput()

        if self.finished:
            break

        self._streamingSleepOnWait()

## 16. HANG WHEN A WORKER FAILS

Classic risk:

    worker FAILED
    executor starts stopping
    generator keeps polling
    executor tries to join the generator
    generator never terminates

Result:

    protocol remains RUNNING forever.

The generator must detect:

    protocol failed
    worker failure
    executor stopping

through the appropriate shared helper, for example:

    _streamingMustStop()

and exit.

## 17. INCREMENTAL HOT PATH

Normal polling must not traverse the entire history.

BAD:

    for item in inputSet:
        if item not in seen:
            ...

on every poll.

For large streams, this produces an approximately quadratic cumulative cost.

Modern pattern:

    watermark
    +
    pending IDs

## 18. WATERMARK

The watermark represents:

    highest ID discovered by the hot path

Example:

    newIds = getUniqueValues(
        'id',
        where='id > %d' % watermark
    )

Then:

    watermark = max(newIds)

However:

    watermark != durable authority
    watermark != processed item collection
    watermark != complete item collection

## 19. PENDING IDS

The watermark and pending state serve different purposes.

Watermark:

    avoids historical rescans

Pending:

    retains discovered items that have not yet been consumed

Pattern:

    newIds, watermark = discoverAfter(inputSet, watermark)

    pendingIds.update(newIds)

    candidates = loadItemsByIds(inputSet, pendingIds)

When an item is actually scheduled/consumed/durable:

    pendingIds.difference_update(consumedIds)

Do not remove it merely because it has been discovered.

## 20. DISCOVERY HELPER

Reusable pattern:

    _discoverIdsAfter(inputSet, lastId)

Ideally:

    getUniqueValues('id', where='id > watermark')

With a logical fallback when the implementation does not support the filter.

Conceptual example:

    try:
        filtered query
    except NotImplementedError:
        allIds = getUniqueValues('id')
        ids = [id for id in allIds if id > watermark]

## 21. LATE-VISIBLE IDS

A watermark alone is insufficient.

Case:

    visible: 1, 3
    watermark = 3

Later, this appears:

    2

The hot path:

    id > 3

will never see ID 2.

This problem has already appeared in several protocols and must be treated as a cross-cutting concern.

## 22. TERMINAL RECONCILIATION

The correct solution is not a full scan on every poll.

HOT PATH:

    IDs > watermark

TERMINAL PATH:

    when the producer closes,
    perform exact reconciliation.

Pattern:

    expectedSize = inputSet.getSize()

    known = durable ∪ pending ∪ scheduled ∪ discovered

    if len(known) < expectedSize:
        allVisibleIds = getUniqueValues('id')
        missingIds = allVisibleIds - known

Only at closure is the cost of a global scan allowed.

## 23. PRODUCER CLOSED != TERMINAL CONSISTENT

Never equate:

    inputSet.isStreamClosed()

with:

    the consumer has seen everything

Separate:

    producerClosed
    terminalConsistent

The output/protocol must close only when the terminal view is consistent.

## 24. PERMANENT TERMINAL INCONSISTENCY

Case:

    producerClosed = True
    getSize() = 100
    consumer sees only 99
    situation never changes

Without protection:

    protocol remains RUNNING forever.

Introduce a progress guard.

Example signature:

    (
        expectedSize,
        len(knownIds),
        watermark
    )

If it repeats for too long without progress:

    RuntimeError

## 25. DO NOT AGE THE TERMINAL STALL WHILE WORK IS ACTIVE

If there is:

    an active worker
    active publication
    active classification
    an in-flight batch

that also counts as progress.

Do not trigger terminal inconsistency merely because the input Set has not changed during a long computation.

While legitimate work is active:

    reset/pause stall counter

## 26. AMBIGUOUS PUBLICATION

Risk:

    outputSet.write()
    commit
    failure afterward

The next Continue/retry may assume the item was not published.

Every streaming publication must be:

    IDEMPOTENT

## 27. IDEMPOTENCE THROUGH DURABLE IDS

Before appending:

    durableIds = outputSet.getIdSet()

And:

    if itemId in durableIds:
        skip

The output's logical identity must be stable whenever possible.

Extract Particles example:

    particle.objId = coordinate.objId

This enables natural recovery after ambiguous publication.

## 28. DURABLE ID CACHES

To avoid:

    outputSet.getIdSet()

on every poll over enormous outputs, maintain caches such as:

    _outputIds
    _outputMicIds
    _persistedOutputIds

However:

    cache != authority

The cache must be reconstructible from durable output after Continue.

## 29. DO NOT CONSUME STATE BEFORE COMMIT

Never perform:

    del pending[item]
    del coordDict[item]
    remove temp
    mark consumed

before confirming durable publication.

If publication fails:

    retry state must remain available.

## 30. CLEANUP

Perform cleanup only after safe consumption.

Do not delete these prematurely:

- stacks;
- metadata;
- coordinates;
- reference;
- temporary scientific output;
- reconstructed batch;
- intermediate artifacts.

Especially when:

    science succeeds
    publication fails

Artifacts must be retained for retry/debugging.

## 31. REQUIRED ARTIFACTS

If a worker should produce:

    .pos
    .xmd
    .mrcs
    reference
    metadata
    stack

and it does not exist:

    RuntimeError

Do not turn a missing artifact into a warning followed by success.

## 32. EMPTY RESULT VS MISSING RESULT

Distinguish:

    artifact exists but has zero enabled items

from:

    artifact missing

The former may be scientifically valid.

The latter is normally an error/inconsistency.

## 33. SCIENTIFIC EXCEPTIONS

Never swallow failures from:

    runJob()
    conversion
    extraction
    classification
    normalization
    metadata parsing

by default.

Incorrect pattern:

    try:
        runJob(...)
    except:
        print(...)
        continue

Unless there is an explicit scientific decision to tolerate that item's failure.

## 34. SELF.ERROR() DOES NOT PROPAGATE AN EXCEPTION

Dangerous pattern:

    except Exception as e:
        self.error(...)
        # no raise

This turns failure into success.

If the operation must fail:

    except Exception:
        self.error(...)
        raise

## 35. PER-ITEM FAILURE POLICY

Before allowing:

    skip corrupted item

explicitly decide whether the protocol scientifically permits that behavior.

Do not assume that “streaming must keep going”.

In many cases:

    corrupt worker → protocol FAILED

is more correct than silently losing data.

## 36. DYNAMIC STEPS: PERSISTABLE ARGUMENTS ONLY

Avoid passing live Python Set objects to `_insertFunctionStep`.

BAD:

    _insertFunctionStep(worker, particleSet)

Because `FunctionStep.argsStr` may be unable to serialize the object.

BETTER:

    batchIds = [item.getObjId() for item in batch]

    _insertFunctionStep(worker, batchIds)

## 37. THE WORKER RECONSTRUCTS THE BATCH BY IDS

The step receives:

    IDs

and reconstructs objects from the logical Set.

Then it checks:

    requestedIds == loadedIds

If any are missing:

    RuntimeError

Do not run scientific work on incomplete batches.

## 38. EXACT BATCH

If the input grows during a computation, DO NOT compare metadata against the entire current input.

Compare it against:

    exact batch IDs

The batch is the contractual unit.

## 39. INCOMPLETE METADATA

If an expected item lacks metadata:

    RuntimeError

Do not use:

    _appendItem = False
    skip
    continue

if that would silently lose the item.

## 40. EXHAUSTED ITERATORS

Watch for APIs that internally do:

    try:
        row = next(iterator)
    except StopIteration:
        break

This can silently truncate output.

When metadata has an expected cardinality:

    explicitly validate every ID.

## 41. MULTIPLE INPUT STREAMS

Protocols may depend on:

    coordinates
    mics
    CTFs
    alternate mics
    models
    references
    other streams

Each input may need its own:

    watermark
    pending
    closed state
    terminal reconciliation

## 42. JOINS BETWEEN INPUTS

Example:

    mic visible
    CTF not yet visible
    alternate mic not yet visible

Do not lose the micrograph.

It must remain pending until all dependencies are available.

## 43. DO NOT RESCAN THE ENTIRE JOIN

Avoid:

    for each mic:
        scan all CTFs

Use:

    pending IDs
    indexed lookup
    lookup by ID/name
    batch lookup

## 44. BULK LOAD VS INDEXED LOAD

For a small number of candidates:

    targeted lookup

For many candidates:

    a single bulk scan may be better.

Pattern:

    if candidateCount >= threshold and candidateCount >= fraction * total:
        bulk
    else:
        indexed lookup

This is a legitimate optimization.

## 45. POLLING COST

While the stream is open:

    cost per poll ≈ new items + actual pending items

NOT:

    total historical size

Audit any use of:

    for item in wholeSet
    getUniqueValues over enormous columns
    getIdSet()
    rebuild dictionaries
    repeated getSize + global scan

## 46. STREAM CLOSED

Separate:

    producer closed
    all discovered
    all dependencies resolved
    all scheduled
    workers finished
    outputs durable
    terminal consistent
    output closed

Do not compress everything into a single ambiguous boolean.

## 47. OUTPUT CLOSURE

Ensure that:

    STREAM_OPEN → STREAM_CLOSED

works for:

- the last full batch;
- the last partial batch;
- an empty stream;
- no new items in the last poll;
- the last output already published before closure is detected.

## 48. FULL PENDING BATCH

Classic case:

    batch full
    worker busy
    next poll
    remaining = 0

Never issue queries where:

    limit=0

could have ambiguous semantics.

If a batch is already full and the worker becomes available:

    it must launch even without new input items.

## 49. RESUME / CONTINUE

Analyze every variable that represents historical state:

    what happens if the process is destroyed?

Examples:

    classificationStarted
    firstTimeDone
    classificationRound
    seenIds
    pendingIds
    outputIds cache
    watermark
    actual class count
    scientific reference

## 50. VOLATILE VS DURABLE

For each attribute, ask:

    is it a cache?
    is it active state?
    is it history?
    can it be reconstructed?

If it represents history:

    it must be reconstructed from durable state.

## 51. RESTART VS RESUME

Do not confuse:

    MODE_RESTART

with:

    MODE_RESUME

Restart must not automatically recover historical state from the previous run in a way that continues its old processing.

## 52. HISTORICAL STEPS

Persisted steps may be inspected for Continue.

However:

    step state != durable output authority

Steps help reconstruct:

- which IDs were scheduled;
- which workers finished;
- which batch IDs belonged to each step;
- which rounds existed.

Combine this information with durable output.

## 53. LEGACY STEPS

Old projects may lack:

    batchIds
    new metadata
    new arguments

Design an explicit fallback.

Do not assume that every project was created using the new code.

## 54. EVOLVING SCIENTIFIC STATE

Some protocols maintain:

    model
    reference
    classes
    weights
    round

If durable evidence shows that scientific work ran using evolved state, but the required artifact is missing:

    fail explicitly

Do not silently reconstruct from an incorrect initial state.

## 55. SOURCE RELATIONS

These can also suffer from ambiguous commits.

Case:

    output durable
    defineSourceRelation fails

On retry:

    the relation must be repairable.

Implement:

    ensure relation

idempotently where necessary.

## 56. MARKER FILES

Legacy markers such as:

    mic_XXXXXX.TXT
    DONE/all.TXT

must not be the main authority for progress.

They may remain as legacy hints.

Prefer:

    persisted steps
    durable output IDs
    logical state

## 57. THE FILESYSTEM IS NOT LOGICAL STATE

Do not use a physical path as a Set's identity.

Avoid reconstruction such as:

    SetClass(filename=inputSet.getFileName())

when there is a way to work with:

    Pointer
    logical Set
    loadAllProperties()

A Set's logical identity matters more than how it is persisted.

## 58. BACKEND AGNOSTIC

There must be no:

- direct SQL;
- direct table queries;
- backend-specific branches;
- different logic depending on deployment;
- dependence on `.sqlite` as a logical identity.

Use Scipion APIs.

The implementation must be exactly the same.

## 59. WHERE FILTERS

Filters such as:

    where='id > ...'
    where='id IN (...)'

may be used as an optimization through the public Set API if a portable fallback exists.

Do not turn them into a hard backend dependency.

## 60. LOADING BY IDS

Use logical helpers such as:

    _loadLogicalSetItemsByIds()

But always review:

- batching;
- fallback;
- cloning;
- acquisition hydration;
- missing IDs;
- duplicate IDs.

## 61. DO NOT CREATE ENORMOUS IN QUERIES

Use batches of, for example:

    500

Do not create a query containing tens of thousands of IDs.

## 62. OUTPUT IDENTITY

Always identify:

    which logical ID can the output use?

Prefer an ID derived from durable input.

This facilitates:

- idempotence;
- Resume;
- ambiguous commit recovery;
- duplicate prevention.

## 63. FIRST PUBLICATION

First publication often follows different paths:

    output does not exist
    create Set
    define output
    define relations

It must be audited separately.

An ambiguous commit during first publication may be more dangerous than during subsequent appends.

## 64. EMPTY TERMINAL STREAM

A protocol must finish correctly if the input:

    closes without producing items

It must not remain RUNNING while waiting for something that will never arrive.

## 65. SCIENTIFIC WORK != PUBLICATION

Explicitly treat:

    scientific artifact generated
    durable output published

as two separate conceptual commits.

## 66. RETRY ARTIFACTS

If scientific work has already finished but publication failed, prefer reusing existing scientific artifacts over repeating expensive work, when safe.

## 67. TEMPORARY WORKSPACES

Never unsafely reuse the same temporary path across concurrent workers.

Where necessary, use:

    item-scoped paths

Conceptual example:

    <itemId>__basename

## 68. BASENAME COLLISIONS

Two files can share a basename:

    /a/mic001.mrc
    /b/mic001.mrc

Artifacts derived only from the basename may collide.

Prefer:

    item ID + basename

## 69. THREAD SAFETY

When several workers may touch:

    same metadata
    same stack
    same reference
    same temp path
    same output

audit for race conditions.

## 70. BATCH SERIALIZATION

If the protocol serializes rounds/batches by design, that property may be used to infer an ambiguous commit:

    at most one publication in flight

But document and test it.

## 71. OUTPUT PERFORMANCE

Do not run:

    output.getUniqueValues(...)
    output.getIdSet()

on every poll if an incremental cache can be maintained.

Initialize the cache once and update it after durable publication.

## 72. COORDINATE PERFORMANCE

In protocols with coordinates, avoid scanning all coordinates for every micrograph.

Use lookup by micrograph when there are few candidates.

Use a bulk scan only when the candidate count makes a global pass more efficient.

## 73. PROGRESS AND SLEEP

If there is no new work:

    sleep

But do not sleep unnecessarily when:

    pending batch ready
    worker became available
    terminal reconciliation needed
    publication retry pending

## 74. DO NOT RELY ON MTIME AS THE ONLY TRUTH

Input change detection based on:

    os.path.getmtime

may serve as an optimization.

But it must not be the only way to detect logical state in a portable architecture.

## 75. PARTIALLY PERSISTED OUTPUT

Explicitly simulate cases such as:

    append first half
    persistence succeeds
    exception after commit

Retry must converge to the same correct state.

## 76. PRACTICAL EXACTLY-ONCE SEMANTICS

We do not necessarily need a perfect distributed transaction.

We seek:

    at-least-once execution
    +
    idempotent publication
    =
    effectively exactly-once durable result

## 77. EXCEPT AUDIT

Search for:

    except:
    except Exception:
    self.error()
    warning()
    continue

Review every occurrence.

Ask:

    could this error cause data loss?

## 78. CLEANPATH AUDIT

Search for:

    cleanPath
    cleanPattern
    remove
    unlink
    rmtree

Ask:

    has the artifact already been durably consumed?

## 79. DEL AUDIT

Search for:

    del self.cache[id]
    pop()
    difference_update()

Ask:

    does this happen before or after the durable commit?

## 80. FIRST-TIME FLAG AUDIT

Search for:

    firstTime
    firstTimeDone
    started
    classificationStarted
    outputCreated

Ask:

    how is this reconstructed after Continue?

## 81. COUNTER AUDIT

Search for:

    round
    batch
    generation
    iteration
    index

Ask:

    could this be reused after an ambiguous commit?

## 82. REFERENCE AUDIT

Look for evolved scientific artifacts.

Ask:

    can they be reconstructed?
    must they exist after Resume?
    what happens if they are missing?

## 83. SET CLOSE() AUDIT

Every logical Set opened temporarily must be closed correctly.

Pattern:

    set = load()
    try:
        ...
    finally:
        set.close()

## 84. DO NOT CLOSE OBJECTS THAT OTHER CODE NEEDS

Ensure that closing a Set view does not improperly invalidate a shared object.

Use the framework's logical contract.

## 85. RECONSTRUCT ACQUISITION

When loading items individually by ID, they may need hydration from Set properties.

Review:

    magnification
    voltage
    spherical aberration
    amplitude contrast

if the items do not carry complete values.

## 86. CHECK LOADED IDS

After:

    loadItemsByIds(requestedIds)

compare:

    loadedIds
    requestedIds

Especially before scientific work.

## 87. OUTPUT SET REUSE

Be careful with:

    enableAppend()

on reconstructed Sets.

Some Set types have special mapper/schema logic.

Do not call apparently harmless methods without reviewing how that Set type prepares its items internally.

## 88. REGRESSION TESTS

Create a dedicated module per protocol when hardening is significant.

Example:

    xmipp3/tests/test_protocol_extract_particles_streaming_regression.py

It must contain small, deterministic, contract-focused tests.

## 89. EXISTING FUNCTIONAL TESTS

Never replace functional tests with unit harnesses.

New tests protect invariants.

Original tests protect real behavior.

## 90. DO NOT OVERMOCK

Mocks must reach the actual contract.

If the harness replicates too much production code, the test loses value.

## 91. AUDIT THE ACTUAL BRANCH

The remote may lag behind the local checkout.

The user's results and the current local code are authoritative.

When a local function already exists but the remote does not show it:

    do not assume it does not exist.

Refresh the state.

## 92. DO NOT TOUCH CORE TOO EARLY

First demonstrate the problem in the protocol/plugin.

Move a fix to core only when:

- the pattern is truly cross-cutting;
- the abstraction is clean;
- there is evidence;
- it does not force unwanted behavior on other plugins.

Avoid unnecessarily turning a plugin audit into a massive core overhaul.

## 93. WHEN TO GENERALIZE INTO CORE

A shared helper belongs in core/a base class when the following clearly recur:

- logical Set loading;
- ID discovery;
- terminal reconciliation;
- durable output IDs;
- resume reconstruction;
- pending state;
- finished step recovery.

Prefer shared infrastructure when it removes real duplication.

## 94. SHARED HELPER TESTS

If shared behavior is moved into:

    XmippStreamingBase

also test the helper in isolation.

Then retain the protocol test that demonstrates correct use.

## 95. LATE-VISIBLE ID TESTS

Minimal pattern:

    initially visible: 1, 3
    watermark: 3
    appears: 2
    producer closes

It must eventually discover:

    {1,2,3}

without duplicates.

## 96. AMBIGUOUS COMMIT TESTS

Pattern:

    durable output contains item
    publication step historically failed

Retry:

    no duplicate append

## 97. RETRY STATE TESTS

Trigger:

    publication error

and verify:

    pending/cache/coord state remains available

## 98. REQUIRED ARTIFACT TESTS

Remove an artifact or simulate its absence.

Expect:

    RuntimeError

Not just a warning.

## 99. SCIENTIFIC FAILURE TESTS

Mock:

    runJob raises

Verify:

    exception propagates
    artifacts are not cleaned up prematurely

## 100. TERMINAL CLOSURE TESTS

Explicitly verify:

    final output stream state == CLOSED

## 101. BUSY TERMINAL TESTS

Keep a worker active for more polls than the terminal stall limit.

The protocol must not fail for terminal inconsistency while the worker is working.

## 102. LEGACY CONTINUE TESTS

When historical formats exist, simulate old persisted steps.

Verify the fallback.

## 103. EMPTY STREAM TESTS

Closed, empty input.

The protocol must finish.

## 104. DUPLICATE TESTS

Retry the same item.

The final output must contain a single logical identity.

## 105. PERFORMANCE CONTRACT TESTS

A benchmark is not necessarily required.

Tests can verify that the hot path calls:

    filtered discovery

and not:

    full iteration

during normal polling.

## 106. DO NOT OPTIMIZE BLINDLY

Before modifying performance, study which optimizations already exist.

Avoid repeating work that is already implemented.

First assess conceptually:

    what does each poll actually do?

## 107. RISK PRIORITY

Recommended order:

1. Silent data loss.
2. Duplication.
3. Incorrect Resume.
4. Infinite hang.
5. Ambiguous publication.
6. Swallowed scientific failures.
7. Missing artifacts accepted.
8. Backend coupling.
9. O(N²) performance.
10. Premature cleanup.
11. Legacy compatibility.
12. Highly theoretical cases.

## 108. DO NOT OVER-HARDEN

Do not endlessly pursue exotic cases once:

- the main contracts are covered;
- regression tests are green;
- functional tests are green;
- the architecture is coherent.

The objective is practical robustness, not impossible mathematical perfection.

## 109. CRITERIA FOR A COMPLETED PROTOCOL

A protocol can be considered complete when:

- it has migrated to modern streaming;
- the hot path is incremental;
- pending state is robust;
- late-visible reconciliation is implemented;
- Continue reconstructs durable state;
- publication is idempotent;
- scientific failures propagate;
- required artifacts are validated;
- state is not consumed prematurely;
- cleanup is not premature;
- terminal closure is tested;
- it cannot remain RUNNING indefinitely;
- multiple inputs are reconciled;
- relations are recoverable where applicable;
- it is backend independent;
- the regression module is green;
- functional tests are green;
- the original suite is green.

## 110. FINAL DIFF CHECK

Before committing:

    git diff --check

Then:

    git diff -- <production files> <test files>

Look for:

- debug leftovers;
- accidental formatting;
- incorrect comments;
- dead code;
- backups;
- storage-specific wording;
- unused imports.

## 111. SEARCH FOR PROHIBITED TERMS IN PLUGIN CODE

Where appropriate, check:

    grep -Ein 'sqlite|postgres(ql)?|scipionweb|classic' <files>

Ideally, this should return nothing in code/comments/tests related to portable contracts.

## 112. COMMIT

Do not commit automatically.

When the user asks for a commit name, provide a short but descriptive one.

Example:

    Harden Extract Particles streaming durability and resume recovery

or:

    Harden AlignPCA streaming resume, durability and terminal recovery

## 113. FINAL ARCHITECTURAL PATTERN

Mental model:

             LOGICAL INPUT SET
                    │
                    ▼
          incremental discovery
               watermark
                    │
                    ▼
                 pending
                    │
                    ▼
              scheduling
                    │
                    ▼
           scientific worker
                    │
                    ▼
         scientific artifacts
                    │
                    ▼
        idempotent publication
                    │
                    ▼
            durable output
                    │
                    ▼
        durable acknowledgement
                    │
                    ▼
      terminal reconciliation
                    │
                    ▼
             STREAM_CLOSED

## 114. DURABLE STATE VS OPTIMIZATION

Authority:

    durable output
    logical Sets
    persisted protocol state
    persisted step graph

Optimizations:

    watermark
    caches
    pending in memory
    mtime
    active flags

Never reverse that hierarchy.

## 115. REQUIRED QUESTIONS WHEN STARTING A NEW PROTOCOL

Before the first patch, answer:

1. Which exact protocol is involved?
2. Which base classes does it use?
3. Does it use legacy streaming or ProtStreamingBase?
4. What are its inputs?
5. Which inputs can grow?
6. Which input determines closure?
7. Does it have multiple dependencies?
8. What is each item's logical identity?
9. How does it discover new items?
10. Is there a watermark?
11. Is there pending state?
12. Does it rescan historical data?
13. How does it schedule workers?
14. Which arguments do the steps persist?
15. Which artifacts does each worker produce?
16. What is the durable output?
17. How does it prevent duplicates?
18. How does it implement Continue?
19. Which volatile state is lost?
20. How does it close?
21. How does it handle worker failures?
22. Can it remain RUNNING?
23. What cleanup does it perform?
24. Which relations does it create?
25. Which tests exist?

## 116. MANDATORY PERFORMANCE AUDIT

In addition to hardening, every protocol must be audited for performance.

Ask:

    does each poll perform work proportional to the historical data?

If so:

    optimize.

The objective is:

    O(new + pending)

while the stream is open.

Not:

    O(total historical input)

## 117. RESUME PERFORMANCE

Resume may perform a somewhat more expensive reconstruction once.

Do not transfer that cost to every poll.

Acceptable:

    full durable reconstruction once on Continue

Unacceptable:

    full reconstruction every poll

## 118. CLOSURE MAY BE MORE EXPENSIVE

Terminal reconciliation may perform:

    one global scan

because it occurs once or only a few times.

Prioritize optimizing the hot path.

## 119. DO NOT PERFORM A FULL TERMINAL SCAN PREMATURELY

Reconcile globally only when:

    producerClosed

Not because:

    “nothing appeared in two polls”

## 120. PROTOCOLS WITH BATCHING

Review:

- a full batch waiting;
- a partial batch;
- batch scheduling;
- no new item but a batch is ready;
- batch ownership;
- exact batch IDs;
- serializable step arguments.

## 121. PROTOCOLS WITH ROUNDS

Review:

- round recovery;
- ambiguously committed rounds;
- suffix/path collisions;
- evolved scientific state;
- restart vs continue.

## 122. PER-MICROGRAPH PROTOCOLS

Review:

- micrograph identity;
- coordinate mapping;
- CTF join;
- basename collisions;
- per-micrograph artifacts;
- finished extraction vs durable particles;
- skipped micrograph policy.

## 123. PER-MOVIE PROTOCOLS

Review:

- item-scoped workspace;
- finished processing step;
- durable output movie;
- late movies;
- Resume from finished steps;
- cleanup after publication.

## 124. CLASSIFICATION PROTOCOLS

Review:

- metadata cardinality;
- class count;
- reference state;
- exact batch;
- round;
- first publication;
- durable membership.

## 125. DO NOT ASSUME ID ORDERING

A batch may logically end up as:

    [1,3,2]

after terminal reconciliation.

The required guarantees are usually:

    exact IDs
    no duplicates

Not necessarily temporal ordering.

## 126. SERIALIZED SCIENCE

If only one scientific round/publication can be active at a time, document that property.

It may simplify recovery from ambiguous commits.

## 127. FAIL FAST

When an essential precondition is missing:

    fail early

before launching expensive work.

Examples:

    missing evolved reference
    incomplete reconstructed batch
    missing coordinate metadata

## 128. SCIENCE BEFORE PERSISTENCE

Never advance durable progress merely because a job was launched.

Advance it only when:

    result scientifically valid
    publication durable

## 129. PERSISTENCE FAILURE

It must be:

    retryable

when safe.

Preserve artifacts.

Do not automatically turn a persistence failure into a scientific rerun if this can be avoided.

## 130. SOURCE INPUT MUTATION

The consumer protocol must not accidentally modify input objects.

Clone where appropriate.

Especially before:

    scale coordinate
    copyObjId
    setCTF
    change acquisition

## 131. CLONES AND IDS

When cloning, verify preservation of:

    objId
    micId
    relations
    acquisition
    coordinate

## 132. OUTPUT PROPERTIES

In addition to items, check:

    sampling rate
    phase flipped flag
    hasCTF
    coordinates pointer
    stream state

Continue/publication retry must not corrupt properties.

## 133. EMPTY/MISSING RELATIONS

If durable output exists after an ambiguous first publication, ensure that its source relations can be reconstructed.

## 134. ERROR MESSAGES

New RuntimeError messages must be clear and diagnostic.

Include:

    item identity
    expected artifact
    problematic path/state

Example:

    Converted coordinates are missing for micrograph X: path

## 135. DO NOT INTRODUCE EXCESSIVE POLL LOGGING

Avoid enormous logs on every poll for large streams.

Use detailed debugging only when it adds value.

## 136. MINIMAL PATCHES

GREEN must change only what is necessary to satisfy the RED contract.

Do not use it as an opportunity to “clean up” other things.

## 137. REFACTOR AT THE END

If refactoring is desired, do it after:

    functionality green
    regression green
    suite green

And keep it separate from fixes.

## 138. REFACTORING STYLE

No large-scale formatting.

Compact code manually when necessary.

Do not split lines unnecessarily.

Do not change semantics.

## 139. WHEN RECEIVING “TEST PASSED”

Mark the contract complete.

Do not revisit the same problem unless new evidence appears.

Move to the next priority risk.

## 140. WHEN RECEIVING “TESTS AND SUITE GREEN”

Review:

- important outstanding risks;
- final diff;
- backend independence;
- performance;
- cleanup.

If nothing relevant remains:

    mark the protocol complete.

## 141. WHEN STARTING A NEW THREAD

Use this guide as operational context.

Do not ask the user to repeat:

- directories;
- methodology;
- patch format;
- style;
- backend rules;
- RED/GREEN;
- exact test commands.

Assume all of the above.

## 142. FINAL PRINCIPLE

The main question when reviewing every streaming line should be:

> If the process dies immediately after this line and I use Continue, can I reconstruct exactly what happened without losing or duplicating work?

And the performance question:

> If the stream has 100,000 items and only one new item has just arrived, does this poll work roughly on that new item, or does it traverse all 100,000 historical items again?

If either answer is bad:

    more hardening work remains.

## 143. ULTRA-SHORT METHOD SUMMARY

For each protocol:

    map state
        ↓
    migrate to modern streaming
        ↓
    incremental hot path
        ↓
    watermark + pending
        ↓
    exact logical IDs
        ↓
    scientific work
        ↓
    durable idempotent publication
        ↓
    ambiguous commit recovery
        ↓
    Continue reconstruction
        ↓
    terminal reconciliation
        ↓
    safe close
        ↓
    regression tests
        ↓
    functional suite
        ↓
    mark the protocol complete

## 144. GOLDEN RULE

DURABLE STATE IS THE AUTHORITY.

WATERMARK IS AN OPTIMIZATION.

PENDING PREVENTS LOSS.

IDEMPOTENCE PREVENTS DUPLICATES.

TERMINAL RECONCILIATION PREVENTS LATE-ITEM LOSS.

FAILURE PROPAGATION PREVENTS SILENT CORRUPTION.

INCREMENTAL POLLING PREVENTS STREAMING FROM DEGRADING WITH SCALE.

ALL OF THIS MUST WORK WITH A SINGLE LOGICAL PLUGIN IMPLEMENTATION.
