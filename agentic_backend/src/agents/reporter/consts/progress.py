"""Progress copy the reporter's nodes emit. Same rules as the orchestrator's."""

from shared.frames import ProgressFrame

OUTLINE_PROGRESS = ProgressFrame(node="outline", label="Reading the conversation...")

REPORT_PROGRESS = ProgressFrame(node="write", label="Writing the report...")
