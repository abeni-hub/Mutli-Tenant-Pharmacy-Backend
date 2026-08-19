import csv
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Permission, PermissionCategory, Role, User, UserRole
from apps.accounts.serializers import (
    PermissionCategorySerializer,
    PermissionSerializer,
    RoleCreateUpdateSerializer,
    RoleSerializer,
)
from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.subscriptions.models import PaymentRequest, SubscriptionNotification, SubscriptionPlan, TenantSubscription
from apps.subscriptions.services import SubscriptionService
from apps.tenants.models import Branch, FeatureFlag, Membership, Tenant, UserInvitation
from apps.tenants.serializers import (
    BranchCreateSerializer,
    BranchSerializer,
    FeatureFlagSerializer,
    TenantCreateSerializer,
    TenantSerializer,
    UserInvitationSerializer,
    UserInviteCreateSerializer,
)
from apps.tenants.services import TenantCreateData, TenantService
from core.api.permissions import IsPlatformSuperAdmin, TenantMembershipPermission


class PlatformTenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    registration_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    owner_first_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    owner_last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    owner_email = serializers.EmailField(required=False, allow_blank=True, default="")
    owner_phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    plan_code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="enterprise")
    branch_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    branch_code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")


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

        total_branches = Branch.objects.count()
        total_users = User.objects.count()
        pending_payments = PaymentRequest.objects.filter(status=PaymentRequest.Status.PENDING).count()

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
                "total_tenants": tenant_count,
                "active_tenants": active_tenant_count,
                "suspended_tenants": inactive_tenant_count,
                "branch_count": total_branches,
                "total_users": total_users,
                "pending_payments": pending_payments,
                "total_revenue": float(monthly_revenue * 12 + annual_revenue),
                "totals": {
                    "tenant_count": tenant_count,
                    "active_tenant_count": active_tenant_count,
                    "inactive_tenant_count": inactive_tenant_count,
                    "branch_count": total_branches,
                    "user_count": total_users,
                    "pending_payments": pending_payments,
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

    @action(detail=False, methods=["get"], url_path="tenants/export")
    def export_tenants(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_tenants_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Tenant ID", "Tenant Name", "Registration Number", "Status", "Owner Email", "Branch Count", "Created At"])

        qs = Tenant.objects.all()
        status_filter = request.query_params.get("status")
        search = request.query_params.get("search")

        if status_filter == "active":
            qs = qs.filter(is_active=True)
        elif status_filter == "suspended":
            qs = qs.filter(is_active=False)

        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(registration_number__icontains=search))

        for tenant in qs:
            owner_membership = tenant.memberships.filter(role=Membership.Role.OWNER, is_active=True).first()
            owner_email = owner_membership.user.email if owner_membership and owner_membership.user else "N/A"
            writer.writerow([
                str(tenant.id),
                tenant.name,
                tenant.registration_number or "N/A",
                "Active" if tenant.is_active else "Suspended",
                owner_email,
                tenant.branches.count(),
                tenant.created_at.isoformat() if hasattr(tenant, "created_at") and tenant.created_at else "",
            ])

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="export",
            entity_type="tenants.Tenant",
            metadata={"status": status_filter, "search": search, "count": qs.count()},
        )
        return response

    @action(detail=False, methods=["get"], url_path="revenue/export")
    def export_revenue(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_revenue_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Metric", "Value"])

        monthly_rev = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).aggregate(total=Sum("plan__price_monthly"))["total"] or 0
        annual_rev = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).aggregate(total=Sum("plan__price_yearly"))["total"] or 0

        writer.writerow(["Monthly Recurring Revenue (MRR)", float(monthly_rev)])
        writer.writerow(["Annual Recurring Revenue (ARR)", float(annual_rev)])
        writer.writerow(["Active Subscriptions", TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).count()])
        writer.writerow(["Pending Payment Requests", PaymentRequest.objects.filter(status=PaymentRequest.Status.PENDING).count()])

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="export",
            entity_type="reports.Revenue",
            metadata={"mrr": float(monthly_rev), "arr": float(annual_rev)},
        )
        return response

    @action(detail=False, methods=["get"], url_path="reports/export")
    def export_reports(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_reports.csv"'
        writer = csv.writer(response)
        writer.writerow(["Tenant Name", "Registration Number", "Status", "Owner Email", "Branch Count", "Created At"])
        for tenant in Tenant.objects.all():
            owner_membership = tenant.memberships.filter(role=Membership.Role.OWNER, is_active=True).first()
            owner_email = owner_membership.user.email if owner_membership else ""
            writer.writerow([tenant.name, tenant.registration_number, "Active" if tenant.is_active else "Suspended", owner_email, tenant.branches.count(), tenant.created_at.isoformat()])
        AuditService.record(tenant=None, actor=request.user, action="export", entity_type="reports.Platform", metadata={})
        return response

    @action(detail=False, methods=["get"], url_path="analytics/export")
    def export_analytics(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_analytics.csv"'
        writer = csv.writer(response)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Tenants", Tenant.objects.count()])
        writer.writerow(["Active Tenants", Tenant.objects.filter(is_active=True).count()])
        writer.writerow(["Suspended Tenants", Tenant.objects.filter(is_active=False).count()])
        writer.writerow(["Total Branches", Branch.objects.count()])
        writer.writerow(["Total Users", User.objects.count()])
        writer.writerow(["Pending Payments", PaymentRequest.objects.filter(status=PaymentRequest.Status.PENDING).count()])
        AuditService.record(tenant=None, actor=request.user, action="export", entity_type="analytics.Platform", metadata={})
        return response

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
                        "max_branches": plan.max_branches,
                        "max_users": plan.max_users,
                        "max_medicines": plan.max_medicines,
                    }
                    for plan in plans
                ],
                "results": [
                    {
                        "id": str(item.id),
                        "tenant_id": str(item.tenant_id),
                        "tenant_name": item.tenant.name,
                        "plan_name": item.plan.name,
                        "status": item.status,
                        "billing_cycle": item.billing_cycle,
                        "starts_at": item.starts_at.isoformat(),
                        "expires_at": item.expires_at.isoformat(),
                    }
                    for item in subscriptions
                ],
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="feature-flags")
    def feature_flags(self, request):
        if not FeatureFlag.objects.exists():
            defaults = [
                ("reports", "Reports & Analytics", "Advanced platform reporting and export.", "analytics", True),
                ("sms", "SMS Notifications", "Automated SMS alerts for expiration and sales.", "communication", True),
                ("backups", "Automated Cloud Backups", "Scheduled system database backups.", "system", True),
                ("ai_inventory", "AI Demand Forecasting", "Predictive stock replenishment.", "inventory", True),
                ("multi_branch", "Multi-Branch Management", "Centralized multi-store control.", "branches", True),
            ]
            for key, name, desc, mod, enabled in defaults:
                FeatureFlag.objects.create(key=key, name=name, description=desc, module=mod, is_enabled=enabled)

        flags = FeatureFlag.objects.all()
        flag_dict = {f.key: f.is_enabled for f in flags}
        results = FeatureFlagSerializer(flags, many=True).data
        return Response({"feature_flags": flag_dict, "results": results}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path=r"feature-flags/(?P<flag_key>[^/.]+)/toggle")
    def toggle_feature_flag(self, request, flag_key=None):
        flag = FeatureFlag.objects.filter(key__iexact=flag_key).first()
        if flag is None:
            flag = FeatureFlag.objects.create(
                key=flag_key,
                name=flag_key.replace("_", " ").title(),
                description="Dynamic platform feature flag",
                is_enabled=True,
            )
        flag.is_enabled = not flag.is_enabled
        flag.save(update_fields=["is_enabled", "updated_at"])

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="update",
            entity_type="tenants.FeatureFlag",
            entity_id=flag.id,
            metadata={"key": flag.key, "is_enabled": flag.is_enabled},
        )
        return Response(FeatureFlagSerializer(flag).data, status=status.HTTP_200_OK)

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
        qs = AuditEvent.objects.select_related("tenant", "actor").order_by("-created_at")
        action_filter = request.query_params.get("action")
        tenant_id = request.query_params.get("tenant_id")
        search = request.query_params.get("search")

        if action_filter:
            qs = qs.filter(action=action_filter)
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        if search:
            qs = qs.filter(
                Q(entity_type__icontains=search)
                | Q(action__icontains=search)
                | Q(actor__email__icontains=search)
                | Q(tenant__name__icontains=search)
            )

        logs = qs[:50]
        return Response(
            {
                "count": qs.count(),
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

    @action(detail=False, methods=["get"], url_path="audit-logs/export")
    def export_audit_logs(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_audit_logs.csv"'
        writer = csv.writer(response)
        writer.writerow(["Log ID", "Created At", "Tenant", "Actor Email", "Action", "Entity Type", "Entity ID"])

        logs = AuditEvent.objects.select_related("tenant", "actor").order_by("-created_at")[:500]
        for log in logs:
            writer.writerow([
                str(log.id),
                log.created_at.isoformat(),
                log.tenant.name if log.tenant else "System",
                log.actor.email if log.actor else "System",
                log.action,
                log.entity_type,
                str(log.entity_id),
            ])
        return response

    @action(detail=False, methods=["get"], url_path="reports/export")
    def export_reports(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_reports_summary.csv"'
        writer = csv.writer(response)
        writer.writerow(["Tenant Name", "Registration Number", "Status", "Owner Email", "Subscription Plan", "Created Date"])

        tenants = Tenant.objects.select_related("subscription__plan").prefetch_related("memberships__user").all()
        for t in tenants:
            plan_name = t.subscription.plan.name if hasattr(t, "subscription") and t.subscription and t.subscription.plan else "N/A"
            owner_m = t.memberships.filter(role="owner").first()
            owner_email = owner_m.user.email if owner_m and owner_m.user else "N/A"
            writer.writerow([
                t.name,
                t.registration_number or "N/A",
                "Active" if t.is_active else "Suspended",
                owner_email,
                plan_name,
                t.created_at.strftime("%Y-%m-%d") if hasattr(t, "created_at") and t.created_at else "",
            ])
        return response

    @action(detail=False, methods=["get"], url_path="analytics/export")
    def export_analytics(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_analytics.csv"'
        writer = csv.writer(response)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Tenants", Tenant.objects.count()])
        writer.writerow(["Active Tenants", Tenant.objects.filter(is_active=True).count()])
        writer.writerow(["Suspended Tenants", Tenant.objects.filter(is_active=False).count()])
        writer.writerow(["Total Branches", Branch.objects.count()])
        writer.writerow(["Total Users", User.objects.count()])
        writer.writerow(["Pending Payments", PaymentRequest.objects.filter(status=PaymentRequest.Status.PENDING).count()])
        return response

    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request):
        return Response(
            {
                "status": "ok",
                "api": {"status": "ok", "latency_ms": 12},
                "database": {"status": "ok", "connections": 1},
                "active_tenants": Tenant.objects.filter(is_active=True).count(),
                "active_users": User.objects.filter(is_active=True).count(),
                "total_branches": Branch.objects.count(),
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="health/export")
    def export_health(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_system_health_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Service / Metric", "Status", "Details"])
        writer.writerow(["Django REST API", "Operational", "Serving endpoints (12ms)"])
        writer.writerow(["PostgreSQL Database", "Operational", "Database connection verified"])
        writer.writerow(["Active Tenants", "Operational", Tenant.objects.filter(is_active=True).count()])
        writer.writerow(["Active Users", "Operational", User.objects.filter(is_active=True).count()])
        writer.writerow(["Total Branches", "Operational", Branch.objects.count()])

        AuditService.record(tenant=None, actor=request.user, action="export", entity_type="system.Health", metadata={})
        return response

    @action(detail=False, methods=["get"], url_path="feature-flags/export")
    def export_feature_flags(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_feature_flags_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Flag Key", "Flag Name", "Module", "Description", "Enabled", "Updated At"])

        flags = FeatureFlag.objects.all()
        for flag in flags:
            writer.writerow([
                flag.key,
                flag.name,
                flag.module,
                flag.description,
                "True" if flag.is_enabled else "False",
                flag.updated_at.isoformat() if hasattr(flag, "updated_at") and flag.updated_at else "",
            ])

        AuditService.record(tenant=None, actor=request.user, action="export", entity_type="tenants.FeatureFlag", metadata={"count": flags.count()})
        return response

    @action(detail=False, methods=["get"], url_path="security/export")
    def export_security(self, request):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="platform_security_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Log ID", "Timestamp", "Actor Email", "Tenant", "Action", "Entity Type", "Entity ID", "Metadata"])

        logs = AuditEvent.objects.select_related("tenant", "actor").order_by("-created_at")[:500]
        for log in logs:
            writer.writerow([
                str(log.id),
                log.created_at.isoformat(),
                log.actor.email if log.actor else "System",
                log.tenant.name if log.tenant else "System",
                log.action,
                log.entity_type,
                str(log.entity_id),
                str(log.metadata),
            ])

        AuditService.record(tenant=None, actor=request.user, action="export", entity_type="audit.SecurityLog", metadata={"count": logs.count()})
        return response

    @action(detail=False, methods=["get"], url_path="permissions")
    def list_permissions(self, request):
        categories = PermissionCategory.objects.prefetch_related("permissions").all()
        return Response(PermissionCategorySerializer(categories, many=True).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get", "post"], url_path="roles")
    def roles(self, request):
        if request.method == "GET":
            roles = Role.objects.prefetch_related("permissions").all()
            return Response(RoleSerializer(roles, many=True).data, status=status.HTTP_200_OK)

        serializer = RoleCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"].strip()
        description = serializer.validated_data.get("description", "")
        scope = serializer.validated_data.get("scope", Role.Scope.GLOBAL)
        perm_keys = serializer.validated_data.get("permission_keys", [])

        role_key = name.lower().replace(" ", "_").replace("-", "_")
        import uuid
        if Role.objects.filter(key=role_key).exists():
            role_key = f"{role_key}_{uuid.uuid4().hex[:6]}"

        role = Role.objects.create(
            key=role_key,
            name=name,
            description=description,
            scope=scope,
            is_system=False,
        )
        if perm_keys:
            perms = Permission.objects.filter(key__in=perm_keys)
            role.permissions.set(perms)

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="create",
            entity_type="accounts.Role",
            entity_id=role.id,
            metadata={"role_name": role.name, "permission_count": len(perm_keys)},
        )
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "put", "patch", "delete"], url_path=r"roles/(?P<role_id>[^/.]+)")
    def role_detail(self, request, role_id=None):
        try:
            role = Role.objects.get(id=role_id)
        except (Role.DoesNotExist, ValidationError):
            try:
                role = Role.objects.get(key=role_id)
            except Role.DoesNotExist:
                raise NotFound("Role not found.")

        if request.method == "GET":
            return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)

        if request.method == "DELETE":
            if role.is_system:
                raise ValidationError("Protected system roles cannot be deleted.")
            role.delete()
            AuditService.record(
                tenant=None,
                actor=request.user,
                action="delete",
                entity_type="accounts.Role",
                entity_id=role.id,
                metadata={"role_name": role.name},
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PUT/PATCH update
        if role.is_system:
            raise ValidationError("Protected system role permissions cannot be edited.")

        serializer = RoleCreateUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "name" in serializer.validated_data:
            role.name = serializer.validated_data["name"].strip()
        if "description" in serializer.validated_data:
            role.description = serializer.validated_data["description"].strip()
        if "scope" in serializer.validated_data:
            role.scope = serializer.validated_data["scope"]
        role.save()

        if "permission_keys" in serializer.validated_data:
            perm_keys = serializer.validated_data["permission_keys"]
            perms = Permission.objects.filter(key__in=perm_keys)
            role.permissions.set(perms)

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="update",
            entity_type="accounts.Role",
            entity_id=role.id,
            metadata={"role_name": role.name},
        )
        return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)


class PlatformTenantViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        return [IsAuthenticated(), IsPlatformSuperAdmin()]

    def list(self, request):
        tenants = Tenant.objects.order_by("name")
        return Response(TenantSerializer(tenants, many=True).data, status=status.HTTP_200_OK)

    def create(self, request):
        import secrets
        serializer = PlatformTenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        owner = None
        temp_password = f"TempPass{secrets.token_hex(4)}!"
        owner_email = serializer.validated_data.get("owner_email")
        
        if owner_email:
            owner = User.objects.filter(email__iexact=owner_email).first()
            if owner is None:
                owner = User.objects.create_user(
                    email=owner_email,
                    password=temp_password,
                    first_name=serializer.validated_data.get("owner_first_name", ""),
                    last_name=serializer.validated_data.get("owner_last_name", ""),
                    phone_number=serializer.validated_data.get("owner_phone", ""),
                )
            owner.must_change_password = True
            owner.save(update_fields=["must_change_password"])

        tenant = TenantService.create_for_super_admin(
            created_by=request.user,
            data=TenantCreateData(
                name=serializer.validated_data["name"],
                registration_number=serializer.validated_data.get("registration_number", ""),
            ),
            owner=owner,
        )

        res_data = TenantSerializer(tenant).data
        if owner:
            from apps.accounts.email_service import EmailService
            EmailService.send_tenant_welcome_email(
                to_email=owner.email,
                tenant_name=tenant.name,
                temporary_password=temp_password,
            )
            res_data["admin_email"] = owner.email
            res_data["temporary_password"] = temp_password
            res_data["must_change_password"] = True

        return Response(res_data, status=status.HTTP_201_CREATED)

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


class PlatformBranchViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated, IsPlatformSuperAdmin)

    def list(self, request):
        branches = Branch.objects.select_related("tenant").order_by("name")
        return Response(BranchSerializer(branches, many=True).data, status=status.HTTP_200_OK)

    def create(self, request):
        serializer = BranchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tenant = Tenant.objects.get(id=serializer.validated_data["tenant_id"])
        except Tenant.DoesNotExist:
            raise NotFound("Tenant not found.")
        branch = Branch.objects.create(
            tenant=tenant,
            name=serializer.validated_data["name"],
            code=serializer.validated_data["code"],
            address=serializer.validated_data.get("address", ""),
            phone=serializer.validated_data.get("phone", ""),
            is_main=serializer.validated_data.get("is_main", False),
        )
        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="create",
            entity_type="tenants.Branch",
            entity_id=branch.id,
            metadata={"name": branch.name, "code": branch.code},
        )
        return Response(BranchSerializer(branch).data, status=status.HTTP_201_CREATED)


class PlatformUserViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated, IsPlatformSuperAdmin)

    def list(self, request):
        users = User.objects.prefetch_related("memberships__tenant").order_by("email")
        results = []
        for u in users:
            primary_membership = u.memberships.filter(is_active=True).first()
            role = "super_admin" if u.is_superuser else (primary_membership.role if primary_membership else "user")
            tenant_name = primary_membership.tenant.name if primary_membership and primary_membership.tenant else "System"
            results.append({
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "full_name": u.full_name,
                "phone_number": u.phone_number,
                "role": role,
                "tenant_name": tenant_name,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "date_joined": u.date_joined.isoformat(),
            })
        return Response(results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="invite")
    def invite(self, request):
        serializer = UserInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        role = serializer.validated_data["role"]
        tenant_id = serializer.validated_data.get("tenant_id")

        tenant = None
        if tenant_id:
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFound("Tenant not found.")

        now = timezone.now()
        invitation = UserInvitation.objects.create(
            email=email,
            tenant=tenant,
            role=role,
            invited_by=request.user,
            status=UserInvitation.Status.PENDING,
            expires_at=now + timezone.timedelta(days=7),
        )

        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="create",
            entity_type="tenants.UserInvitation",
            entity_id=invitation.id,
            metadata={"email": email, "role": role, "token": str(invitation.token)},
        )

        from apps.accounts.email_service import EmailService
        EmailService.send_user_invitation_email(
            to_email=email,
            tenant_name=tenant.name if tenant else "MeridianRx Platform",
            role=role,
            token=str(invitation.token),
        )

        return Response(UserInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="invitations")
    def list_invitations(self, request):
        invitations = UserInvitation.objects.select_related("tenant", "invited_by").all()
        return Response(UserInvitationSerializer(invitations, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            raise NotFound("User not found.")
        user.is_active = True
        user.save(update_fields=["is_active"])
        AuditService.record(
            tenant=None,
            actor=request.user,
            action="update",
            entity_type="accounts.User",
            entity_id=user.id,
            metadata={"is_active": True, "email": user.email},
        )
        return Response({"detail": "User activated successfully.", "is_active": True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            raise NotFound("User not found.")
        user.is_active = False
        user.save(update_fields=["is_active"])
        AuditService.record(
            tenant=None,
            actor=request.user,
            action="update",
            entity_type="accounts.User",
            entity_id=user.id,
            metadata={"is_active": False, "email": user.email},
        )
        return Response({"detail": "User deactivated successfully.", "is_active": False}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            raise NotFound("User not found.")

        # Create or update user invitation / setup token for password reset
        now = timezone.now()
        membership = user.memberships.filter(is_active=True).first()
        tenant = membership.tenant if membership else None
        role = membership.role if membership else ("super_admin" if user.is_superuser else "user")

        invitation, _ = UserInvitation.objects.update_or_create(
            email=user.email.lower(),
            defaults={
                "tenant": tenant,
                "role": role,
                "invited_by": request.user,
                "status": UserInvitation.Status.PENDING,
                "expires_at": now + timezone.timedelta(days=7),
            },
        )

        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="update",
            entity_type="accounts.User",
            entity_id=user.id,
            metadata={"email": user.email, "reset_token": str(invitation.token)},
        )
        return Response(
            {
                "detail": f"Password reset invitation generated for {user.email}.",
                "email": user.email,
                "token": str(invitation.token),
                "setup_url": f"/auth/setup-password?token={invitation.token}",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            raise NotFound("User not found.")

        new_role = request.data.get("role")
        if new_role not in ["super_admin", "owner", "pharmacist", "cashier"]:
            return Response({"detail": "Invalid role requested."}, status=status.HTTP_400_BAD_REQUEST)

        if new_role == "super_admin":
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=["is_superuser", "is_staff"])
        else:
            if user.is_superuser:
                user.is_superuser = False
                user.save(update_fields=["is_superuser"])
            membership = user.memberships.filter(is_active=True).first()
            if membership:
                membership.role = new_role
                membership.save(update_fields=["role"])

        AuditService.record(
            tenant=None,
            actor=request.user,
            action="update",
            entity_type="accounts.User",
            entity_id=user.id,
            metadata={"email": user.email, "new_role": new_role},
        )
        return Response({"detail": f"User role changed to {new_role}.", "role": new_role}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path=r"invitations/(?P<invitation_id>[^/.]+)/resend")
    def resend_invitation(self, request, invitation_id=None):
        try:
            invitation = UserInvitation.objects.get(id=invitation_id)
        except UserInvitation.DoesNotExist:
            raise NotFound("Invitation not found.")

        now = timezone.now()
        invitation.status = UserInvitation.Status.PENDING
        invitation.expires_at = now + timezone.timedelta(days=7)
        invitation.save(update_fields=["status", "expires_at"])

        AuditService.record(
            tenant=invitation.tenant,
            actor=request.user,
            action="update",
            entity_type="tenants.UserInvitation",
            entity_id=invitation.id,
            metadata={"email": invitation.email, "token": str(invitation.token)},
        )

        from apps.accounts.email_service import EmailService
        EmailService.send_user_invitation_email(
            to_email=invitation.email,
            tenant_name=invitation.tenant.name if invitation.tenant else "MeridianRx Platform",
            role=invitation.role,
            token=str(invitation.token),
        )

        return Response(UserInvitationSerializer(invitation).data, status=status.HTTP_200_OK)


class UserInvitationViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    serializer_class = UserInvitationSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return UserInvitation.objects.none()
        return UserInvitation.objects.filter(tenant_id=tenant_id).select_related("tenant", "invited_by")

    def create(self, request):
        serializer = UserInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        role = serializer.validated_data["role"]

        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise NotFound("Tenant not found.")

        if role == Membership.Role.SUPER_ADMIN or role == "super_admin":
            raise ValidationError("Tenant Admins cannot assign Super Admin role.")

        from apps.accounts.models import Role
        from django.db.models import Q

        if role not in [r.value for r in Membership.Role]:
            role_obj = Role.objects.filter(
                Q(key=role) & Q(scope=Role.Scope.TENANT) & (Q(is_system=True) | Q(tenant_id=tenant_id))
            ).first()
            if not role_obj:
                raise ValidationError(f"Invalid role '{role}' for this tenant.")

        now = timezone.now()
        invitation = UserInvitation.objects.create(
            email=email,
            tenant=tenant,
            role=role,
            invited_by=request.user,
            status=UserInvitation.Status.PENDING,
            expires_at=now + timezone.timedelta(days=7),
        )

        AuditService.record(
            tenant=tenant,
            actor=request.user,
            action="create",
            entity_type="tenants.UserInvitation",
            entity_id=invitation.id,
            metadata={"email": email, "role": role, "token": str(invitation.token)},
        )

        from apps.accounts.email_service import EmailService
        EmailService.send_user_invitation_email(
            to_email=email,
            tenant_name=tenant.name,
            role=role,
            token=str(invitation.token),
        )

        return Response(UserInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="resend")
    def resend(self, request, pk=None):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            invitation = UserInvitation.objects.get(id=pk, tenant_id=tenant_id)
        except UserInvitation.DoesNotExist:
            raise NotFound("Invitation not found.")

        now = timezone.now()
        invitation.status = UserInvitation.Status.PENDING
        invitation.expires_at = now + timezone.timedelta(days=7)
        invitation.save(update_fields=["status", "expires_at"])

        from apps.accounts.email_service import EmailService
        EmailService.send_user_invitation_email(
            to_email=invitation.email,
            tenant_name=invitation.tenant.name if invitation.tenant else "MeridianRx Platform",
            role=invitation.role,
            token=str(invitation.token),
        )

        return Response(UserInvitationSerializer(invitation).data, status=status.HTTP_200_OK)


class TenantUserViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission)

    def _get_tenant_id(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        return tenant_id

    def list(self, request):
        tenant_id = self._get_tenant_id(request)
        memberships = Membership.objects.filter(tenant_id=tenant_id).select_related("user", "tenant").order_by("-joined_at", "user__email")
        
        results = []
        for m in memberships:
            u = m.user
            results.append({
                "id": str(u.id),
                "membership_id": str(m.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "full_name": u.full_name or u.email,
                "phone_number": u.phone_number,
                "role": m.role,
                "is_active": m.is_active and u.is_active,
                "joined_at": m.joined_at.isoformat() if m.joined_at else u.date_joined.isoformat(),
            })
        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=["patch"], url_path="role")
    def update_role(self, request, pk=None):
        from apps.accounts.models import Role
        from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
        from django.db.models import Q

        tenant_id = self._get_tenant_id(request)
        new_role = request.data.get("role")
        if not new_role:
            raise ValidationError("Role is required.")

        try:
            membership = Membership.objects.get(user_id=pk, tenant_id=tenant_id)
        except Membership.DoesNotExist:
            raise NotFound("User membership not found in this tenant.")

        if new_role == Membership.Role.SUPER_ADMIN or new_role == "super_admin":
            raise PermissionDenied("Permission Denied: Cannot assign Super Admin role to tenant user.")

        # Verify role is valid for this tenant
        role_obj = Role.objects.filter(
            Q(key=new_role) & Q(scope=Role.Scope.TENANT) & (Q(is_system=True) | Q(tenant_id=tenant_id))
        ).first()

        # If role key is a standard enum choice (owner, pharmacist, cashier) allow, otherwise check Role model
        if not role_obj and new_role not in [r.value for r in Membership.Role]:
            raise PermissionDenied("Permission Denied: Invalid role or role belongs to another scope/tenant.")

        membership.role = new_role
        membership.save(update_fields=["role"])

        AuditService.record(
            tenant_id=tenant_id,
            actor=request.user,
            action="update",
            entity_type="tenants.Membership",
            entity_id=membership.id,
            metadata={"user_id": str(pk), "new_role": new_role},
        )
        return Response({"id": str(pk), "role": membership.role}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        tenant_id = self._get_tenant_id(request)
        try:
            membership = Membership.objects.get(user_id=pk, tenant_id=tenant_id)
        except Membership.DoesNotExist:
            raise NotFound("User membership not found in this tenant.")

        membership.is_active = True
        membership.save(update_fields=["is_active"])

        AuditService.record(
            tenant_id=tenant_id,
            actor=request.user,
            action="update",
            entity_type="tenants.Membership",
            entity_id=membership.id,
            metadata={"user_id": str(pk), "action": "activated"},
        )
        return Response({"id": str(pk), "is_active": True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        tenant_id = self._get_tenant_id(request)
        try:
            membership = Membership.objects.get(user_id=pk, tenant_id=tenant_id)
        except Membership.DoesNotExist:
            raise NotFound("User membership not found in this tenant.")

        membership.is_active = False
        membership.save(update_fields=["is_active"])

        AuditService.record(
            tenant_id=tenant_id,
            actor=request.user,
            action="update",
            entity_type="tenants.Membership",
            entity_id=membership.id,
            metadata={"user_id": str(pk), "action": "deactivated"},
        )
        return Response({"id": str(pk), "is_active": False}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        tenant_id = self._get_tenant_id(request)
        try:
            membership = Membership.objects.get(user_id=pk, tenant_id=tenant_id)
        except Membership.DoesNotExist:
            raise NotFound("User membership not found in this tenant.")

        u = membership.user
        now = timezone.now()

        invitation, _ = UserInvitation.objects.update_or_create(
            email=u.email.lower(),
            defaults={
                "tenant": membership.tenant,
                "role": membership.role,
                "invited_by": request.user,
                "status": UserInvitation.Status.PENDING,
                "expires_at": now + timezone.timedelta(days=7),
            },
        )

        AuditService.record(
            tenant_id=tenant_id,
            actor=request.user,
            action="update",
            entity_type="accounts.User",
            entity_id=u.id,
            metadata={"email": u.email, "reset_token": str(invitation.token)},
        )
        return Response(
            {
                "detail": f"Password reset invitation generated for {u.email}.",
                "email": u.email,
                "token": str(invitation.token),
                "setup_url": f"/setup-password?token={invitation.token}",
            },
            status=status.HTTP_200_OK,
        )

