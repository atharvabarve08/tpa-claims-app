"""
Role-based permissions matching the spec's three roles.

TPA_MANAGER is a superset ("Perform both submitter and approver actions" —
"Complete access across all application modules") so every check here lets
a manager through regardless of the specific allowed_roles a view declares.
"""

from rest_framework.permissions import BasePermission

from .models import UserProfile


class HasRole(BasePermission):
    """Base class — subclasses set allowed_roles. Do not use directly on a view."""

    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        profile = getattr(user, "claims_profile", None)
        if profile is None:
            return False

        if profile.role == UserProfile.Role.TPA_MANAGER:
            return True

        return profile.role in self.allowed_roles


class IsSubmitter(HasRole):
    """Ingestion, pricing submission, submit-for-payment-approval, schedule-payment."""

    allowed_roles = (UserProfile.Role.CLAIMS_SUBMITTER,)


class IsApprover(HasRole):
    """Approve/deny/pend, approve-payment/hold-payment."""

    allowed_roles = (UserProfile.Role.CLAIMS_APPROVER,)


class IsManager(HasRole):
    """Manager-only actions — analytics, user/permission management, overrides."""

    allowed_roles = ()  # nobody but TPA_MANAGER passes (see has_permission above)


class IsAnyRole(HasRole):
    """Any authenticated user with a role — used for read-only views like the Claims List/Detail."""

    allowed_roles = (UserProfile.Role.CLAIMS_SUBMITTER, UserProfile.Role.CLAIMS_APPROVER)