# Scipion protocol form compatibility

ScipionAPI is responsible for translating native Scipion protocol form
definitions into a representation that ScipionWeb can interpret without
losing Scipion semantics.

The source of truth is the real form hierarchy and parameter classes provided
by `scipion-pyworkflow`.

## Preserve form hierarchy

`Group` and `Line` must remain explicit in serialized protocol form
definitions.

A nested structure such as:

```text
Group
  Line
    Param
    Param
  Param
```

must never be flattened into:

```text
Group
  Param
  Param
  Param
```

Flattening a `Line` loses semantic information including:

- label;
- help;
- condition;
- expert level;
- child grouping;
- intended horizontal layout.

Nested decorators must therefore be serialized recursively.

## Preserve semantics through Python inheritance

When the web frontend needs the semantics of a Scipion base parameter class,
ScipionAPI should resolve them using Python inheritance where possible.

In particular, every object satisfying:

```python
isinstance(param, PathParam)
```

must be serialized with web `PathParam` semantics.

This includes:

- `PathParam`;
- `FileParam`;
- `FolderParam`;
- plugin-defined subclasses derived from them.

Do not require ScipionWeb to reconstruct the Python inheritance hierarchy from
individual class names.

## Conditions and protocol constants

Scipion form conditions may reference both form parameters and protocol
attributes/constants.

`scipion-pyworkflow Form._analizeCondition()` already determines the
identifiers referenced by each parameter through `_conditionParams`.

ScipionAPI should reuse this information rather than independently parsing
condition expressions.

For condition identifiers that:

- are not form parameters;
- are protocol attributes;
- can be serialized safely;

ScipionAPI exposes their current value through the serialized
`conditionContext`.

For example:

```python
condition='importFrom == IMPORT_FROM_FILES'
```

may be serialized with:

```json
{
  "condition": "importFrom == IMPORT_FROM_FILES",
  "conditionContext": {
    "IMPORT_FROM_FILES": 0
  }
}
```

Dynamic form parameter values remain owned by ScipionWeb state. Static protocol
constants and attributes required to evaluate the expression come from
`conditionContext`.

Do not evaluate arbitrary condition Python code in ScipionAPI merely to decide
frontend visibility.

## Boolean conditions

Scipion `FormElement.condition` is stored as a `String`.

Consequently Python boolean values used as conditions may reach the serialized
form as:

```text
"True"
"False"
```

These values are valid Scipion conditions and must be preserved.

Do not reinterpret them as parameter names.

## Expert level

Expert-level visibility is independent from parameter `condition`.

Changes to condition serialization must not alter or remove:

- parameter `expertLevel`;
- the global `expertLevel` form parameter;
- Normal versus Advanced visibility semantics.

## Regression expectations

Protocol form serialization tests should preserve at least:

- nested `Group -> Line -> Param` structure;
- `PathParam` subclass normalization;
- protocol constants required by conditions;
- condition strings without destructive rewriting;
- expert-level metadata.

The purpose of this layer is generic Scipion compatibility. Avoid
protocol-specific serialization workarounds when behavior can be represented
correctly from the native Scipion form definition.