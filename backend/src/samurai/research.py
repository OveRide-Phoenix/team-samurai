"""Convert native Gemini Search grounding into bounded research lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol, cast, override
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError

from samurai.contracts import (
    Assumption,
    CompanyBrief,
    ResearchArtifact,
    SourcedClaim,
    SourceReference,
    VerificationFinding,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from agno.models.message import Citations
    from agno.run.agent import RunOutput

MAX_SOURCES: Final = 10
MAX_CLAIMS: Final = 20
MAX_SEGMENT_CHARS: Final = 500


@dataclass(frozen=True, slots=True)
class ResearchInputError(Exception):
    """A requested retention cap exceeds the bounded research contract."""

    max_sources: int

    @override
    def __str__(self) -> str:
        return f"max_sources must be between 1 and {MAX_SOURCES}"


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Research content plus deterministic, still-unverified source lineage."""

    status: Literal["complete", "insufficient_evidence"]
    payload: ResearchArtifact
    sources: tuple[SourceReference, ...]
    claims: tuple[SourcedClaim, ...]
    assumptions: tuple[Assumption, ...]
    verification_findings: tuple[VerificationFinding, ...]


class ResearchAgent(Protocol):
    """Minimal async Agno runner needed by grounded research."""

    def arun(
        self,
        input: str,  # noqa: A002
        *,
        stream: Literal[False] = False,
    ) -> Awaitable[RunOutput]:
        """Run one non-streaming research request."""
        ...


class _ProviderModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)


class _ResearchDraft(_ProviderModel):
    summary: str
    conflicts: tuple[str, ...] = ()


class _GroundingWeb(_ProviderModel):
    uri: str | None = None
    title: str | None = None


class _GroundingChunk(_ProviderModel):
    web: _GroundingWeb | None = None


class _GroundingSegment(_ProviderModel):
    text: str | None = None


class _GroundingSupport(_ProviderModel):
    segment: _GroundingSegment | None = None
    grounding_chunk_indices: tuple[int, ...] = ()


class _GroundingMetadata(_ProviderModel):
    grounding_chunks: tuple[_GroundingChunk, ...] = ()
    grounding_supports: tuple[_GroundingSupport, ...] = ()


class _CitationRaw(_ProviderModel):
    grounding_metadata: _GroundingMetadata | None = None


@dataclass(frozen=True, slots=True)
class _CandidateSource:
    url: str
    title: str
    chunk_index: int | None


@dataclass(frozen=True, slots=True)
class _Retention:
    query: str
    retrieved_at: datetime
    max_sources: int


async def run_research(
    agent: ResearchAgent,
    brief: CompanyBrief,
    *,
    max_sources: int = 5,
) -> ResearchResult:
    """Run one grounded researcher and retain bounded, schema-checked lineage."""
    if not 1 <= max_sources <= MAX_SOURCES:
        raise ResearchInputError(max_sources)
    request = (
        "Use Google Search for current public competitor and pricing evidence as of "
        "2026-10-11, and cite each web source before answering.\n\n"
    )
    output = await agent.arun(request + brief.model_dump_json(), stream=False)
    draft = (
        _ResearchDraft.model_validate_json(
            output.content.removeprefix("```json").removesuffix("```").strip()
        )
        if isinstance(output.content, str)
        else _ResearchDraft.model_validate(output.content, from_attributes=True)
    )
    payload = ResearchArtifact(summary=draft.summary, conflicts=draft.conflicts)
    citations = output.citations
    grounding = _parse_grounding(citations)
    candidates = _source_candidates(citations, grounding)
    sources, chunk_sources = _retain_sources(
        candidates,
        grounding,
        _Retention(
            query=_search_query(citations, brief.idea),
            retrieved_at=datetime.now(UTC),
            max_sources=max_sources,
        ),
    )
    claims = _retain_claims(grounding, sources, chunk_sources, payload.summary)
    finding = VerificationFinding(
        code="research_lineage_retained" if sources else "research_citations_missing",
        message=(
            "Source linkage was retained; factual support remains unverified."
            if sources
            else "No usable source citation was returned; research is insufficient."
        ),
        severity="info" if sources else "warning",
    )
    return ResearchResult(
        status="complete" if sources else "insufficient_evidence",
        payload=payload,
        sources=sources,
        claims=claims,
        assumptions=(Assumption(assumption_id=uuid4(), text=payload.summary),),
        verification_findings=(finding,),
    )


