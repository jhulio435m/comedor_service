import html
from typing import Any


def h(value: Any) -> str:
    return html.escape(str(value), quote=False)


def pre(value: str) -> str:
    return f"<pre>{h(value)}</pre>"
