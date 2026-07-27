from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)
from apps.subscriptions.serializers import (
    PaymentRequestRejectSerializer,
    PaymentRequestSerializer,
    PaymentRequestSubmitSerializer,
    SubscriptionNotificationSerializer,
    SubscriptionPlanSerializer,
    TenantSubscriptionSerializer,
)
from apps.subscriptions.services import SubscriptionService
from apps.tenants.models import Tenant
from core.api.permissions import TenantMembershipPermission


class SubscriptionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /subscriptions/plans/
    GET /subscriptions/plans/{id}/

    List active subscription plans available for tenants.
    """
    permission_classes = (AllowAny,)
    serializer_class = SubscriptionPlanSerializer
    queryset = SubscriptionPlan.objects.filter(is_active=True)


class TenantSubscriptionViewSet(viewsets.GenericViewSet):
    """
    GET /subscriptions/current/
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    serializer_class = TenantSubscriptionSerializer

    @action(detail=False, methods=["get"], url_path="current")
    def current_subscription(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        usage_data = SubscriptionService.get_tenant_usage_and_limits(tenant)
        sub = getattr(tenant, "subscription", None)
        sub_serialized = TenantSubscriptionSerializer(sub).data if sub else None

        return Response(
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "subscription": sub_serialized,
                "plan_limits_and_usage": usage_data,
            }
        )


class PaymentRequestViewSet(viewsets.ModelViewSet):
    """
    POST /subscriptions/payment-requests/         — Submit payment request (Tenant Owner/Member)
    GET  /subscriptions/payment-requests/         — List payment requests
    POST /subscriptions/payment-requests/{id}/approve/ — Approve payment (Platform Admin)
    POST /subscriptions/payment-requests/{id}/reject/  — Reject payment (Platform Admin)
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = PaymentRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return PaymentRequest.objects.select_related("tenant", "plan", "submitted_by", "reviewed_by").all()

        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id:
            return PaymentRequest.objects.select_related("tenant", "plan", "submitted_by").filter(tenant_id=tenant_id)

        # Fallback to user's accessible tenants
        return PaymentRequest.objects.select_related("tenant", "plan", "submitted_by").filter(
            tenant__memberships__user=user
        ).distinct()

    def create(self, request, *args, **kwargs):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required to submit a payment request.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = PaymentRequestSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment_req = SubscriptionService.submit_payment_request(
            tenant=tenant,
            plan=serializer.validated_data["plan_id"],
            billing_cycle=serializer.validated_data["billing_cycle"],
            transaction_id=serializer.validated_data["transaction_id"],
            payment_method=serializer.validated_data["payment_method"],
            amount=serializer.validated_data["amount"],
            proof_attachment=serializer.validated_data.get("proof_attachment", ""),
            submitted_by=request.user,
        )

        return Response(
            PaymentRequestSerializer(payment_req).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied("Only platform super admins can approve payment requests.")

        sub = SubscriptionService.approve_payment_request(
            payment_request_id=pk,
            reviewer=request.user,
        )
        return Response(
            {
                "detail": "Payment request approved and subscription successfully activated.",
                "subscription": TenantSubscriptionSerializer(sub).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied("Only platform super admins can reject payment requests.")

        serializer = PaymentRequestRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment_req = SubscriptionService.reject_payment_request(
            payment_request_id=pk,
            reviewer=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(
            {
                "detail": "Payment request rejected.",
                "payment_request": PaymentRequestSerializer(payment_req).data,
            },
            status=status.HTTP_200_OK,
        )


class SubscriptionNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /subscriptions/notifications/
    POST /subscriptions/notifications/process-checks/
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    serializer_class = SubscriptionNotificationSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return SubscriptionNotification.objects.none()
        return SubscriptionNotification.objects.filter(tenant_id=tenant_id)

    @action(detail=False, methods=["post"], url_path="process-checks")
    def process_checks(self, request):
        created_notifs = SubscriptionService.process_expiration_notifications()
        return Response(
            {
                "detail": f"Processed expiration checks. {len(created_notifs)} notifications generated.",
                "new_notifications_count": len(created_notifs),
            },
            status=status.HTTP_200_OK,
        )
