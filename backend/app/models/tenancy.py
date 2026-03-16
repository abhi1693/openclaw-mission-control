"""Shared tenancy-scoped model base classes."""

from __future__ import annotations

from app.models.base import QueryModel


class TenantScoped(QueryModel, table=False):
    """Base class for models constrained to a tenant/organization scope."""
