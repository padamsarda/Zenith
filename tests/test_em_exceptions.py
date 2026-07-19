"""Tests for the Engineering Manager exception hierarchy."""

from __future__ import annotations

from engineering_manager.exceptions import (
    AccountNotFoundError,
    DomainValidationError,
    DuplicateEntityError,
    EngineeringManagerError,
    OrchestrationError,
    ProjectNotFoundError,
    ProviderAlreadyRegisteredError,
    ProviderError,
    ProviderNotFoundError,
    ProviderSessionError,
    SessionNotFoundError,
    StoreError,
    TaskNotFoundError,
)
from shared.exceptions import ZenithError


def test_engineering_manager_error_inherits_zenith_error() -> None:
    assert issubclass(EngineeringManagerError, ZenithError)


def test_domain_validation_error_inherits_base() -> None:
    assert issubclass(DomainValidationError, EngineeringManagerError)


def test_provider_errors_inherit_provider_error() -> None:
    for error_type in (
        ProviderNotFoundError,
        ProviderAlreadyRegisteredError,
        ProviderSessionError,
    ):
        assert issubclass(error_type, ProviderError)
    assert issubclass(ProviderError, EngineeringManagerError)


def test_store_errors_inherit_store_error() -> None:
    for error_type in (
        ProjectNotFoundError,
        TaskNotFoundError,
        SessionNotFoundError,
        AccountNotFoundError,
        DuplicateEntityError,
    ):
        assert issubclass(error_type, StoreError)
    assert issubclass(StoreError, EngineeringManagerError)


def test_orchestration_error_inherits_base() -> None:
    assert issubclass(OrchestrationError, EngineeringManagerError)


def test_all_em_errors_are_catchable_as_engineering_manager_error() -> None:
    for error_type in (
        DomainValidationError,
        ProviderError,
        ProviderNotFoundError,
        ProviderAlreadyRegisteredError,
        ProviderSessionError,
        StoreError,
        ProjectNotFoundError,
        TaskNotFoundError,
        SessionNotFoundError,
        AccountNotFoundError,
        DuplicateEntityError,
        OrchestrationError,
    ):
        try:
            raise error_type("boom")
        except EngineeringManagerError as exc:
            assert isinstance(exc, error_type)
