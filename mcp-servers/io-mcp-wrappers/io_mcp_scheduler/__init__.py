"""io-scheduler MCP wrapper — lets the agent create/list/delete cron schedules
for the user it's currently acting on behalf of.

The user describes a recurring task in chat ("every day at 8pm watch my stocks");
the agent calls create_schedule with a cron expression it converts. Subsequent
firings then run autonomously via the heartbeat scheduler in the tasks service.
"""
