"""Read-only SQL browse pages for the LangGraph-owned checkpointer tables."""

from dataclasses import dataclass

from django.contrib import admin
from django.db import connection
from django.http import Http404
from django.template.response import TemplateResponse
from django.views import View

from chat.signals import CHECKPOINT_SCHEMA

PAGE_SIZE = 50
MAX_SEARCH_LENGTH = 100


@dataclass(frozen=True)
class BrowseTable:
    """Static SQL identifiers and visible columns for one browse page."""

    name: str
    table: str
    columns: tuple[str, ...]
    ordering: tuple[str, ...]
    search_column: str | None = "thread_id"


TABLES = {
    "checkpoint": BrowseTable(
        name="Checkpoints",
        table="checkpoints",
        columns=("thread_id", "checkpoint_ns", "checkpoint_id", "type"),
        ordering=("thread_id", "checkpoint_ns", "checkpoint_id"),
    ),
    "checkpointblob": BrowseTable(
        name="Checkpoint blobs",
        table="checkpoint_blobs",
        columns=("thread_id", "checkpoint_ns", "channel", "version", "type"),
        ordering=("thread_id", "checkpoint_ns", "channel", "version"),
    ),
    "checkpointwrite": BrowseTable(
        name="Checkpoint writes",
        table="checkpoint_writes",
        columns=(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "task_path",
            "idx",
            "channel",
            "type",
        ),
        ordering=("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    ),
    "checkpointmigration": BrowseTable(
        name="Checkpoint migrations",
        table="checkpoint_migrations",
        columns=("v",),
        ordering=("v",),
        search_column=None,
    ),
}


class ReadOnlyBrowseOnlyAdmin(View):
    """Staff-only changelist pages backed by SELECT statements, with no detail view."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, table: str):
        try:
            table_config = TABLES[table]
        except KeyError as exc:
            raise Http404("Unknown checkpointer table") from exc

        search = ""
        if table_config.search_column:
            search = request.GET.get("q", "")[:MAX_SEARCH_LENGTH]

        quoted_table = ".".join(
            connection.ops.quote_name(identifier)
            for identifier in (CHECKPOINT_SCHEMA, table_config.table)
        )
        where_sql = ""
        query_params: list[object] = []
        if search:
            column = connection.ops.quote_name(table_config.search_column)
            where_sql = f" WHERE {column} ILIKE %s"
            query_params.append(f"%{search}%")

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {quoted_table}{where_sql}", query_params
            )
            row_count = cursor.fetchone()[0]

        page_count = max(1, (row_count + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            requested_page = int(request.GET.get("page", "1"))
        except (TypeError, ValueError):
            requested_page = 1
        current_page = min(max(requested_page, 1), page_count)
        offset = (current_page - 1) * PAGE_SIZE

        selected_columns = ", ".join(
            connection.ops.quote_name(column) for column in table_config.columns
        )
        order_by = ", ".join(
            connection.ops.quote_name(column) for column in table_config.ordering
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {selected_columns} FROM {quoted_table}{where_sql} "
                f"ORDER BY {order_by} LIMIT %s OFFSET %s",
                [*query_params, PAGE_SIZE, offset],
            )
            rows = cursor.fetchall()

        def page_url(number: int) -> str:
            query = request.GET.copy()
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        page_links = [
            {
                "number": number,
                "url": page_url(number),
                "current": number == current_page,
            }
            for number in range(
                max(1, current_page - 2), min(page_count, current_page + 2) + 1
            )
        ]

        context = {
            **admin.site.each_context(request),
            "title": table_config.name,
            "columns": table_config.columns,
            "rows": rows,
            "row_count": row_count,
            "search": search,
            "searchable": table_config.search_column is not None,
            "current_page": current_page,
            "page_count": page_count,
            "page_links": page_links,
            "previous_url": page_url(current_page - 1) if current_page > 1 else None,
            "next_url": page_url(current_page + 1)
            if current_page < page_count
            else None,
        }
        return TemplateResponse(request, "admin/checkpointer/browse.html", context)
