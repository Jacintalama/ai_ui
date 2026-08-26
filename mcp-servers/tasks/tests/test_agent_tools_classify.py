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


@pytest.mark.parametrize("name", READS)
def test_reads_are_not_writes(name):
    assert is_write_tool(name) is False


@pytest.mark.parametrize("name", WRITES)
def test_writes_are_writes(name):
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
