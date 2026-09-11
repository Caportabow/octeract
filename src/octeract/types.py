"""Best-effort coercion of raw response data (dict/list/primitive) into a
declared response type: a dataclass, a pydantic model, or a plain type.

This is intentionally lenient rather than a full validation framework: the
goal is "make any API feel typed", not to replace pydantic/attrs.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional, Type, TypeVar

from .exceptions import ValidationError

T = TypeVar("T")

try:
    from pydantic import BaseModel as _PydanticBaseModel
except ImportError:  # pydantic is an optional dependency
    _PydanticBaseModel = None  # type: ignore[assignment]


def coerce(data: Any, model: Optional[Type[T]]) -> Any:
    """Coerce `data` into `model` if a model was declared; otherwise pass through."""
    if model is None or data is None:
        return data

    # Already the right type.
    if isinstance(model, type) and isinstance(data, model):
        return data

    # Pydantic model.
    if _PydanticBaseModel is not None and isinstance(model, type) and issubclass(model, _PydanticBaseModel):
        try:
            if hasattr(model, "model_validate"):  # pydantic v2
                return model.model_validate(data)
            return model.parse_obj(data)  # pydantic v1
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Failed to coerce into {model.__name__}: {exc}", data, model) from exc

    # Dataclass.
    if dataclasses.is_dataclass(model) and isinstance(data, dict):
        field_names = {f.name for f in dataclasses.fields(model)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        try:
            return model(**filtered)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Failed to coerce into {model.__name__}: {exc}", data, model) from exc

    # List of models, e.g. response_model=list[User].
    origin = getattr(model, "__origin__", None)
    if origin in (list, tuple) and isinstance(data, (list, tuple)):
        (item_type,) = getattr(model, "__args__", (None,))
        coerced = [coerce(item, item_type) for item in data]
        return origin(coerced)

    # Last resort: try direct construction, else return raw data untouched.
    try:
        return model(**data) if isinstance(data, dict) else model(data)
    except Exception:
        return data
