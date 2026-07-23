import uuid

from django.db import models

from core.tenant_context import get_tenant_context, require_tenant_id


class UUIDModel(models.Model):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedModel(UUIDModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="%(class)s_records"
    )

    class TenantScopedManager(models.Manager):
        def get_queryset(self):
            context = get_tenant_context()
            if context is None or context.tenant_id is None:
                return super().get_queryset().none()
            return super().get_queryset().filter(tenant_id=require_tenant_id())

    objects = TenantScopedManager()

    class Meta:
        abstract = True
