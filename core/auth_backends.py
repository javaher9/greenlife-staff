from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    """Authenticate usernames without treating letter case as significant."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        if username is None:
            username = kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = user_model._default_manager.get(
                **{f"{user_model.USERNAME_FIELD}__iexact": username.strip()}
            )
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            # Keep password-check timing similar for unknown usernames and do
            # not choose an account when legacy case-only duplicates exist.
            user_model().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
