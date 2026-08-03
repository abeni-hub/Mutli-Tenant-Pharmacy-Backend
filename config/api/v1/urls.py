from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    LoginHistoryViewSet,
    LoginView,
    LogoutView,
    MeViewSet,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegistrationViewSet,
)
from apps.catalog.views import ProductViewSet
from apps.tenants.views import TenantContextViewSet, TenantViewSet

router = DefaultRouter()

# ── Auth ──────────────────────────────────────────────────────────────────────
router.register("auth/register", RegistrationViewSet, basename="registration")
router.register("auth/me", MeViewSet, basename="me")
router.register("auth/login-history", LoginHistoryViewSet, basename="login-history")

# ── Tenants ───────────────────────────────────────────────────────────────────
router.register("tenants", TenantViewSet, basename="tenant")
router.register("tenant-context", TenantContextViewSet, basename="tenant-context")

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

# ── Sales ─────────────────────────────────────────────────────────────────────
from apps.sales.views import SaleViewSet

router.register("sales", SaleViewSet, basename="sale")

# ── Reports & Analytics ───────────────────────────────────────────────────────
from apps.reports.views import ReportViewSet

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

    # Password reset
    path("auth/password/reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("auth/password/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # Router-based endpoints
    # Support no-trailing-slash for router-registered auth/me and tenants
    path("auth/me", MeViewSet.as_view({"get": "list"}), name="auth-me-noslash"),
    path("tenants", TenantViewSet.as_view({"get": "list", "post": "create"}), name="tenant-noslash"),

    path("", include(router.urls)),
]
