"""Custom exceptions for the Agent Meeting SDK."""


class MeetingError(Exception):
    """Base exception for meeting SDK."""
    pass


class ConnectionError(MeetingError):
    """WebSocket connection error."""
    pass


class AuthError(MeetingError):
    """Authentication error."""
    pass


class NotInRoomError(MeetingError):
    """Agent is not in the room."""
    pass


class PermissionDeniedError(MeetingError):
    """Insufficient permissions for the requested action."""
    pass
