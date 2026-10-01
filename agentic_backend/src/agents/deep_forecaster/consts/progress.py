"""Progress copy the deep forecaster emits.

Same rule as `agents/deep_expert/consts/progress.py`: `api._generate`
forwards these verbatim, so the labels are literals and the templates are
filled with integers only, never with a query, a name, a title, or a URL.
"""

PROGRESS_NODE = "deep_forecaster"
RESEARCH_LABEL = "Planning the research..."
SEARCH_PROGRESS_LABEL = "Searching the forecasters' sites ({used} of {cap})..."
READ_PROGRESS_LABEL = "Reading sources ({count} so far)..."
VIDEO_PROGRESS_LABEL = "Asking Gemini about a video ({used} of {cap})..."
CLAIMS_LABEL = "Drafting the claims..."
ROUND_LABEL = "Council voting, round {round} of 2..."
WRITE_LABEL = "Writing the analysis..."
VERIFY_LABEL = "Checking the answer..."
