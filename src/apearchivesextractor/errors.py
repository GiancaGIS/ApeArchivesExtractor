class ApeArchivesExtractorError(Exception):
    """Base exception for ApeArchivesExtractor."""


class UnsupportedArchiveError(ApeArchivesExtractorError):
    """Raised when an archive format is not supported."""


class UnsupportedFeatureError(ApeArchivesExtractorError):
    """Raised when a supported format does not support a requested feature."""


class UnsafeArchivePathError(ApeArchivesExtractorError):
    """Raised when an archive contains an unsafe path."""


class ArchiveLimitExceededError(ApeArchivesExtractorError):
    """Raised when an archive extraction would exceed safety limits."""


class ArchiveDependencyError(ApeArchivesExtractorError):
    """Raised when an optional archive backend is missing."""


class ArchiveMemberNotFoundError(ApeArchivesExtractorError):
    """Raised when a requested archive member cannot be found."""


class OperationCancelledError(ApeArchivesExtractorError):
    """Raised when the user cancels a running archive operation."""
