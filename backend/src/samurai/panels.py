# ruff: noqa: D101, D102, D103, EM101, TRY003
"""Bounded presentation tools; generated views never change company evidence."""

from __future__ import annotations

import json
from typing import Annotated, Final, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from agno.run import RunContext  # noqa: TC002 - Agno resolves tool annotations at runtime.
from agno.tools.function import Function
from pydantic import Field, JsonValue, TypeAdapter, model_validator

from samurai.contracts import Contract

PANEL_MARKER = "SAMURAI_PANEL="
MAX_PANEL_CHARS = 100_000
MAX_PANEL_KEY_CHARS = 80
DRAFT_NOTE = "Generated view · Working assumptions, not verified business results"
ShortText = Annotated[str, Field(min_length=1, max_length=4000)]


class TextBlock(Contract):
    kind: Literal["text"]
    text: ShortText


class MetricBlock(Contract):
    kind: Literal["metric"]
    label: ShortText
    value: ShortText
    detail: ShortText


class ListBlock(Contract):
    kind: Literal["list"]
    title: ShortText
    items: Annotated[list[ShortText], Field(min_length=1, max_length=30)]


class TableBlock(Contract):
    kind: Literal["table"]
    columns: Annotated[list[ShortText], Field(min_length=1, max_length=8)]
    rows: Annotated[list[list[ShortText]], Field(max_length=100)]

    @model_validator(mode="after")
    def rectangular(self) -> TableBlock:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Each table row must match the columns")
        return self


PanelBlock = Annotated[
    TextBlock | MetricBlock | ListBlock | TableBlock, Field(discriminator="kind")
]


class DeclarativePanel(Contract):
    id: str
    kind: Literal["declarative"] = "declarative"
    title: Annotated[str, Field(min_length=1, max_length=120)]
    note: Literal["Generated view · Working assumptions, not verified business results"] = (
        DRAFT_NOTE
    )
    blocks: Annotated[list[PanelBlock], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def bounded(self) -> DeclarativePanel:
        if len(self.model_dump_json()) > MAX_PANEL_CHARS:
            raise ValueError("Panel exceeds the size limit")
        return self


class CustomPanel(Contract):
    id: str
    kind: Literal["custom"] = "custom"
    title: Annotated[str, Field(min_length=1, max_length=120)]
    note: Literal["Generated view · Working assumptions, not verified business results"] = (
        DRAFT_NOTE
    )
    html: Annotated[str, Field(min_length=1, max_length=60_000)]
    css: Annotated[str, Field(max_length=20_000)]
    javascript: Annotated[str, Field(max_length=20_000)]


def _panel_id(context: RunContext, panel_key: str) -> str:
    if not context.user_id or not context.session_id:
        raise ValueError("Authenticated company session required")
    if not panel_key or len(panel_key) > MAX_PANEL_KEY_CHARS:
        raise ValueError("Panel key must contain 1 to 80 characters")
    identity = json.dumps(
        ("samurai-panel", context.user_id, context.session_id, panel_key), separators=(",", ":")
    )
    return str(uuid5(NAMESPACE_URL, identity))


def compose_panel(
    run_context: RunContext,
    panel_key: str,
    title: str,
    blocks: list[object],
) -> str:
    """Compose a useful draft view; reuse panel_key to update it.

    Each block uses exactly one shape, with no extra fields:
    {"kind":"text","text":"..."};
    {"kind":"metric","label":"...","value":"...","detail":"..."};
    {"kind":"list","title":"...","items":["..."]};
    {"kind":"table","columns":["..."],"rows":[["..."]]}.
    Text blocks have no title or detail field; put all prose in text.
    """
    panel = DeclarativePanel.model_validate(
        {"id": _panel_id(run_context, panel_key), "title": title, "blocks": blocks}
    )
    return PANEL_MARKER + panel.model_dump_json()


def create_custom_panel(  # noqa: PLR0913 - typed presentation tool contract.
    run_context: RunContext,
    panel_key: str,
    title: str,
    html: str,
    *,
    css: str = "",
    javascript: str = "",
) -> str:
    """Create a requested inline interactive view without network or host access."""
    panel = CustomPanel(
        id=_panel_id(run_context, panel_key),
        title=title,
        html=html,
        css=css,
        javascript=javascript,
    )
    return PANEL_MARKER + panel.model_dump_json()


_schema = DeclarativePanel.model_json_schema()
# Agno's Gemini adapter supports anyOf/enum, but drops oneOf/const.
_schema["properties"]["blocks"]["items"] = {
    "anyOf": _schema["properties"]["blocks"]["items"]["oneOf"]
}
for _block_type in (TextBlock, MetricBlock, ListBlock, TableBlock):
    _kind = cast(
        "dict[str, JsonValue]", _schema["$defs"][_block_type.__name__]["properties"]["kind"]
    )
    _kind["enum"] = [_kind.pop("const")]
COMPOSE_PARAMETERS: Final = TypeAdapter(dict[str, JsonValue]).validate_python(
    {
        "type": "object",
        "properties": {
            "panel_key": {"type": "string", "minLength": 1, "maxLength": MAX_PANEL_KEY_CHARS},
            "title": _schema["properties"]["title"],
            "blocks": _schema["properties"]["blocks"],
        },
        "$defs": _schema["$defs"],
        "required": ["panel_key", "title", "blocks"],
        "additionalProperties": False,
    }
)


def presentation_tools() -> list[Function]:
    # Agno 3.1.2 hides nested Pydantic parameters; supply the schema and validate here.
    return [
        Function(
            name="compose_panel",
            description=compose_panel.__doc__,
            entrypoint=compose_panel,
            parameters=COMPOSE_PARAMETERS,
            skip_entrypoint_processing=True,
            stop_after_tool_call=True,
            show_result=True,
        ),
        Function(
            name="create_custom_panel",
            entrypoint=create_custom_panel,
            stop_after_tool_call=True,
            show_result=True,
        ),
    ]
