import re
from uuid import uuid4

GROUP_ID_MAX_LENGTH = 128
GROUP_ID_PATTERN_STR = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
GROUP_ID_PATTERN = re.compile(GROUP_ID_PATTERN_STR)


class InvalidGroupId(ValueError):
    pass


def new_group_id() -> str:
    return str(uuid4())


def parse_group_id(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise InvalidGroupId("group id is required")
        return None
    gid = value.strip()
    if not gid:
        if required:
            raise InvalidGroupId("group id is required")
        return None
    if len(gid) > GROUP_ID_MAX_LENGTH or not GROUP_ID_PATTERN.fullmatch(gid):
        raise InvalidGroupId(
            "group id must be 1-128 characters starting with a letter or digit, "
            "then letters, digits, '.', '_', '-', or ':'"
        )
    return gid


def resolve_create_id(value: str | None) -> str:
    parsed = parse_group_id(value, required=False)
    return parsed if parsed is not None else new_group_id()
