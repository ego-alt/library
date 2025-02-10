from enum import Enum


class UserRoleChoice(str, Enum):
    ADMIN = "admin"
    STANDARD = "standard"


class BookProgressChoice(str, Enum):
    UNREAD = "Unread"
    IN_PROGRESS = "In Progress"
    FINISHED = "Finished"
