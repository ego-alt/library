from enum import Enum


class UserRoleChoice(str, Enum):
    ADMIN = "admin"
    STANDARD = "standard"


class AccessLevelChoice(str, Enum):
    STANDARD = "standard"      # visible to everyone
    RESTRICTED = "restricted"  # admins only


class BookProgressChoice(str, Enum):
    UNREAD = "Unread"
    IN_PROGRESS = "In Progress"
    FINISHED = "Finished"
