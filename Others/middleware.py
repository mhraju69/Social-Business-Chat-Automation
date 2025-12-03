from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils.timezone import now
from .models import UserSession
from django.core.exceptions import PermissionDenied

User = get_user_model()

class JwtAuthMiddleware:
    """Authenticate WebSocket connections using JWT from querystring."""
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope["query_string"].decode())
        token = query.get("token")

        scope["user"] = None
        if token:
            try:
                access_token = AccessToken(token[0])
                user = await self.get_user(access_token["user_id"])
                scope["user"] = user
            except Exception:
                pass

        return await self.inner(scope, receive, send)

    @staticmethod
    async def get_user(user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
        

class UpdateLastActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        print(f"\n[Middleware] ===== NEW REQUEST: {request.path} =====")
        jwt_auth = JWTAuthentication()
        try:
            user_auth = jwt_auth.authenticate(request)
            print(f"[Middleware] Authentication successful")
        except Exception as e:
            print(f"[Middleware] Authentication failed: {e}")
            user_auth = None

        if user_auth:
            user, token = user_auth
            # token is the validated token object
            try:
                jti = str(token['jti'])
                print(f"[Middleware] User: {user.email}")
                print(f"[Middleware] Token JTI: {jti}")
            except (KeyError, TypeError) as e:
                print(f"[Middleware] Could not extract JTI: {e}")
                # If we can't get jti, skip session validation
                return self.get_response(request)

            # Check if session exists
            print(f"[Middleware] Searching for session with JTI: {jti}")
            session = UserSession.objects.filter(user=user, token=jti).first()
            
            if session:
                print(f"[Middleware] ✓ Session FOUND!")
                print(f"[Middleware] Session ID: {session.id}")
                print(f"[Middleware] Session is_active: {session.is_active}")
                
                # If session exists but is inactive (logged out), block access
                if not session.is_active:
                    print(f"[Middleware] ✗ BLOCKING REQUEST - Session is INACTIVE!")
                    raise PermissionDenied("Session expired or logged out")
                
                # Update last active time for active sessions
                session.last_active = now()
                session.save()
                print(f"[Middleware] ✓ Updated last_active")
            else:
                print(f"[Middleware] ✗ NO SESSION FOUND for this JTI")
                print(f"[Middleware] Checking all sessions for user {user.email}:")
                all_sessions = UserSession.objects.filter(user=user)
                for s in all_sessions:
                    print(f"  - Session {s.id}: JTI={s.token[:30]}..., active={s.is_active}")
            # If no session exists at all, allow access (for backward compatibility)

        print(f"[Middleware] ===== REQUEST ALLOWED =====\n")
        return self.get_response(request)