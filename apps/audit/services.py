"""
Audit service — records structured audit events for all tenant operations.
"""
from __future__ import annotations

import uuid
from uuid import UUID

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.tenants.models import Tenant


class AuditService:
    @staticmethod
    def record(
        *,
        tenant: Tenant | None = None,
        actor: User | None,
        action: str,
        entity_type: str,
        entity_id: UUID | str | None = None,
        metadata: dict,
        ip_address: str | None = None,
    ) -> AuditEvent:
        """
        Persist a single audit event.

        Args:
            tenant:      The tenant context for this event.
            actor:       The user who performed the action (None for system events).
            action:      One of AuditEvent.Action values.
            entity_type: Dotted model name, e.g. "tenants.Tenant".
            entity_id:   UUID primary key of the affected object (optional, auto-generated if None).
            metadata:    Arbitrary JSON-serialisable context dict.
            ip_address:  Optional originating IP (captured from request).
        """
        if entity_id is None:
            entity_id = uuid.uuid4()
        elif isinstance(entity_id, str):
            entity_id = UUID(entity_id)

        return AuditEvent.objects.create(
            tenant=tenant,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
            ip_address=ip_address,
        )

    @staticmethod
    def record_login(
        *,
        tenant: Tenant,
        actor: User,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Convenience wrapper for recording a successful login audit event."""
        return AuditService.record(
            tenant=tenant,
            actor=actor,
            action=AuditEvent.Action.LOGIN,
            entity_type="accounts.User",
            entity_id=actor.id,
            metadata=metadata or {},
            ip_address=ip_address,
        )
