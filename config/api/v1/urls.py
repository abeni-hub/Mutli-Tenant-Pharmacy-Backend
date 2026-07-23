from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import LoginView, MeViewSet, RegistrationViewSet
from apps.catalog.views import ProductViewSet
from apps.tenants.views import TenantContextViewSet, TenantViewSet

router = DefaultRouter()
router.register("auth/register", RegistrationViewSet, basename="registration")
router.register("auth/me", MeViewSet, basename="me")
router.register("tenants", TenantViewSet, basename="tenant")
router.register("tenant-context", TenantContextViewSet, basename="tenant-context")
router.register("products", ProductViewSet, basename="product")

app_name = "v1"

urlpatterns = [
    path("auth/token/", LoginView.as_view(), name="token-obtain-pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("", include(router.urls)),
]
