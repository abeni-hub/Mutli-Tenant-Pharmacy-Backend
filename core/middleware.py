from uuid import UUID

from django.http import JsonResponse

from core.tenant_context import TenantContext, reset_tenant_context, set_tenant_context


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_tenant_id = request.headers.get("X-Tenant-ID")
        tenant_id = None
        if raw_tenant_id:
            try:
                tenant_id = UUID(raw_tenant_id)
            except ValueError:
                return JsonResponse(
                    {"error": "A valid tenant identifier is required."}, status=400
                )

        request.tenant_id = tenant_id
        token = set_tenant_context(
            TenantContext(tenant_id=tenant_id, user_id=None)
        )
        try:
            return self.get_response(request)
        finally:
            reset_tenant_context(token)
