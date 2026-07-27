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


app_name = "v1"

urlpatterns = [
    # JWT — obtain / refresh / logout
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),

    # Password reset
    path("auth/password/reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("auth/password/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # Router-based endpoints
    path("", include(router.urls)),
]
