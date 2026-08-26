"""Deciding what an agent may do, and doing it.

Split out of agent_runner because it is the part with teeth: agent_runner
decides what to say, this decides what actually happens to someone's mail.
"""
import logging

logger = logging.getLogger(__name__)

#: Verb prefixes that only ever read. Anything else is treated as a write.
#: Deliberately a prefix rule and not a substring one: "unread" contains
#: "read" and delete_calendar_event contains "eve", and a substring rule
#: would quietly reclassify both.
_READ_PREFIXES = (
    "list_", "get_", "search_", "read_", "fetch_", "find_",
    "describe_", "count_",
)

#: The native tools, pinned by name. The verb rule already agrees with every
#: one of these; they are written out so that renaming a method has to break
#: a test rather than silently change what an unattended agent may do.
READ_METHODS = frozenset({
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",
    "list_calendar_events",
    "list_drive_files", "search_drive", "read_drive_file",
})


def is_write_tool(method_name: str) -> bool:
    """True when calling this method could change something.

    Unknown counts as a write. That is the whole point: the classifier is
    consulted before an unattended run is allowed to act, so the failure
    direction has to be refusal.
    """
    name = (method_name or "").strip().lower()
    if not name:
        return True
    if name in READ_METHODS:
        return False
    # Proxy tools arrive server-qualified (clickup_create_task). Match the
    # verb anywhere a segment starts, not just at the front of the string.
    for prefix in _READ_PREFIXES:
        if name.startswith(prefix) or ("_" + prefix) in name:
            return False
    return True
