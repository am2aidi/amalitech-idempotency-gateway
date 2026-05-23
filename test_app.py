import threading
import unittest
from datetime import datetime, timedelta, timezone
from time import sleep as real_sleep
from unittest.mock import patch

from app import app, clear_expired_keys, idempotency_store, reset_store, store_lock


class IdempotencyGatewayTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        reset_store()
        self.client = app.test_client()

    def tearDown(self):
        reset_store()

    def test_happy_path_returns_new_transaction_success(self):
        with patch("app.time.sleep", return_value=None) as mocked_sleep:
            response = self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-001"},
                json={"amount": 100, "currency": "GHS"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["X-Cache-Hit"], "false")
        self.assertEqual(
            response.get_json(),
            {
                "status": "New Transaction Success",
                "message": "Charged 100 GHS",
            },
        )
        mocked_sleep.assert_called_once_with(2)

    def test_duplicate_request_returns_already_paid_status(self):
        with patch("app.time.sleep", return_value=None) as mocked_sleep:
            self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-002"},
                json={"amount": 100, "currency": "GHS"},
            )

            duplicate_response = self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-002"},
                json={"amount": 100, "currency": "GHS"},
            )

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(duplicate_response.headers["X-Cache-Hit"], "true")
        self.assertEqual(
            duplicate_response.get_json(),
            {
                "status": "Duplicate Detected - Already Paid",
                "message": "Charged 100 GHS",
            },
        )
        mocked_sleep.assert_called_once_with(2)

    def test_payload_change_with_same_key_returns_security_alert(self):
        with patch("app.time.sleep", return_value=None):
            self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-003"},
                json={"amount": 100, "currency": "GHS"},
            )

        response = self.client.post(
            "/process-payment",
            headers={"Idempotency-Key": "pay-003"},
            json={"amount": 500, "currency": "GHS"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json(),
            {
                "status": "Security Alert - Conflict",
                "message": "Idempotency key already used for a different request body.",
            },
        )

    def test_admin_cache_eviction_returns_admin_success(self):
        with patch("app.time.sleep", return_value=None):
            self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-004"},
                json={"amount": 100, "currency": "GHS"},
            )

        response = self.client.delete("/admin/idempotency-keys/pay-004")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "status": "Admin Success",
                "message": "Key manually evicted from cache.",
            },
        )

    def test_expired_key_is_removed_and_allows_a_fresh_transaction(self):
        with patch("app.time.sleep", return_value=None) as mocked_sleep:
            first_response = self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-ttl-001"},
                json={"amount": 100, "currency": "GHS"},
            )

            self.assertEqual(first_response.status_code, 201)

            with store_lock:
                idempotency_store["pay-ttl-001"]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

            clear_expired_keys()

            with store_lock:
                self.assertNotIn("pay-ttl-001", idempotency_store)

            second_response = self.client.post(
                "/process-payment",
                headers={"Idempotency-Key": "pay-ttl-001"},
                json={"amount": 100, "currency": "GHS"},
            )

        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(second_response.headers["X-Cache-Hit"], "false")
        self.assertEqual(
            second_response.get_json(),
            {
                "status": "New Transaction Success",
                "message": "Charged 100 GHS",
            },
        )
        self.assertEqual(mocked_sleep.call_count, 2)

    def test_inflight_duplicate_waits_then_replays_as_duplicate(self):
        responses = []

        def send_request():
            with app.test_client() as client:
                response = client.post(
                    "/process-payment",
                    headers={"Idempotency-Key": "pay-race-001"},
                    json={"amount": 250, "currency": "USD"},
                )
                responses.append(
                    (
                        response.status_code,
                        response.headers["X-Cache-Hit"],
                        response.get_json(),
                    )
                )

        with patch("app.time.sleep", side_effect=lambda _: real_sleep(0.15)):
            first_thread = threading.Thread(target=send_request)
            second_thread = threading.Thread(target=send_request)

            first_thread.start()
            real_sleep(0.03)
            second_thread.start()

            first_thread.join()
            second_thread.join()

        self.assertEqual(len(responses), 2)

        responses.sort(key=lambda item: item[0], reverse=True)
        first_result, second_result = responses

        self.assertEqual(first_result[0], 201)
        self.assertEqual(first_result[1], "false")
        self.assertEqual(
            first_result[2],
            {
                "status": "New Transaction Success",
                "message": "Charged 250 USD",
            },
        )

        self.assertEqual(second_result[0], 200)
        self.assertEqual(second_result[1], "true")
        self.assertEqual(
            second_result[2],
            {
                "status": "Duplicate Detected - Already Paid",
                "message": "Charged 250 USD",
            },
        )


if __name__ == "__main__":
    unittest.main()
