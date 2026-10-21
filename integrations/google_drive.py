"""Compatibility import for the rclone-backed Google Drive integration."""

from integrations.rclone_drive import RcloneDriveManager

GoogleDriveManager = RcloneDriveManager

__all__ = ["GoogleDriveManager", "RcloneDriveManager"]
