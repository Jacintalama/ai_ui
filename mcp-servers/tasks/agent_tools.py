"""Deciding what an agent may do, and doing it.

Split out of agent_runner because it is the part with teeth: agent_runner
decides what to say, this decides what actually happens to someone's mail.
"""
import logging

logger = logging.getLogger(__name__)

#: Mutating verbs, matched as whole underscore-delimited tokens anywhere in
#: the name. This check runs first, in is_write_tool, and wins over the read
#: check below.
#:
#: That ordering is the fix for a Critical bug: the earlier rule matched a
#: read verb at the start of the name, or as a whole segment anywhere in the
#: name, and returned False (read) the moment it found one. It never asked
#: whether the same name also carried a mutating verb. So search_and_replace
#: read as a read because it starts with "search_", and clickup_delete_
#: list_item read as a read because "_list_" appears mid-string -- both are
#: writes. Putting the write-verb check first and letting it win closes that
#: specific class: a read-looking token elsewhere in the name can no longer
#: hide a delete, create, update, replace, and so on.
#:
#: This does not make the classifier exhaustive. It is a fixed vocabulary,
#: so a mutating verb not on this list (or a read-looking phrase that is
#: secretly destructive, like "get_rid_of_x") can still misclassify. Extend
#: this set when a false negative like that is found; do not read its
#: presence as a guarantee the gate is complete.
_WRITE_VERBS = frozenset({
    "create", "update", "delete", "remove", "send", "reply", "draft",
    "upload", "write", "set", "add", "move", "clear", "mark", "archive",
    "replace", "rename", "edit", "insert", "post", "patch", "destroy",
    "purge", "revoke", "grant", "share", "invite", "assign", "merge",
    "cancel", "trigger", "execute", "sync", "import", "export", "save",
    "publish", "unpublish", "enable", "disable", "reset", "restore",
    "duplicate", "copy", "close", "complete", "approve", "reject", "star",
    "unstar", "label", "tag", "comment",
})

#: Verbs that only ever read, checked against the first token or the second
#: token (proxy tools arrive server-qualified, e.g. clickup_list_tasks, so
#: the read verb is the second segment, not the first). Only consulted once
#: the write-verb veto above has cleared the name, so a read verb sitting
#: elsewhere in the name (the "search" in search_and_replace) no longer gets
#: to mark a write as safe.
_READ_VERBS = frozenset({
    "list", "get", "search", "read", "fetch", "find", "describe", "count",
    "query", "view", "show", "check",
})

#: The native tools, pinned by name. The verb rule already agrees with every
#: one of these; they are written out so that renaming a method has to break
#: a test rather than silently change what an unattended agent may do.
READ_METHODS: frozenset[str] = frozenset({
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",
    "list_calendar_events",
    "list_drive_files", "search_drive", "read_drive_file",
    "whoami",
})


def is_write_tool(method_name: str) -> bool:
    """True when calling this method could change something.

    Unknown counts as a write. That is the whole point: the classifier is
    consulted before an unattended run is allowed to act, so the failure
    direction has to be refusal.

    Order of checks, and why it matters:
    1. If any underscore-delimited token in the name is a known mutating
       verb, this is a write. Checked first, wins over everything below.
    2. Otherwise, if the name is one of the explicitly pinned READ_METHODS,
       it is a read.
    3. Otherwise, if the first token or the second token is a read verb,
       it is a read.
    4. Otherwise it is a write, by default.
    """
    name = (method_name or "").strip().lower()
    if not name:
        return True
    tokens = name.split("_")
    if any(token in _WRITE_VERBS for token in tokens):
        return True
    if name in READ_METHODS:
        return False
    if tokens[0] in _READ_VERBS:
        return False
    if len(tokens) > 1 and tokens[1] in _READ_VERBS:
        return False
    return True
