from uuid import UUID

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.tenants.models import Tenant


class AuditService:
    @staticmethod
    def record(
        *,
        tenant: Tenant,
        actor: User | None,
        action: str,
        entity_type: str,
        entity_id: UUID,
        metadata: dict,
    ) -> AuditEvent:
        return AuditEvent.objects.create(
            tenant=tenant,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )
