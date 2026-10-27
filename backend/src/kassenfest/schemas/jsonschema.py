"""Checks a schema against the Meta structured-output limits (dev.meta.ai/docs/structured-output).

The server inlines $ref, rejects recursive refs, and allows nesting depth <= 10
and <= 5,000 properties after inlining.
"""

from typing import Any

MAX_DEPTH = 10
MAX_PROPERTIES = 5000


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {})

    def resolve(node: Any, stack: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                if name in stack:
                    raise ValueError(f"recursive $ref: {' -> '.join((*stack, name))}")
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                return {**resolve(defs[name], (*stack, name)), **siblings}
            return {k: resolve(v, stack) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v, stack) for v in node]
        return node

    return resolve(schema, ())


def nesting_depth(node: Any) -> int:
    """Count object/array levels along the deepest path."""
    if not isinstance(node, dict):
        return 0
    own = 1 if node.get("type") in ("object", "array") else 0
    children = [
        *(node.get("properties") or {}).values(),
        *([node["items"]] if isinstance(node.get("items"), dict) else []),
        *node.get("anyOf", []),
    ]
    return own + max((nesting_depth(c) for c in children), default=0)


def count_properties(node: Any) -> int:
    if isinstance(node, dict):
        own = len(node.get("properties") or {})
        return own + sum(count_properties(v) for v in node.values())
    if isinstance(node, list):
        return sum(count_properties(v) for v in node)
    return 0


def object_nodes(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        found = [node] if node.get("type") == "object" else []
        return found + [n for v in node.values() for n in object_nodes(v)]
    if isinstance(node, list):
        return [n for v in node for n in object_nodes(v)]
    return []
