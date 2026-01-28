from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils.timezone import now
from .models import UserSession
from django.core.exceptions import PermissionDenied

class UpdateLastActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip middleware for specific paths
        excluded_substrings = ['get-otp', 'verify-otp', 'login', 'docs', 'schema']
        if any(path in request.path for path in excluded_substrings) or request.path.rstrip('/') == '/api':
            print("Skipping middleware for path:", request.path)
            return self.get_response(request)

        print("Middleware for path:", request.path)

        jwt_auth = JWTAuthentication()
        try:
            user_auth = jwt_auth.authenticate(request)
        except Exception:
            user_auth = None

        if user_auth:
            user, token = user_auth
            try:
                jti = str(token['jti'])
            except Exception:
                pass
            session = UserSession.objects.filter(user=user, token=jti).first()
            
            if session:
                if not session.is_active:
                    raise PermissionDenied("Session expired or logged out")
                
                session.last_active = now()
                session.save()
            else:
                # If session is missing (e.g. deleted by 'logout all'), deny access
                raise PermissionDenied("Session invalid or terminated")
                
        return self.get_response(request)