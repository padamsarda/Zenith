"""Tests for ConcurrencyLimitedPolicy."""

from __future__ import annotations

from uuid import uuid4

import pytest

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.policy import AssignmentPolicy, ConcurrencyLimitedPolicy


def make_task() -> Task:
    return Task(project_id="zenith", title="Write docs")


def make_session(provider_id: str, account_id: str) -> Session:
    return Session(
        task_id=uuid4(), project_id="zenith", provider_id=provider_id, account_id=account_id
    )


def test_is_an_assignment_policy() -> None:
    assert isinstance(ConcurrencyLimitedPolicy(), AssignmentPolicy)


def test_default_limit_of_one_matches_first_available_behavior() -> None:
    policy = ConcurrencyLimitedPolicy()
    accounts = [ProviderAccount(provider_id="claude", account_id="personal")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "personal")]
    )

    assert chosen is None


def test_higher_default_limit_allows_concurrent_sessions_on_one_provider() -> None:
    policy = ConcurrencyLimitedPolicy(default_limit=2)
    accounts = [ProviderAccount(provider_id="claude", account_id="a")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "a")]
    )

    assert chosen == accounts[0]


def test_limit_counts_across_every_account_on_the_same_provider() -> None:
    policy = ConcurrencyLimitedPolicy(default_limit=1)
    accounts = [ProviderAccount(provider_id="claude", account_id="b")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("claude", "a")]
    )

    assert chosen is None


def test_per_provider_limit_overrides_default() -> None:
    policy = ConcurrencyLimitedPolicy(limits={"claude": 3}, default_limit=1)
    accounts = [ProviderAccount(provider_id="claude", account_id="a")]
    open_sessions = [make_session("claude", "a"), make_session("claude", "b")]

    chosen = policy.choose_account(make_task(), accounts, open_sessions)

    assert chosen == accounts[0]


def test_per_provider_limit_still_blocks_once_reached() -> None:
    policy = ConcurrencyLimitedPolicy(limits={"claude": 2})
    accounts = [ProviderAccount(provider_id="claude", account_id="a")]
    open_sessions = [make_session("claude", "a"), make_session("claude", "b")]

    chosen = policy.choose_account(make_task(), accounts, open_sessions)

    assert chosen is None


def test_unnamed_provider_falls_back_to_default_limit() -> None:
    policy = ConcurrencyLimitedPolicy(limits={"claude": 5}, default_limit=1)
    accounts = [ProviderAccount(provider_id="gemini", account_id="a")]

    chosen = policy.choose_account(
        make_task(), accounts, [make_session("gemini", "a")]
    )

    assert chosen is None


def test_tries_accounts_in_given_order() -> None:
    policy = ConcurrencyLimitedPolicy()
    accounts = [
        ProviderAccount(provider_id="claude", account_id="a"),
        ProviderAccount(provider_id="gemini", account_id="b"),
    ]

    chosen = policy.choose_account(make_task(), accounts, [])

    assert chosen == accounts[0]


def test_returns_none_with_no_accounts() -> None:
    assert ConcurrencyLimitedPolicy().choose_account(make_task(), [], []) is None


def test_default_limit_must_be_a_positive_int() -> None:
    with pytest.raises(OrchestrationError):
        ConcurrencyLimitedPolicy(default_limit=0)
    with pytest.raises(OrchestrationError):
        ConcurrencyLimitedPolicy(default_limit="2")  # type: ignore[arg-type]


def test_provider_limit_must_be_a_positive_int() -> None:
    with pytest.raises(OrchestrationError):
        ConcurrencyLimitedPolicy(limits={"claude": 0})
    with pytest.raises(OrchestrationError):
        ConcurrencyLimitedPolicy(limits={"claude": True})
