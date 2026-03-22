from pathlib import Path
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Archive


class SecurityRegressionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner", password="testpass123"
        )
        self.attacker = user_model.objects.create_user(
            username="attacker", password="testpass123"
        )
        self.owner_archive = Archive.objects.create(
            user=self.owner,
            url="https://example.com",
            title="Owner Archive",
            notes="private notes",
            content="<html>owner content</html>",
        )

    def test_idor_blocked_for_archive_detail_view(self):
        self.client.login(username="attacker", password="testpass123")
        response = self.client.get(
            reverse("view_archive", kwargs={"archive_id": self.owner_archive.id})
        )
        self.assertEqual(response.status_code, 404)

    def test_idor_blocked_for_archive_edit_view(self):
        self.client.login(username="attacker", password="testpass123")
        response = self.client.get(
            reverse("edit_archive", kwargs={"archive_id": self.owner_archive.id})
        )
        self.assertEqual(response.status_code, 404)

    def test_idor_blocked_for_archive_delete_view(self):
        self.client.login(username="attacker", password="testpass123")
        response = self.client.get(
            reverse("delete_archive", kwargs={"archive_id": self.owner_archive.id})
        )
        self.assertEqual(response.status_code, 404)

    def test_search_query_payload_does_not_break_scope(self):
        Archive.objects.create(
            user=self.attacker,
            url="https://attacker.example",
            title="attacker secret",
            notes="n",
            content="c",
        )
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("search_archives"), {"q": "' OR 1=1 --"})
        self.assertEqual(response.status_code, 200)
        results = list(response.context["results"])
        self.assertEqual(results, [])

    def test_view_archive_escapes_stored_html(self):
        self.owner_archive.notes = "<script>alert('x')</script>"
        self.owner_archive.content = "<img src=x onerror=alert('x')>"
        self.owner_archive.save()

        self.client.login(username="owner", password="testpass123")
        response = self.client.get(
            reverse("view_archive", kwargs={"archive_id": self.owner_archive.id})
        )
        body = response.content.decode("utf-8")

        self.assertNotIn("<script>alert('x')</script>", body)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", body)
        self.assertNotIn("<img src=x onerror=alert('x')>", body)
        self.assertIn("&lt;img src=x onerror=alert(&#x27;x&#x27;)&gt;", body)

    @patch("archiver.views.query_llm", return_value="DROP TABLE archiver_archive;")
    def test_ask_database_blocks_non_select_sql(self, _mock_query_llm):
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(reverse("ask_database"), {"prompt": "drop table"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only SELECT queries are allowed.")

    @patch("archiver.views.query_llm", return_value="SELECT * FROM auth_user")
    def test_ask_database_blocks_wrong_table_access(self, _mock_query_llm):
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(reverse("ask_database"), {"prompt": "show users"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Query must read from archiver_archive.")

    def test_add_archive_blocks_localhost_url(self):
        self.client.login(username="owner", password="testpass123")
        before = Archive.objects.count()
        response = self.client.post(
            reverse("add_archive"),
            {"url": "http://127.0.0.1:8000/admin", "notes": "x"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Archive.objects.count(), before)
        self.assertContains(response, "Only public HTTP/HTTPS URLs are allowed.")

    @patch("archiver.views.requests.get")
    @patch(
        "archiver.views.query_llm",
        return_value={
            "tool_calls": [
                {
                    "function": {
                        "name": "fetch_url",
                        "arguments": {"url": "http://localhost:11434"},
                    }
                }
            ]
        },
    )
    def test_enrich_archive_blocks_tool_ssrf(self, _mock_query_llm, mock_requests_get):
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(
            reverse("enrich_archive", kwargs={"archive_id": self.owner_archive.id}),
            {"instruction": "fetch latest content"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Blocked non-public URL")
        mock_requests_get.assert_not_called()

    @patch("archiver.views.query_llm", return_value="Summary body")
    def test_export_summary_sanitizes_output_path(self, _mock_query_llm):
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(
            reverse("export_summary"),
            {"topic": "Q3 Report", "filename_hint": "../../escape"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        safe_path = Path(settings.BASE_DIR) / "exported_summaries" / "escape.txt"
        self.assertTrue(safe_path.exists())
        self.assertEqual(safe_path.read_text(encoding="utf-8"), "Summary body")

    def test_generate_token_uses_project_secret_key(self):
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("generate_token"))
        self.assertEqual(response.status_code, 200)

        token = response.json()["token"]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        self.assertEqual(payload["user_id"], self.owner.id)
        self.assertEqual(payload["username"], self.owner.username)
