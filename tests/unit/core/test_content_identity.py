"""Tests for parsed-content identity."""

from __future__ import annotations

from ai_ingestion_retrieval_platform.core.content_identity import (
    ContentIdentityState,
    calculate_content_sha256,
    classify_content_identity,
)


def test_calculate_content_sha256_hashes_empty_text() -> None:
    result = calculate_content_sha256("")

    assert result == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_calculate_content_sha256_hashes_ascii_text() -> None:
    result = calculate_content_sha256("hello")

    assert result == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_calculate_content_sha256_hashes_unicode_as_utf8() -> None:
    result = calculate_content_sha256("café")

    assert result == (
        "850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e"
    )


def test_identical_text_produces_identical_hashes() -> None:
    text = "Persisted parsed content."

    assert calculate_content_sha256(text) == calculate_content_sha256(text)


def test_changed_text_produces_different_hashes() -> None:
    original = "Persisted parsed content."
    changed = "Persisted parsed content changed."

    assert calculate_content_sha256(original) != calculate_content_sha256(changed)


def test_whitespace_is_part_of_content_identity() -> None:
    assert calculate_content_sha256(
        "Persisted parsed content."
    ) != calculate_content_sha256("Persisted parsed content. ")


def test_unicode_normalization_is_not_applied() -> None:
    composed = "café"
    decomposed = "cafe\u0301"

    assert composed != decomposed
    assert calculate_content_sha256(composed) != calculate_content_sha256(decomposed)


def test_classify_content_identity_returns_new_without_previous_content() -> None:
    result = classify_content_identity(
        current_sha256=calculate_content_sha256("current"),
        previous_sha256=None,
    )

    assert result is ContentIdentityState.NEW


def test_classify_content_identity_returns_unchanged_for_equal_hashes() -> None:
    content_sha256 = calculate_content_sha256("same content")

    result = classify_content_identity(
        current_sha256=content_sha256,
        previous_sha256=content_sha256,
    )

    assert result is ContentIdentityState.UNCHANGED


def test_classify_content_identity_returns_changed_for_different_hashes() -> None:
    result = classify_content_identity(
        current_sha256=calculate_content_sha256("new content"),
        previous_sha256=calculate_content_sha256("old content"),
    )

    assert result is ContentIdentityState.CHANGED
