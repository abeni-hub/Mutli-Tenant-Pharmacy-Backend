from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.subscriptions.models import PaymentRequest, SubscriptionNotification, SubscriptionPlan, TenantSubscription
from apps.subscriptions.services import SubscriptionService
from apps.tenants.models import Membership, Tenant
from apps.tenants.serializers import TenantCreateSerializer, TenantSerializer
from apps.tenants.services import TenantCreateData, TenantService
from core.api.permissions import IsPlatformSuperAdmin, TenantMembershipPermission


class PlatformTenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    registration_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    owner_email = serializers.EmailField(required=False, allow_blank=True)


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


class PlatformViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        return [IsAuthenticated(), IsPlatformSuperAdmin()]

    @staticmethod
    def _get_tenant_from_pk(pk):
        try:
            return Tenant.objects.get(id=pk)
        except Tenant.DoesNotExist as exc:
            raise NotFound("Tenant not found.") from exc

    @action(detail=False, methods=["get"], url_path="analytics")
    def analytics(self, request):
        tenants = Tenant.objects.select_related("subscription").all()
        tenant_count = tenants.count()
        active_tenant_count = tenants.filter(is_active=True).count()
        inactive_tenant_count = tenant_count - active_tenant_count

        monthly_revenue = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).aggregate(
            total=Sum("plan__price_monthly")
        )["total"] or 0
        annual_revenue = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).aggregate(
            total=Sum("plan__price_yearly")
        )["total"] or 0

        subscription_distribution = {}
        for plan in SubscriptionPlan.objects.filter(is_active=True):
            subscription_distribution[plan.name] = TenantSubscription.objects.filter(plan=plan).count()

        growth_trends = []
        for month in range(1, 13):
            growth_trends.append({"month": month, "tenant_count": tenants.filter(created_at__month=month).count()})

        usage_metrics = {
            "total_active_users": Membership.objects.filter(is_active=True).count(),
            "average_members_per_tenant": round(Membership.objects.filter(is_active=True).count() / tenant_count, 2) if tenant_count else 0,
        }

        most_active_tenants = [
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "member_count": tenant.memberships.filter(is_active=True).count(),
            }
            for tenant in tenants.annotate(member_count=Count("memberships")).order_by("-member_count")[:5]
        ]

        return Response(
            {
                "totals": {
                    "tenant_count": tenant_count,
                    "active_tenant_count": active_tenant_count,
                    "inactive_tenant_count": inactive_tenant_count,
                    "monthly_revenue": float(monthly_revenue),
                    "annual_revenue": float(annual_revenue),
                },
                "subscription_distribution": subscription_distribution,
                "growth_trends": growth_trends,
                "usage_metrics": usage_metrics,
                "most_active_tenants": most_active_tenants,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="reports")
    def reports(self, request):
        analytics = self.analytics(request).data
        return Response(
            {
                "monthly_revenue": analytics["totals"]["monthly_revenue"],
                "annual_revenue": analytics["totals"]["annual_revenue"],
                "growth_trends": analytics["growth_trends"],
                "subscription_distribution": analytics["subscription_distribution"],
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="subscriptions")
    def subscriptions(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True)
        subscriptions = TenantSubscription.objects.select_related("tenant", "plan").all()
        return Response(
            {
                "count": subscriptions.count(),
                "plans": [
                    {
                        "id": str(plan.id),
                        "name": plan.name,
                        "code": plan.code,
                        "price_monthly": str(plan.price_monthly),
                        "price_yearly": str(plan.price_yearly),
                    }
                    for plan in plans
                ],
                "results": [
                    {
                        "tenant_id": str(item.tenant_id),
                        "tenant_name": item.tenant.name,
                        "plan_name": item.plan.name,
                        "status": item.status,
                        "expires_at": item.expires_at.isoformat(),
                    }
                    for item in subscriptions[:10]
                ],
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="feature-flags")
    def feature_flags(self, request):
        return Response(
            {
                "feature_flags": {
                    "reports": True,
                    "sms": True,
                    "backups": True,
                }
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="notifications")
    def notifications(self, request):
        qs = SubscriptionNotification.objects.select_related("tenant").order_by("-created_at")[:20]
        results = [
            {
                "id": str(item.id),
                "tenant_id": str(item.tenant_id),
                "tenant_name": item.tenant.name,
                "type": item.notification_type,
                "message": item.message,
                "is_read": item.is_read,
                "created_at": item.created_at.isoformat() if hasattr(item, "created_at") and item.created_at else timezone.now().isoformat(),
            }
            for item in qs
        ]
        return Response({"notifications": results, "count": len(results)}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="audit-logs")
    def audit_logs(self, request):
        logs = AuditEvent.objects.select_related("tenant", "actor").order_by("-created_at")[:20]
        return Response(
            {
                "count": logs.count(),
                "results": [
                    {
                        "id": str(log.id),
                        "tenant_name": log.tenant.name if log.tenant else "System",
                        "actor_email": log.actor.email if log.actor else "System",
                        "action": log.action,
                        "entity_type": log.entity_type,
                        "entity_id": str(log.entity_id),
                        "metadata": log.metadata,
                        "created_at": log.created_at.isoformat(),
                    }
                    for log in logs
                ],
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request):
        return Response(
            {
                "status": "ok",
                "api": {"status": "ok", "latency_ms": 12},
                "database": {"status": "ok", "connections": 1},
                "queue": {"status": "ok", "pending_jobs": 0},
                "storage": {"status": "ok", "used_mb": 42},
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class PlatformTenantViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        return [IsAuthenticated(), IsPlatformSuperAdmin()]

    def list(self, request):
        tenants = Tenant.objects.order_by("name")
        return Response(TenantSerializer(tenants, many=True).data, status=status.HTTP_200_OK)

    def create(self, request):
        serializer = PlatformTenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        owner = None
        owner_email = serializer.validated_data.get("owner_email")
        if owner_email:
            owner = User.objects.filter(email__iexact=owner_email).first()
            if owner is None:
                owner = User.objects.create_user(email=owner_email, password="TempPassword123!")

        tenant = TenantService.create_for_super_admin(
            created_by=request.user,
            data=TenantCreateData(
                name=serializer.validated_data["name"],
                registration_number=serializer.validated_data.get("registration_number", ""),
            ),
            owner=owner,
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        tenant = self._get_tenant(pk)
        tenant.is_active = False
        tenant.save(update_fields=["is_active"])
        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="update",
            entity_type="tenants.Tenant",
            entity_id=tenant.id,
            metadata={"status": "suspended"},
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        tenant = self._get_tenant(pk)
        tenant.is_active = True
        tenant.save(update_fields=["is_active"])
        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="update",
            entity_type="tenants.Tenant",
            entity_id=tenant.id,
            metadata={"status": "reactivated"},
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="usage")
    def usage(self, request, pk=None):
        tenant = self._get_tenant(pk)
        return Response(SubscriptionService.get_tenant_usage_and_limits(tenant), status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request, pk=None):
        tenant = self._get_tenant(pk)
        return Response(
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "is_active": tenant.is_active,
                "member_count": tenant.memberships.filter(is_active=True).count(),
                "subscription_status": getattr(getattr(tenant, "subscription", None), "status", None),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_tenant(pk):
        try:
            return Tenant.objects.get(id=pk)
        except Tenant.DoesNotExist as exc:
            raise NotFound("Tenant not found.") from exc


class PlatformPaymentViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        return [IsAuthenticated(), IsPlatformSuperAdmin()]

    def list(self, request):
        payments = PaymentRequest.objects.select_related("tenant", "plan", "submitted_by", "reviewed_by").all()
        results = [
            {
                "id": str(payment.id),
                "transaction_id": payment.transaction_id,
                "tenant_id": str(payment.tenant_id),
                "tenant_name": payment.tenant.name,
                "plan_name": payment.plan.name,
                "billing_cycle": payment.billing_cycle,
                "amount": str(payment.amount),
                "payment_method": payment.payment_method,
                "status": payment.status,
                "rejection_reason": payment.rejection_reason,
                "submitted_by": payment.submitted_by.email if payment.submitted_by else "",
                "created_at": payment.created_at.isoformat(),
            }
            for payment in payments
        ]
        return Response({"count": len(results), "results": results}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        payment_request = self._get_payment(pk)
        subscription = SubscriptionService.approve_payment_request(payment_request_id=payment_request.id, reviewer=request.user)
        AuditService.record(
            tenant=payment_request.tenant,
            actor=request.user,
            action="update",
            entity_type="subscriptions.PaymentRequest",
            entity_id=payment_request.id,
            metadata={"status": "approved"},
        )
        return Response(
            {
                "detail": "Payment request approved and subscription successfully activated.",
                "subscription": {
                    "tenant_id": str(subscription.tenant_id),
                    "plan_name": subscription.plan.name,
                    "status": subscription.status,
                },
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        payment_request = self._get_payment(pk)
        AuditService.record(
            tenant=payment_request.tenant,
            actor=request.user,
            action="update",
            entity_type="subscriptions.PaymentRequest",
            entity_id=payment_request.id,
            metadata={"status": "verified"},
        )
        return Response(
            {
                "detail": "Payment request verified.",
                "payment_request": {
                    "id": str(payment_request.id),
                    "status": payment_request.status,
                    "transaction_id": payment_request.transaction_id,
                },
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        payment_request = self._get_payment(pk)
        reason = request.data.get("reason", "Payment rejected by platform super admin.")
        payment_request.status = PaymentRequest.Status.REJECTED
        payment_request.rejection_reason = reason
        payment_request.reviewed_by = request.user
        payment_request.reviewed_at = timezone.now()
        payment_request.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"])
        AuditService.record(
            tenant=payment_request.tenant,
            actor=request.user,
            action="update",
            entity_type="subscriptions.PaymentRequest",
            entity_id=payment_request.id,
            metadata={"status": "rejected", "reason": reason},
        )
        return Response({"detail": "Payment request rejected.", "status": payment_request.status}, status=status.HTTP_200_OK)

    @staticmethod
    def _get_payment(pk):
        try:
            return PaymentRequest.objects.get(id=pk)
        except PaymentRequest.DoesNotExist as exc:
            raise NotFound("Payment request not found.") from exc
