"""Photo import actions for the frontend (main.py convert_images).

Takes the JSON payload dict and returns a JSON-able dict; failures come back as
{"success": False, "error": ...} so the UI gets a readable message."""

from typing import Any, Callable, Dict

from services.imageconvert import HeifUnavailable, convert_images

IMAGE_ACTIONS = ("convert_images",)


def convert(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, **convert_images(payload["paths"], payload["out_dir"])}


_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {"convert_images": convert}


def run_image_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return _HANDLERS[action](payload or {})
    except KeyError as exc:
        return {"success": False, "error": f"Missing field: {exc.args[0]}"}
    except HeifUnavailable as exc:
        return {"success": False, "error": str(exc), "missing_package": "pillow-heif"}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
