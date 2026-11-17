import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
import app as api


class InvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://test"
        )
        self.incident = json.loads(
            (Path(__file__).parents[1] / "examples" / "incident.json").read_text()
        )
        self.findings = {
            "suspected_root_cause": "A reduced connection pool may explain the timeouts.",
            "evidence_ids": ["deploy-1", "log-1", "metric-1"],
            "recommended_actions": ["Check connection wait times and database capacity."],
            "uncertainties": ["Database-side measurements are unavailable."],
        }
        self.request = httpx.Request("POST", "http://ollama/api/chat")
        client_patch = patch("app.httpx.Client")
        self.http = client_patch.start().return_value.__enter__.return_value.post
        self.addCleanup(client_patch.stop)
        self.set_model_response(self.findings)

    async def asyncTearDown(self):
        await self.client.aclose()

    def set_model_response(self, findings):
        self.http.return_value = httpx.Response(
            200,
            request=self.request,
            json={"done": True, "message": {"content": json.dumps(findings)}},
        )

    async def test_investigation_filters_sorts_and_returns_traceable_findings(self):
        other_service = deepcopy(self.incident["evidence"][0])
        other_service.update(id="other-service", service="search")
        self.incident["evidence"] = [other_service, *reversed(self.incident["evidence"])]

        response = await self.client.post("/investigate", json=self.incident)

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["findings"], self.findings)
        self.assertEqual(
            [item["id"] for item in result["evidence"]],
            ["deploy-1", "log-1", "metric-1"],
        )
        self.assertIn("database-timeouts.md", [item["source"] for item in result["runbooks"]])
        self.http.assert_called_once()
        request_body = self.http.call_args.kwargs["json"]
        context = json.loads(request_body["messages"][1]["content"])
        self.assertNotIn("evidence", context["incident"])
        self.assertEqual(context["evidence"], result["evidence"])
        self.assertEqual(context["runbooks"], result["runbooks"])
        self.assertFalse(request_body["stream"])
        self.assertIn("suspected_root_cause", request_body["format"]["properties"])

    async def test_empty_or_irrelevant_evidence_skips_model(self):
        for evidence in ([], [self.incident["evidence"][-1]]):
            with self.subTest(evidence=evidence):
                self.incident["evidence"] = evidence
                response = await self.client.post("/investigate", json=self.incident)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["findings"]["suspected_root_cause"])
                self.assertEqual(response.json()["evidence"], [])
        self.http.assert_not_called()

    async def test_time_window_boundaries_are_inclusive(self):
        self.incident["evidence"][0]["timestamp"] = self.incident["window_start"]
        self.incident["evidence"][2]["timestamp"] = self.incident["window_end"]
        response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["evidence"]), 3)

    async def test_invalid_inputs_are_rejected_without_model_call(self):
        for invalid in (
            {"window_start": "2026-11-18T10:00:00Z"},
            {"window_start": "2026-11-17T10:00:00"},
            {"evidence": [self.incident["evidence"][0]] * 2},
            {"evidence": [self.incident["evidence"][0]] * 101},
            {"summary": " "},
            {"unexpected": True},
        ):
            with self.subTest(invalid=invalid):
                response = await self.client.post("/investigate", json=self.incident | invalid)
                self.assertEqual(response.status_code, 422, response.text)
        self.http.assert_not_called()

    async def test_oversized_context_is_rejected_without_model_call(self):
        self.incident["evidence"] = [
            self.incident["evidence"][0] | {"id": f"log-{index}", "detail": "x" * 2000}
            for index in range(10)
        ]
        response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 422)
        self.http.assert_not_called()

    async def test_invalid_findings_are_rejected(self):
        for invalid in (
            {"evidence_ids": ["invented-id"]},
            {"evidence_ids": ["old-log"]},
            {"evidence_ids": []},
            {"suspected_root_cause": " "},
            {"recommended_actions": [" "]},
            {"unexpected": True},
        ):
            with self.subTest(invalid=invalid):
                self.set_model_response(self.findings | invalid)
                response = await self.client.post("/investigate", json=self.incident)
                self.assertEqual(response.status_code, 502, response.text)

    async def test_model_can_return_inconclusive_findings(self):
        findings = self.findings | {"suspected_root_cause": None, "evidence_ids": []}
        self.set_model_response(findings)
        response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["findings"]["suspected_root_cause"])

    async def test_malformed_or_incomplete_model_responses_are_rejected(self):
        for payload in (
            [],
            {"done": True},
            {"done": False, "message": {"content": json.dumps(self.findings)}},
            {"done": True, "done_reason": "length"},
            {"done": True, "message": {"content": "not JSON"}},
        ):
            with self.subTest(payload=payload):
                self.http.return_value = httpx.Response(200, request=self.request, json=payload)
                response = await self.client.post("/investigate", json=self.incident)
                self.assertEqual(response.status_code, 502, response.text)

    async def test_dependency_failures_return_errors_and_release_lock(self):
        for error, status in (
            (httpx.ConnectError("offline", request=self.request), 503),
            (httpx.ReadTimeout("timeout", request=self.request), 504),
        ):
            with self.subTest(error=error):
                self.http.side_effect = error
                response = await self.client.post("/investigate", json=self.incident)
                self.assertEqual(response.status_code, status, response.text)
        self.http.side_effect = None
        self.http.return_value = httpx.Response(404, request=self.request)
        response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 502)
        self.set_model_response(self.findings)
        response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 200)

    async def test_busy_model_returns_503_without_calling_ollama(self):
        with api.MODEL_LOCK:
            response = await self.client.post("/investigate", json=self.incident)
        self.assertEqual(response.status_code, 503)
        self.http.assert_not_called()

    def test_retrieval_ignores_no_match_and_breaks_ties_deterministically(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "b.md").write_text("database timeout", encoding="utf-8")
            (path / "a.md").write_text("database timeout", encoding="utf-8")
            (path / "c.md").write_text("disk capacity", encoding="utf-8")
            with patch.object(api, "RUNBOOK_DIR", path):
                self.assertEqual(api.retrieve_runbooks("unrelated xyzzy"), [])
                matches = api.retrieve_runbooks("database timeout")
        self.assertEqual([item.source for item in matches], ["a.md", "b.md"])


if __name__ == "__main__":
    unittest.main()
