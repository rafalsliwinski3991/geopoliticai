"""Tests for raw-SQL, read-only checkpointer admin pages."""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

TABLES = (
    "checkpoint_migrations",
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
)


class ReadOnlyBrowseOnlyAdminTest(TransactionTestCase):
    """The admin reads LangGraph tables without registering Django models."""

    def setUp(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS agentic")
            for table in TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS agentic.{table}")
            cursor.execute(
                "CREATE TABLE agentic.checkpoints ("
                " thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL,"
                " checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT,"
                " type TEXT, checkpoint JSONB NOT NULL, metadata JSONB NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO agentic.checkpoints VALUES"
                " ('t1', '', 'c1', NULL, NULL, '{}', '{}'),"
                " ('t2', '', 'c2', NULL, NULL, '{}', '{}')"
            )
            cursor.execute(
                "INSERT INTO agentic.checkpoints"
                " SELECT 'page-' || n, '', 'c' || n, NULL, NULL, '{}', '{}'"
                " FROM generate_series(1, 51) AS n"
            )
            cursor.execute(
                "CREATE TABLE agentic.checkpoint_blobs ("
                " thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL,"
                " channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL,"
                " blob BYTEA)"
            )
            cursor.execute(
                "INSERT INTO agentic.checkpoint_blobs VALUES"
                " ('t1', '', 'channel', '1', 'empty', NULL)"
            )
            cursor.execute(
                "CREATE TABLE agentic.checkpoint_writes ("
                " thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL,"
                " checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,"
                " task_path TEXT NOT NULL DEFAULT '', idx INTEGER NOT NULL,"
                " channel TEXT NOT NULL, type TEXT, blob BYTEA NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO agentic.checkpoint_writes VALUES"
                " ('t1', '', 'c1', 'task', '', 0, 'channel', NULL, ''::bytea)"
            )
            cursor.execute(
                "CREATE TABLE agentic.checkpoint_migrations (v INTEGER PRIMARY KEY)"
            )
            cursor.execute("INSERT INTO agentic.checkpoint_migrations VALUES (1)")
        self.addCleanup(self._drop_stub_tables)

        user = get_user_model().objects.create_superuser(
            email="probe-admin@example.com", password="probe-password-1"
        )
        self.client.force_login(user)

    def _drop_stub_tables(self) -> None:
        with connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS agentic.{table}")

    def test_checkpointer_app_has_no_django_models(self) -> None:
        checkpointer = apps.get_app_config("checkpointer")
        self.assertEqual(list(checkpointer.get_models()), [])

    def test_each_admin_page_renders_rows_using_raw_sql(self) -> None:
        for url, expected in (
            ("/admin/checkpointer/checkpoint/", "page-1"),
            ("/admin/checkpointer/checkpointblob/", "channel"),
            ("/admin/checkpointer/checkpointwrite/", "task"),
            ("/admin/checkpointer/checkpointmigration/", "1"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.content.decode())
                self.assertIn("Read-only", response.content.decode())

    def test_thread_search_is_parameterized_and_filters_results(self) -> None:
        response = self.client.get(
            "/admin/checkpointer/checkpoint/", {"q": "t1' OR 1=1 --"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<td>t2</td>", response.content.decode())
        self.assertContains(response, "0 rows")

    def test_pagination_limits_rows_and_handles_invalid_page(self) -> None:
        response = self.client.get("/admin/checkpointer/checkpoint/", {"page": "2"})
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("page 2 of 2", content)
        self.assertIn("<td>t1</td>", content)
        self.assertNotIn("page-8", content)

        invalid_page = self.client.get(
            "/admin/checkpointer/checkpoint/", {"page": "not-a-number"}
        )
        self.assertEqual(invalid_page.status_code, 200)
        self.assertContains(invalid_page, "page 1 of 2")

    def test_browse_pages_reject_unknown_tables_and_writes(self) -> None:
        self.assertEqual(
            self.client.get("/admin/checkpointer/unknown/").status_code, 404
        )
        self.assertEqual(
            self.client.post("/admin/checkpointer/checkpoint/").status_code, 405
        )

    def test_browse_pages_require_staff_authentication(self) -> None:
        self.client.logout()

        response = self.client.get("/admin/checkpointer/checkpoint/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_admin_home_links_to_the_browse_pages(self) -> None:
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agentic backend — checkpointer (read-only)")
        self.assertContains(response, "Web backend — Django-managed")
        self.assertContains(response, "/admin/checkpointer/checkpoint/")
        self.assertContains(response, "/admin/checkpointer/checkpointblob/")
        self.assertContains(response, "/static/admin/css/dashboard.")
        self.assertContains(response, 'class="colMS"')
        self.assertContains(response, 'id="content-related"')
        self.assertNotContains(response, 'id="nav-sidebar"')
