import hashlib
import json
import threading
import time
from typing import Any, Dict

from flask import Flask, jsonify, make_response, request

app = Flask(__name__)

idempotency_store: Dict[str, Dict[str, Any]] = {}
store_lock = threading.Lock()


def canonical_body_hash(payload: Dict[str, Any]) -> str:
    serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def build_response(payload: Dict[str, Any], status_code: int, cache_hit: bool):
    response = make_response(jsonify(payload), status_code)
    response.headers["X-Cache-Hit"] = "true" if cache_hit else "false"
    return response


def validate_request_payload(payload: Any):
    if payload is None:
        return "Request body must be valid JSON."

    if not isinstance(payload, dict):
        return "Request body must be a JSON object."

    if "amount" not in payload or "currency" not in payload:
        return "Request body must include 'amount' and 'currency'."

    return None


@app.post("/process-payment")
def process_payment():
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return jsonify({"error": "Idempotency-Key header is required."}), 400

    payload = request.get_json(silent=True)
    validation_error = validate_request_payload(payload)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    payload_hash = canonical_body_hash(payload)

    while True:
        with store_lock:
            record = idempotency_store.get(idempotency_key)

            if record is None:
                completion_event = threading.Event()
                idempotency_store[idempotency_key] = {
                    "payload_hash": payload_hash,
                    "status": "processing",
                    "event": completion_event,
                    "response_body": None,
                }
                break

            if record["payload_hash"] != payload_hash:
                return (
                    jsonify(
                        {
                            "error": "Idempotency key already used for a different request body."
                        }
                    ),
                    409,
                )

            if record["status"] == "completed":
                return build_response(record["response_body"], 200, True)

            completion_event = record["event"]

        completion_event.wait()

    try:
        time.sleep(2)
        response_body = {
            "message": f"Charged {payload['amount']} {payload['currency']}"
        }

        with store_lock:
            record = idempotency_store.get(idempotency_key)
            if record is not None:
                record["status"] = "completed"
                record["response_body"] = response_body
                record["event"].set()

        return build_response(response_body, 201, False)
    except Exception:
        with store_lock:
            record = idempotency_store.pop(idempotency_key, None)
            if record is not None:
                record["event"].set()
        raise


@app.delete("/admin/idempotency-keys/<key>")
def delete_idempotency_key(key: str):
    with store_lock:
        record = idempotency_store.get(key)

        if record is None:
            return jsonify({"error": "Idempotency key not found."}), 404

        if record["status"] == "processing":
            return (
                jsonify(
                    {
                        "error": "Cannot evict a key that is currently processing."
                    }
                ),
                409,
            )

        del idempotency_store[key]

    return jsonify({"message": f"Idempotency key '{key}' deleted."}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
