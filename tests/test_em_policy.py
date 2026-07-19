"""Tests for the FirstAvailablePolicy."""

from __future__ import annotations

from uuid import uuid4

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task
from engineering_manager.orchestration.policy import FirstAvailablePolicy


def make_task() -> Task:
    return Task(project_id="zenith", title="Write docs")


def make_session(provider_id: str, account_id: str) -> Session:
    return Session(
        task_id=uuid4(), project_id="zenith", provider_id=provider_id, account_id=account_id
    )


def test_chooses_first_account_when_all_free() -> None:
    policy = FirstAvailablePolicy()
    accounts = [
        ProviderAccount(provider_id="claude", account_id="personal"),
        ProviderAccount(provider_id="gemini", account_id="work"),
    ]

    chosen = policy.choose_account(make_task(), accounts, [])

    assert chosen == accounts[0]


def test_skips_account_with_open_session() -> None:
    policy = FirstAvailablePolicy()
    accounts = [
        ProviderAccount(provider_id="claude", account_id="personal"),
        ProviderAccount(provider_id="gemini", account_id="work"),
    ]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "personal")]
    )

    assert chosen == accounts[1]


def test_returns_none_when_every_account_is_busy() -> None:
    policy = FirstAvailablePolicy()
    accounts = [ProviderAccount(provider_id="claude", account_id="personal")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "personal")]
    )

    assert chosen is None


def test_returns_none_with_no_accounts() -> None:
    policy = FirstAvailablePolicy()

    assert policy.choose_account(make_task(), [], []) is None


def test_same_account_id_on_other_provider_does_not_block() -> None:
    policy = FirstAvailablePolicy()
    accounts = [ProviderAccount(provider_id="gemini", account_id="personal")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "personal")]
    )

    assert chosen == accounts[0]
