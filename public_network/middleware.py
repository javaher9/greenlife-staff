from django.shortcuts import redirect


class PublicNetworkMemberMiddleware:
    """Keep public-network accounts isolated from staff-only application pages."""

    ALLOWED_PREFIXES = (
        '/join/greenlife/',
        '/public-network/',
        '/static/',
        '/media/',
        '/api/health/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and hasattr(user, 'public_network_member'):
            if not request.path.startswith(self.ALLOWED_PREFIXES):
                return redirect('public_network:dashboard')
        return self.get_response(request)
