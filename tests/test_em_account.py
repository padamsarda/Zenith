"""Tests for the ProviderAccount domain entity."""

from __future__ import annotations

import dataclasses

import pytest

from engineering_manager.domain.account import ProviderAccount


def test_account_holds_identity_and_label() -> None:
    account = ProviderAccount(provider_id="claude", account_id="personal", label="Personal")

    assert account.provider_id == "claude"
    assert account.account_id == "personal"
    assert account.label == "Personal"


def test_account_label_is_optional() -> None:
    account = ProviderAccount(provider_id="claude", account_id="personal")

    assert account.label is None


def test_account_is_frozen() -> None:
    account = ProviderAccount(provider_id="claude", account_id="personal")

    with pytest.raises(dataclasses.FrozenInstanceError):
        account.account_id = "other"  # type: ignore[misc]


def test_accounts_with_same_fields_are_equal() -> None:
    assert ProviderAccount("claude", "personal") == ProviderAccount("claude", "personal")
