"""Stable domain exceptions raised by project transaction services."""


class ProjectDomainError(Exception):
    """Base class for expected project workflow failures."""


class MembershipNotFound(ProjectDomainError):
    pass


class ExistingMember(ProjectDomainError):
    pass


class DuplicateInvitation(ProjectDomainError):
    pass


class InvitationNotFound(ProjectDomainError):
    pass


class InvitationExpired(ProjectDomainError):
    pass


class InvitationUnavailable(ProjectDomainError):
    pass


class SoleOwnerViolation(ProjectDomainError):
    pass


class InvalidRole(ProjectDomainError):
    pass
