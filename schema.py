from typing import get_type_hints, get_origin, get_args, List, Dict, Optional, Union, Any
from types import NoneType

def python_type_to_json_type(py_type: Any) -> dict:
    """
    Convert a Python type annotation to JSON Schema type.
    Handles list, dict, optional, union, and basic types.
    """
    origin = get_origin(py_type)
    args = get_args(py_type)

    if origin is Union:
        # Optional or general union
        subtypes = [python_type_to_json_type(a) for a in args if a is not NoneType]
        if NoneType in args:
            # optional field
            if len(subtypes) == 1:
                return {"anyOf": [subtypes[0], {"type": "null"}]}
            else:
                return {"anyOf": subtypes + [{"type": "null"}]}
        else:
            return {"anyOf": subtypes}
    elif origin is list or origin is List:
        item_type = python_type_to_json_type(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_type}
    elif origin is dict or origin is Dict:
        key_type, val_type = args if args else (str, Any)
        val_schema = python_type_to_json_type(val_type)
        return {"type": "object", "additionalProperties": val_schema}
    elif py_type in [str, int, float, bool]:
        return {"type": {str: "string", int: "integer", float: "number", bool: "boolean"}[py_type]}
    elif isinstance(py_type, type):
        # Custom class: treat as object and recurse
        return class_to_json_schema(py_type)
    else:
        # fallback
        return {"type": "string"}

def class_to_json_schema(cls) -> dict:
    """
    Generate JSON Schema for a Python class using __annotations__.
    Recursively handles nested classes.
    """
    props = {}
    for name, ann in get_type_hints(cls).items():
        props[name] = python_type_to_json_type(ann)

    return {
        "type": "object",
        "properties": props,
        "required": list(props.keys())
    }