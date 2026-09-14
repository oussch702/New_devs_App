"""
Minimal tenant resolver for authentication.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TenantResolver:
    """Minimal tenant resolver that extracts tenant_id from JWT claims."""

    @staticmethod
    def resolve_tenant_from_token(token_payload: dict) -> Optional[str]:
        """
        Extract tenant_id from JWT token payload.

        Args:
            token_payload: Decoded JWT payload

        Returns:
            Tenant ID if found, None otherwise
        """
        # Only call this with verified claims. user_metadata is user-editable
        # and must never determine which company's data a request can access.
        app_metadata = token_payload.get('app_metadata') or {}
        tenant_id = app_metadata.get('tenant_id') if isinstance(app_metadata, dict) else None
        if tenant_id is None:
            tenant_id = token_payload.get('tenant_id')
        if isinstance(tenant_id, str) and tenant_id.strip():
            return tenant_id.strip()

        logger.warning("No tenant_id found in token payload")
        return None

    @staticmethod
    def resolve_tenant_from_user(user_data: dict) -> Optional[str]:
        """
        Extract tenant_id from user data.

        Args:
            user_data: User data dictionary

        Returns:
            Tenant ID if found, None otherwise
        """
        return TenantResolver.resolve_tenant_from_token(user_data)

    @staticmethod
    async def resolve_tenant_id(
        user_id: str,
        user_email: str,
        token: Optional[str] = None,
        *,
        verified_payload: Optional[dict] = None,
        verified_user=None,
    ) -> Optional[str]:
        """
        Resolve tenant ID for a user.
        
        Args:
            user_id: User ID
            user_email: User email
            
        Returns:
            Tenant ID
        """
        # Callers may pass identity already verified by the authentication layer.
        if verified_payload is not None:
            return TenantResolver.resolve_tenant_from_token(verified_payload)
        if verified_user is not None:
            return TenantResolver.resolve_tenant_from_user({
                'app_metadata': getattr(verified_user, 'app_metadata', None),
                'tenant_id': getattr(verified_user, 'tenant_id', None),
            })

        if token:
            from jose import JWTError, jwt
            from ..config import settings

            try:
                payload = jwt.decode(
                    token, settings.secret_key, algorithms=['HS256'],
                    audience='authenticated', options={'require_exp': True, 'require_aud': True},
                )
                if (payload.get('id') or payload.get('sub')) != user_id:
                    return None
                return TenantResolver.resolve_tenant_from_token(payload)
            except JWTError:
                return None

        # An email address is not tenant authorization. Missing trusted context
        # must fail closed instead of silently selecting the first company.
        return None

    @staticmethod
    async def update_user_tenant_metadata(user_id: str, tenant_id: str) -> None:
        """
        Update user metadata with tenant_id.
        
        Args:
            user_id: User ID
            tenant_id: Tenant ID
        """
        # No-op in this resolver implementation.
        pass
