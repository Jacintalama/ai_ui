"""The read/write split that decides what an unattended agent may do.

Worth testing hard: a classifier that returned False for everything would
let a 7am cron send mail, and would pass any test that only checked reads.
So the writes are asserted individually, by name, from the real tool list.
"""
import pytest

from agent_tools import is_write_tool


READS = [
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",            # gmail
    "list_calendar_events",                   # calendar
    "list_drive_files", "search_drive", "read_drive_file",   # gdrive
    "whoami", "query_database",               # mytools
]

WRITES = [
    "draft_email", "reply_to_email", "send_email",           # gmail
    "create_calendar_event", "update_calendar_event",
    "delete_calendar_event",                                 # calendar
    "create_document",                                       # documents
    "create_excel", "create_simple_excel",                   # excel_creator
    "create_dashboard", "create_simple_dashboard",           # executive_dashboard
    "upload_drive_file",                                     # gdrive
    "remember",                                              # remember
]

#: Names that used to classify as reads under the old prefix/substring rule,
#: because a read verb led the name or sat in a mid-string segment (e.g.
#: "_list_"), even though each of these mutates real data. That was the
#: Critical finding: the gate is only safe if the failure direction is
#: refusal, and these all failed the wrong way, silently letting an
#: unattended agent overwrite, delete, or rewrite state.
FORMERLY_MISCLASSIFIED_WRITES = [
    "search_and_replace",          # startswith "search_" -> overwrites content
    "find_and_delete_duplicates",  # startswith "find_" -> deletes
    "get_and_delete_temp_files",   # startswith "get_" -> deletes
    "mark_read_and_archive",       # "_read_" mid-string -> changes message state
    "clear_search_history",        # "_search_" mid-string -> destroys history
    "list_and_delete_stale_tasks", # "_list_" mid-string -> deletes
    "clickup_create_list_item",    # "_list_" mid-string -> creates
    "clickup_delete_list_item",    # "_list_" mid-string -> deletes
    "trello_update_list_name",     # "_list_" mid-string -> mutates
    "notion_update_list_view",     # "_list_" mid-string -> mutates
    "delete_search_filter",        # "_search_" mid-string -> deletes
]


@pytest.mark.parametrize("name", READS)
def test_reads_are_not_writes(name):
    assert is_write_tool(name) is False


@pytest.mark.parametrize("name", WRITES)
def test_writes_are_writes(name):
    assert is_write_tool(name) is True


@pytest.mark.parametrize("name", FORMERLY_MISCLASSIFIED_WRITES)
def test_write_verb_veto_beats_a_leading_or_mid_string_read_verb(name):
    """Regression for the Critical finding: a mutating verb anywhere in the
    name must win, even when a read verb leads or appears mid-string."""
    assert is_write_tool(name) is True


def test_an_unknown_method_counts_as_a_write():
    """The default has to fail toward refusing. A tool nobody classified
    must not be able to act unattended."""
    assert is_write_tool("frobnicate_the_widget") is True


def test_an_empty_name_counts_as_a_write():
    assert is_write_tool("") is True


def test_classification_ignores_case_and_server_prefix():
    """Proxy tools arrive qualified, e.g. clickup_create_task, and casing
    is not guaranteed."""
    assert is_write_tool("SEARCH_emails") is False
    assert is_write_tool("clickup_create_task") is True


# "check" was once treated as a read verb, on the strength of check_my_access.
# It is overloaded: on a ClickUp or Trello checklist, checking an item ticks
# it off, which mutates. These names contain no other write verb, so nothing
# else in the classifier would have caught them.
CHECK_WRITES = [
    "check_item", "check_task", "check_checklist_item", "check_off_task",
    "trello_check_item", "clickup_check_checklist_item",
]


@pytest.mark.parametrize("name", CHECK_WRITES)
def test_checking_something_off_is_a_write(name):
    assert is_write_tool(name) is True


def test_the_one_genuine_check_read_is_pinned_by_name():
    """check_my_access really does only inspect, and it exists in this repo,
    so it is pinned rather than resurrecting the verb for everything."""
    assert is_write_tool("check_my_access") is False


# The names below come from the live proxy's real 312-tool surface, not from
# imagination. Several server prefixes there are two-part (google-drive_,
# web-search_) or hyphenated per-user prefixes (my-clickup_, my-github_),
# which pushes the read verb to the third underscore-delimited token --
# e.g. google-drive_gdrive_list_files. That is exactly why the read-verb
# window in is_write_tool checks the first THREE tokens rather than two.

#: These two-part-prefix names carry a write verb somewhere in the name and
#: must still classify as writes. This is the regression that matters most:
#: widening the read window is only safe because the write-verb veto runs
#: first and scans every token, not just the first three, so a write verb
#: anywhere in the name -- including past the third token -- still wins.
TWO_PART_PREFIX_WRITES = [
    "google-drive_gdrive_upload_to_webui",
    "google-drive_gdrive_create_file",
    "google-drive_auth_google_disconnect",
    "my-clickup_create_task",
    "my-github_create_issue",
]


@pytest.mark.parametrize("name", TWO_PART_PREFIX_WRITES)
def test_two_part_server_prefix_writes_stay_writes(name):
    assert is_write_tool(name) is True


#: These two-part-prefix names are genuine reads that a two-token window
#: refused, because the read verb sits in the third token.
TWO_PART_PREFIX_READS = [
    "my-clickup_list_tasks",
    "my-clickup_whoami",
    "my-github_list_my_repos",
    "google-drive_gdrive_list_files",
    "google-drive_gdrive_read_file",
    "web-search_web_search",
]


@pytest.mark.parametrize("name", TWO_PART_PREFIX_READS)
def test_two_part_server_prefix_reads_are_not_writes(name):
    assert is_write_tool(name) is False
