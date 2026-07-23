from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID | None
    user_id: UUID | None
    is_super_admin: bool = False


_current_context: ContextVar[TenantContext | None] = ContextVar(
    "current_tenant_context", default=None
)


def set_tenant_context(context: TenantContext) -> Token:
    return _current_context.set(context)


def get_tenant_context() -> TenantContext | None:
    return _current_context.get()


def reset_tenant_context(token: Token) -> None:
    _current_context.reset(token)


def require_tenant_id() -> UUID:
    context = get_tenant_context()
    if context is None or context.tenant_id is None:
        raise RuntimeError("A tenant context is required for this query.")
    return context.tenant_id
