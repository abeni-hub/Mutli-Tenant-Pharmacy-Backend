from typing import TypeVar
from uuid import UUID

from django.db import models

from core.models import TenantScopedModel

TenantModel = TypeVar("TenantModel", bound=TenantScopedModel)


class TenantScopedRepository[TenantModel]:
    model: type[TenantModel]

    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    def queryset(self) -> models.QuerySet[TenantModel]:
        return self.model.objects.filter(tenant_id=self.tenant_id)

    def get(self, object_id: UUID) -> TenantModel:
        return self.queryset().get(id=object_id)
