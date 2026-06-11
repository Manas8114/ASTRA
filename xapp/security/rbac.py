import os
import logging
from fastapi import Request, HTTPException, Depends

log = logging.getLogger("astra.rbac")

# In production, this integrates with Keycloak or an OAuth2 provider
# Here we simulate simple RBAC via headers or static tokens
ADMIN_TOKEN = os.getenv("ASTRA_ADMIN_TOKEN", "admin-secret-token")
VIEWER_TOKEN = os.getenv("ASTRA_VIEWER_TOKEN", "viewer-secret-token")
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "https://keycloak.local/realms/astra")

class Role:
    ADMIN = "admin"
    VIEWER = "viewer"

def verify_oidc_token(token: str) -> dict:
    """Stub for OIDC JWT verification using JWKS from Keycloak/Okta."""
    # In a real implementation:
    # from jose import jwt
    # jwks = fetch_jwks(OIDC_ISSUER)
    # return jwt.decode(token, jwks, algorithms=["RS256"], audience="astra-xapp")
    log.debug("OIDC verification stub called.")
    return {"sub": "user123", "realm_access": {"roles": ["admin"]}}

def verify_mtls_cert(request: Request) -> bool:
    """Stub to check for client certificates from the reverse proxy (e.g. Envoy/Nginx)."""
    # Normally the proxy forwards the client cert thumbprint in a header like X-Forwarded-Client-Cert
    cert_header = request.headers.get("X-Forwarded-Client-Cert")
    if not cert_header and os.getenv("ASTRA_MODE") == "prod":
        log.warning("Missing mTLS client certificate header.")
        return False
    return True

def get_current_role(request: Request) -> str:
    # 1. Enforce mTLS check in prod
    if os.getenv("ASTRA_MODE") == "prod":
        if not verify_mtls_cert(request):
            raise HTTPException(status_code=403, detail="Forbidden: Valid mTLS client certificate required")

    token = request.headers.get("Authorization")
    if not token:
        # For dev mode, default to admin if no auth is provided, but in prod enforce auth
        if os.getenv("ASTRA_MODE") == "prod":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return Role.ADMIN
        
    token = token.replace("Bearer ", "").strip()
    
    # 2. Check if token is a JWT (contains dots)
    if "." in token:
        try:
            claims = verify_oidc_token(token)
            roles = claims.get("realm_access", {}).get("roles", [])
            if "admin" in roles:
                return Role.ADMIN
            return Role.VIEWER
        except Exception as e:
            log.error(f"JWT Verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid OIDC Token")

    # 3. Fallback to static tokens for legacy/testing
    if token == ADMIN_TOKEN:
        return Role.ADMIN
    if token == VIEWER_TOKEN:
        return Role.VIEWER
        
    raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(role: str = Depends(get_current_role)):
    if role != Role.ADMIN:
        log.warning("Blocked attempt to perform admin action by non-admin")
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    return role
