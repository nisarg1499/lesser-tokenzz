"""Provider-neutral response types; billing stays unknown unless measured."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    text: str
    retrieved_at: str
    provider: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResponse:
    hits: list[SearchHit]
    elapsed_s: float
    provider: str
    billable_units: float | None = None
    cost_usd: float | None = None
    usage: dict = field(default_factory=dict)


class SearchProvider(Protocol):
    """Adapters must preserve source URLs, timestamps, usage, failures and costs."""

    name: str

    def search(self, query: str, *, limit: int = 10) -> SearchResponse: ...
    def fetch(self, url: str) -> SearchResponse: ...
