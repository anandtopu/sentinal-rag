"""Unit tests for the three chunking strategies."""

from __future__ import annotations

import pytest
from sentinelrag_shared.chunking import (
    ChunkingStrategy,
    SemanticChunker,
    SlidingWindowChunker,
    StructureAwareChunker,
    get_chunker,
)
from sentinelrag_shared.parsing.elements import ElementType, ParsedElement


def _make_elements(parts: list[tuple[ElementType, str]]) -> list[ParsedElement]:
    return [
        ParsedElement(text=text, element_type=t, page_number=1)
        for t, text in parts
    ]


@pytest.mark.unit
class TestSemanticChunker:
    def test_keeps_short_doc_as_one_chunk(self) -> None:
        elements = _make_elements(
            [
                (ElementType.NARRATIVE_TEXT, "First paragraph."),
                (ElementType.NARRATIVE_TEXT, "Second paragraph."),
            ]
        )
        chunks = SemanticChunker(target_tokens=512).chunk(elements)
        assert len(chunks) == 1
        assert "First paragraph" in chunks[0].text
        assert "Second paragraph" in chunks[0].text

    def test_splits_when_budget_exceeded(self) -> None:
        big_text = " ".join(["word"] * 800)  # well over default 512 token budget
        elements = _make_elements([(ElementType.NARRATIVE_TEXT, big_text)])
        chunks = SemanticChunker(target_tokens=200, overlap_tokens=20).chunk(elements)
        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count <= 250  # target + small slack

    def test_skips_headers_and_footers(self) -> None:
        elements = _make_elements(
            [
                (ElementType.HEADER, "Page header — irrelevant"),
                (ElementType.NARRATIVE_TEXT, "Real content here."),
                (ElementType.FOOTER, "Page 1 of 5"),
            ]
        )
        chunks = SemanticChunker(target_tokens=512).chunk(elements)
        text = " ".join(c.text for c in chunks)
        assert "Real content here" in text
        assert "Page header" not in text
        assert "Page 1 of 5" not in text

    def test_chunk_indices_are_monotonic(self) -> None:
        elements = _make_elements(
            [
                (ElementType.NARRATIVE_TEXT, " ".join(["alpha"] * 600)),
                (ElementType.NARRATIVE_TEXT, " ".join(["beta"] * 600)),
            ]
        )
        chunks = SemanticChunker(target_tokens=200).chunk(elements)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


@pytest.mark.unit
class TestSlidingWindowChunker:
    def test_produces_overlapping_windows(self) -> None:
        elements = _make_elements(
            [(ElementType.NARRATIVE_TEXT, " ".join(["word"] * 1000))]
        )
        chunks = SlidingWindowChunker(target_tokens=200, overlap_tokens=50).chunk(
            elements
        )
        assert len(chunks) >= 4  # 1000 / (200 - 50) ≈ 6.7 windows
        for c in chunks:
            assert c.token_count <= 200

    def test_rejects_overlap_ge_target(self) -> None:
        with pytest.raises(ValueError, match="overlap"):
            SlidingWindowChunker(target_tokens=100, overlap_tokens=100)

    def test_empty_doc_yields_empty(self) -> None:
        chunks = SlidingWindowChunker().chunk([])
        assert chunks == []


@pytest.mark.unit
class TestStructureAwareChunker:
    def test_table_is_not_split_with_other_content(self) -> None:
        elements = [
            ParsedElement(
                text="Intro paragraph.",
                element_type=ElementType.NARRATIVE_TEXT,
                page_number=1,
            ),
            ParsedElement(
                text="<<TABLE>>",
                element_type=ElementType.TABLE,
                page_number=1,
                table_html="<table><tr><td>x</td></tr></table>",
            ),
            ParsedElement(
                text="Trailing paragraph.",
                element_type=ElementType.NARRATIVE_TEXT,
                page_number=1,
            ),
        ]
        chunks = StructureAwareChunker(target_tokens=512).chunk(elements)
        # The table gets its own chunk; the table's own row carries table_html.
        table_chunks = [c for c in chunks if c.table_html]
        assert len(table_chunks) == 1
        # And no chunk contains both intro AND trailing — the table broke them.
        for c in chunks:
            assert not ("Intro paragraph" in c.text and "Trailing paragraph" in c.text)

    def test_heading_starts_new_chunk_and_sets_section(self) -> None:
        elements = [
            ParsedElement(text="Pre-heading body.", element_type=ElementType.NARRATIVE_TEXT),
            ParsedElement(text="My Section", element_type=ElementType.HEADING),
            ParsedElement(text="Post-heading body.", element_type=ElementType.NARRATIVE_TEXT),
        ]
        chunks = StructureAwareChunker(target_tokens=512).chunk(elements)
        # The heading is consumed as section_title for following chunks; not its
        # own chunk text.
        post = [c for c in chunks if "Post-heading" in c.text]
        assert post
        assert post[0].section_title == "My Section"
        pre = [c for c in chunks if "Pre-heading" in c.text]
        assert pre
        assert pre[0].section_title != "My Section"


@pytest.mark.unit
class TestChunkerFactory:
    def test_factory_dispatches_correctly(self) -> None:
        assert isinstance(
            get_chunker(ChunkingStrategy.SEMANTIC), SemanticChunker
        )
        assert isinstance(
            get_chunker(ChunkingStrategy.SLIDING_WINDOW), SlidingWindowChunker
        )
        assert isinstance(
            get_chunker(ChunkingStrategy.STRUCTURE_AWARE), StructureAwareChunker
        )
