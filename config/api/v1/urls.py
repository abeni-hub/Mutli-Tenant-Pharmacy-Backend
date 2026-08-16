from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    LoginHistoryViewSet,
    LoginView,
    LogoutView,
    MeViewSet,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PermissionCatalogViewSet,
    RegistrationViewSet,
    SetupPasswordView,
    TenantRoleViewSet,
)
from apps.catalog.views import ProductViewSet
from apps.purchases.views import GoodsReceiptViewSet, PurchaseOrderViewSet, SupplierViewSet
from apps.tenants.views import PlatformBranchViewSet, PlatformPaymentViewSet, PlatformTenantViewSet, PlatformUserViewSet, PlatformViewSet, TenantContextViewSet, TenantUserViewSet, TenantViewSet, UserInvitationViewSet

router = DefaultRouter()

# ── Auth & RBAC ───────────────────────────────────────────────────────────────
router.register("auth/register", RegistrationViewSet, basename="registration")
router.register("auth/me", MeViewSet, basename="me")
router.register("auth/login-history", LoginHistoryViewSet, basename="login-history")
router.register("permissions", PermissionCatalogViewSet, basename="permissions")
router.register("roles", TenantRoleViewSet, basename="roles")

# ── Tenants ───────────────────────────────────────────────────────────────────
router.register("tenants/invitations", UserInvitationViewSet, basename="tenant-invitation")
router.register("tenants/users", TenantUserViewSet, basename="tenant-user")
router.register("tenants", TenantViewSet, basename="tenant")
router.register("tenant-context", TenantContextViewSet, basename="tenant-context")
router.register("platform/tenants", PlatformTenantViewSet, basename="platform-tenant")
router.register("platform/payments", PlatformPaymentViewSet, basename="platform-payment")
router.register("platform/branches", PlatformBranchViewSet, basename="platform-branch")
router.register("platform/users", PlatformUserViewSet, basename="platform-user")
router.register("platform", PlatformViewSet, basename="platform")

# ── Catalog ───────────────────────────────────────────────────────────────────
router.register("products", ProductViewSet, basename="product")

# ── Subscriptions ─────────────────────────────────────────────────────────────
from apps.subscriptions.views import (
    PaymentRequestViewSet,
    SubscriptionNotificationViewSet,
    SubscriptionPlanViewSet,
    TenantSubscriptionViewSet,
)

router.register("subscriptions/plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register("subscriptions/current", TenantSubscriptionViewSet, basename="subscription-current")
router.register("subscriptions/payment-requests", PaymentRequestViewSet, basename="subscription-payment-request")
router.register("subscriptions/notifications", SubscriptionNotificationViewSet, basename="subscription-notification")

# ── Inventory ─────────────────────────────────────────────────────────────────
from apps.inventory.views import InventoryLogViewSet, StockBatchViewSet

router.register("inventory/batches", StockBatchViewSet, basename="inventory-batch")
router.register("inventory/logs", InventoryLogViewSet, basename="inventory-log")

# ── Purchasing ─────────────────────────────────────────────────────────────
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("purchases", PurchaseOrderViewSet, basename="purchase")
router.register("goods-receipts", GoodsReceiptViewSet, basename="goods-receipt")

# ── Sales ─────────────────────────────────────────────────────────────────────
from apps.sales.views import SaleViewSet

router.register("sales", SaleViewSet, basename="sale")

# ── Reports & Analytics ───────────────────────────────────────────────────────
from apps.reports.views import DashboardViewSet, ReportViewSet

router.register("dashboard", DashboardViewSet, basename="dashboard")
router.register("reports", ReportViewSet, basename="report")



app_name = "v1"

urlpatterns = [
    # JWT — obtain / refresh / logout
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/login/", LoginView.as_view(), name="auth-login-slash"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout-slash"),
    path("auth/token/refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh-slash"),

    # Password reset & setup
    path("auth/password/reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("auth/password/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("auth/setup-password/", SetupPasswordView.as_view(), name="auth-setup-password"),
    path("auth/setup-password", SetupPasswordView.as_view(), name="auth-setup-password-noslash"),
    path("auth/change-password/", PasswordChangeView.as_view(), name="auth-change-password"),
    path("auth/change-password", PasswordChangeView.as_view(), name="auth-change-password-noslash"),

    # Router-based endpoints
    # Support no-trailing-slash for router-registered auth/me and tenants
    path("auth/me", MeViewSet.as_view({"get": "list"}), name="auth-me-noslash"),
    path("tenants", TenantViewSet.as_view({"get": "list", "post": "create"}), name="tenant-noslash"),

    path("", include(router.urls)),
]
