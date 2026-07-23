from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.serializers import TenantCreateSerializer, TenantSerializer
from apps.tenants.services import TenantCreateData, TenantService
from core.api.permissions import TenantMembershipPermission


class TenantViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = TenantSerializer

    def list(self, request):
        tenants = TenantService.accessible_to(request.user)
        return Response(self.get_serializer(tenants, many=True).data)

    def create(self, request):
        serializer = TenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = TenantService.create_for_owner(
            request.user,
            TenantCreateData(**serializer.validated_data),
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


class TenantContextViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    serializer_class = TenantSerializer

    def retrieve(self, request, pk=None):
        tenant = next(
            (
                tenant
                for tenant in TenantService.accessible_to(request.user)
                if str(tenant.id) == str(pk)
            ),
            None,
        )
        if tenant is None:
            raise NotFound("Tenant not found.")
        return Response(self.get_serializer(tenant).data)
