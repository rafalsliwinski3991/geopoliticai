"""Progress copy the reporter's nodes emit. Same rules as the orchestrator's."""

OUTLINE_PROGRESS = {
    "type": "progress",
    "node": "outline",
    "label": "Reading the conversation...",
}

REPORT_PROGRESS = {
    "type": "progress",
    "node": "write",
    "label": "Writing the report...",
}
