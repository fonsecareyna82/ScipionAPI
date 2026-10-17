"""Safe, inert protocol-viewer condition syntax for later browser evaluation.

No Scipion imports and no Python eval/exec. Parse a deliberately small grammar,
then serialize it as bounded JSON with explicit operators and operands.
"""
from __future__ import annotations

import ast
import math

_BINOPS = {ast.Eq: 'eq', ast.NotEq: 'ne', ast.Lt: 'lt', ast.LtE: 'le',
           ast.Gt: 'gt', ast.GtE: 'ge', ast.Is: 'is', ast.IsNot: 'is-not'}
_OPERATORS = frozenset(_BINOPS.values())


def _scalar(value):
    return (value is None or type(value) in (bool, int) or
            (type(value) is float and math.isfinite(value)) or
            (type(value) is str and len(value) <= 256))


def compileViewerConditionRule(expression):
    """Compile a whitelisted Python expression to inert bounded JSON, or None."""
    if type(expression) is not str or not 0 < len(expression) <= 256:
        return None
    try:
        expr = ast.parse(expression, mode='eval')
        if len(list(ast.walk(expr))) > 40:
            return None
    except (SyntaxError, ValueError, RecursionError):
        return None

    def walk(node, depth):
        if depth > 12:
            raise ValueError('rule too deep')
        if isinstance(node, ast.Constant) and _scalar(node.value):
            return {'op': 'const', 'value': node.value}
        if isinstance(node, ast.Name) and len(node.id) <= 128 and node.id.isidentifier():
            return {'op': 'field', 'name': node.id}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return {'op': 'not', 'arg': walk(node.operand, depth + 1)}
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)) \
                and 2 <= len(node.values) <= 16:
            return {'op': 'and' if isinstance(node.op, ast.And) else 'or',
                    'args': [walk(item, depth + 1) for item in node.values]}
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            op = _BINOPS.get(type(node.ops[0]))
            if op:
                left, right = walk(node.left, depth + 1), walk(node.comparators[0], depth + 1)
                if op in ('is', 'is-not') and not (
                    left == {'op': 'const', 'value': None} or
                    right == {'op': 'const', 'value': None}
                ):
                    raise ValueError('only identity with None allowed')
                return {'op': op, 'left': left, 'right': right}
        raise ValueError('unsupported rule')

    try:
        result = walk(expr.body, 0)
    except (ValueError, RecursionError):
        return None
    return result if validViewerConditionRule(result) else None


def validViewerConditionRule(rule):
    """Check an untrusted JSON rule tree before forwarding to the frontend."""
    counter = [0]

    def check(node, depth):
        counter[0] += 1
        if depth > 12 or counter[0] > 40 or type(node) is not dict:
            return False
        op = node.get('op')
        if op == 'const':
            return set(node) == {'op', 'value'} and _scalar(node['value'])
        if op == 'field':
            return (set(node) == {'op', 'name'} and type(node['name']) is str
                    and 0 < len(node['name']) <= 128 and node['name'].isidentifier())
        if op == 'not':
            return set(node) == {'op', 'arg'} and check(node['arg'], depth + 1)
        if op in ('and', 'or'):
            return (set(node) == {'op', 'args'} and type(node['args']) is list
                    and 2 <= len(node['args']) <= 16
                    and all(check(child, depth + 1) for child in node['args']))
        if op in _OPERATORS:
            if set(node) != {'op', 'left', 'right'} or not (
                check(node['left'], depth + 1) and check(node['right'], depth + 1)
            ):
                return False
            if op in ('is', 'is-not') and not (
                node['left'] == {'op': 'const', 'value': None} or
                node['right'] == {'op': 'const', 'value': None}
            ):
                return False
            return True
        return False

    return check(rule, 0)


def referencedViewerFields(rule):
    """Return referenced names only for a validated, inert rule."""
    if not validViewerConditionRule(rule):
        return None
    names = set()

    def collect(node):
        if node['op'] == 'field':
            names.add(node['name'])
        elif node['op'] == 'not':
            collect(node['arg'])
        elif node['op'] in ('and', 'or'):
            for child in node['args']:
                collect(child)
        elif node['op'] not in ('const',):
            collect(node['left'])
            collect(node['right'])

    collect(rule)
    return frozenset(names)
