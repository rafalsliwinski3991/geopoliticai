"""Progress copy the deep expert emits.

Same rule as `agents/orchestrator/consts/progress.py`: `api._generate` forwards
these verbatim, so nothing model- or user-produced may reach them. The templates
are filled with integers only, never with a query, title, or URL.
"""

from frames import ProgressFrame

PROGRESS_NODE = "deep_expert"
PLANNING_PROGRESS = ProgressFrame(node=PROGRESS_NODE, label="Planning the research...")
SEARCH_PROGRESS_LABEL = "Searching sources ({used} of {cap})..."
READ_PROGRESS_LABEL = "Reading sources ({count} so far)..."
REVISION_PROGRESS_LABEL = "Revising the analysis ({round} of {cap})..."
