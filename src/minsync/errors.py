"""Uniform MinSync errors. Every error carries a stable machine-readable code."""
from __future__ import annotations


class MinSyncError(Exception):
    code = "minsync_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidArgument(MinSyncError):
    code = "invalid_argument"


class WorkspaceNotFound(MinSyncError):
    code = "workspace_not_found"


class TaskNotFound(MinSyncError):
    code = "task_not_found"


class ArtifactNotFound(MinSyncError):
    code = "artifact_not_found"


class DockerUnavailable(MinSyncError):
    code = "docker_unavailable"


class ImageMissing(MinSyncError):
    code = "image_missing"


class UnknownProfile(MinSyncError):
    code = "unknown_profile"


class PathTraversal(MinSyncError):
    code = "path_traversal"


class QuotaExceeded(MinSyncError):
    code = "quota_exceeded"


class ArchiveError(MinSyncError):
    code = "archive_error"


class FileOperationError(MinSyncError):
    code = "file_error"