def _parse_grounding(citations: Citations | None) -> _GroundingMetadata:
    if citations is None or citations.raw is None:
        return _GroundingMetadata()
    try:
        raw = _CitationRaw.model_validate(cast("object", citations.raw))
    except ValidationError:
        return _GroundingMetadata()
    return raw.grounding_metadata if raw.grounding_metadata is not None else _GroundingMetadata()


def _search_query(citations: Citations | None, fallback: str) -> str:
    if citations is not None:
        for query in citations.search_queries or ():
            if stripped := query.strip():
                return stripped
    return fallback


def _source_candidates(
    citations: Citations | None,
    grounding: _GroundingMetadata,
) -> tuple[_CandidateSource, ...]:
    candidates = [
        _CandidateSource(web.uri, (web.title or web.uri).strip(), index)
        for index, chunk in enumerate(grounding.grounding_chunks)
        if (web := chunk.web) is not None and web.uri and web.uri.strip()
    ]
    if citations is not None:
        candidates.extend(
            _CandidateSource(citation.url, (citation.title or citation.url).strip(), None)
            for citation in citations.urls or ()
            if citation.url and citation.url.strip()
        )
    return tuple(candidates)


def _retain_sources(
    candidates: tuple[_CandidateSource, ...],
    grounding: _GroundingMetadata,
    retention: _Retention,
) -> tuple[tuple[SourceReference, ...], dict[int, UUID]]:
    retained: list[SourceReference] = []
    source_by_url: dict[str, SourceReference] = {}
    chunk_urls = {
        candidate.chunk_index: candidate.url
        for candidate in candidates
        if candidate.chunk_index is not None
    }
    segments_by_url: dict[str, list[str]] = {}
    for support in grounding.grounding_supports:
        if support.segment is None or not (text := support.segment.text):
            continue
        for index in support.grounding_chunk_indices:
            if url := chunk_urls.get(index):
                segments_by_url.setdefault(url, []).append(text.strip()[:MAX_SEGMENT_CHARS])
    for candidate in candidates:
        if candidate.url in source_by_url or len(retained) >= retention.max_sources:
            continue
        excerpt = " ".join(dict.fromkeys(segments_by_url.get(candidate.url, ())))[:2000]
        try:
            source = SourceReference(
                source_id=uuid4(),
                url=HttpUrl(candidate.url),
                title=candidate.title,
                retrieved_at=retention.retrieved_at,
                search_query=retention.query,
                excerpt=excerpt or "Provider returned the URL without a mapped support segment.",
            )
        except ValidationError:
            continue
        retained.append(source)
        source_by_url[candidate.url] = source
    chunk_sources = {
        index: source_by_url[url].source_id
        for index, url in chunk_urls.items()
        if url in source_by_url
    }
    return tuple(retained), chunk_sources


def _retain_claims(
    grounding: _GroundingMetadata,
    sources: tuple[SourceReference, ...],
    chunk_sources: dict[int, UUID],
    summary: str,
) -> tuple[SourcedClaim, ...]:
    if not sources:
        return ()
    claims: list[SourcedClaim] = []
    seen_text: set[str] = set()
    all_source_ids = tuple(source.source_id for source in sources)
    for support in grounding.grounding_supports:
        if len(claims) >= MAX_CLAIMS or support.segment is None:
            break
        text = (support.segment.text or "").strip()[:MAX_SEGMENT_CHARS]
        if not text or text in seen_text:
            continue
        source_ids = tuple(
            dict.fromkeys(
                chunk_sources[index]
                for index in support.grounding_chunk_indices
                if index in chunk_sources
            )
        )
        mapped = bool(source_ids)
        claims.append(
            SourcedClaim(
                claim_id=uuid4(),
                text=text,
                source_ids=source_ids or all_source_ids,
                support_status="mapped" if mapped else "unmapped",
                support_segments=(text,) if mapped else (),
                verification_status="unverified",
            )
        )
        seen_text.add(text)
    if not claims:
        claims.append(
            SourcedClaim(
                claim_id=uuid4(),
                text=summary,
                source_ids=all_source_ids,
                support_status="unmapped",
                support_segments=(),
                verification_status="unverified",
            )
        )
    return tuple(claims)
