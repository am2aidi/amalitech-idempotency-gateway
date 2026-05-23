import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from flask import Flask, jsonify, make_response, render_template_string, request

app = Flask(__name__)

store_lock = threading.Lock()
idempotency_store: Dict[str, Dict[str, Any]] = {}

STATUS_NEW_SUCCESS = "New Transaction Success"
STATUS_DUPLICATE = "Duplicate Detected - Already Paid"
STATUS_CONFLICT = "Security Alert - Conflict"
STATUS_ADMIN = "Admin Success"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", DEFAULT_TTL_SECONDS))

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>FinSafe Idempotency Gateway</title>
    <style>
        :root {
            --bg: #f4f1ea;
            --ink: #1b2430;
            --muted: #5e6a75;
            --panel: rgba(255, 255, 255, 0.88);
            --green: #0f5a2b;
            --green-soft: #cfeeda;
            --blue: #0b5ea8;
            --blue-soft: #d9ebff;
            --red: #8f1f28;
            --red-soft: #ffdfe2;
            --border: rgba(27, 36, 48, 0.09);
            --shadow: 0 18px 45px rgba(27, 36, 48, 0.12);
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: Georgia, "Times New Roman", serif;
            color: var(--ink);
            background:
                radial-gradient(circle at top left, rgba(29, 122, 70, 0.18), transparent 32%),
                radial-gradient(circle at top right, rgba(23, 105, 170, 0.18), transparent 28%),
                linear-gradient(160deg, #f7f4ee 0%, #ece4d6 100%);
        }

        .shell {
            width: min(1120px, calc(100% - 32px));
            margin: 32px auto;
            display: grid;
            gap: 24px;
        }

        .hero,
        .panel {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 24px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(10px);
        }

        .hero {
            padding: 32px;
            display: grid;
            gap: 16px;
        }

        .eyebrow {
            margin: 0;
            font-size: 0.85rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--muted);
        }

        h1 {
            margin: 0;
            font-size: clamp(2rem, 4vw, 3.6rem);
            line-height: 0.95;
        }

        .hero p {
            margin: 0;
            max-width: 700px;
            color: var(--muted);
            font-size: 1.05rem;
            line-height: 1.6;
        }

        .grid {
            display: grid;
            grid-template-columns: 1.15fr 0.85fr;
            gap: 24px;
        }

        .panel {
            padding: 28px;
        }

        .panel h2 {
            margin: 0 0 8px;
            font-size: 1.4rem;
        }

        .panel p {
            margin: 0 0 20px;
            color: var(--muted);
            line-height: 1.6;
        }

        .form-grid {
            display: grid;
            gap: 16px;
        }

        label {
            display: grid;
            gap: 8px;
            font-size: 0.95rem;
            color: var(--ink);
        }

        input {
            width: 100%;
            border: 1px solid rgba(27, 36, 48, 0.14);
            border-radius: 14px;
            padding: 14px 16px;
            font: inherit;
            background: rgba(255, 255, 255, 0.92);
        }

        button {
            border: 0;
            border-radius: 999px;
            padding: 14px 20px;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            transition: transform 150ms ease, box-shadow 150ms ease, opacity 150ms ease;
        }

        button:hover {
            transform: translateY(-1px);
        }

        button:disabled {
            opacity: 0.7;
            cursor: wait;
            transform: none;
        }

        .primary {
            color: white;
            background: linear-gradient(135deg, #1d7a46, #259f59);
            box-shadow: 0 10px 24px rgba(29, 122, 70, 0.25);
        }

        .secondary {
            color: white;
            background: linear-gradient(135deg, #1769aa, #2482cf);
            box-shadow: 0 10px 24px rgba(23, 105, 170, 0.25);
        }

        .stack {
            display: grid;
            gap: 14px;
        }

        .scenario-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
        }

        .scenario-card {
            border-radius: 18px;
            padding: 16px 18px;
            border: 1px solid rgba(27, 36, 48, 0.1);
        }

        .scenario-card h3 {
            margin: 0 0 8px;
            font-size: 1rem;
        }

        .scenario-card p {
            margin: 0;
            line-height: 1.55;
            color: inherit;
        }

        .banner {
            display: none;
            border-radius: 18px;
            padding: 16px 18px;
            border: 1px solid transparent;
            animation: fadeUp 220ms ease;
        }

        .banner.visible {
            display: block;
        }

        .banner h3 {
            margin: 0 0 6px;
            font-size: 1.05rem;
        }

        .banner p,
        .banner small {
            margin: 0;
            color: inherit;
        }

        .banner small {
            display: block;
            margin-top: 10px;
            opacity: 0.85;
        }

        .success {
            background: var(--green-soft);
            color: var(--green);
            border-color: rgba(29, 122, 70, 0.18);
        }

        .cache {
            background: var(--blue-soft);
            color: var(--blue);
            border-color: rgba(23, 105, 170, 0.18);
        }

        .conflict {
            background: var(--red-soft);
            color: var(--red);
            border-color: rgba(161, 47, 52, 0.18);
        }

        .neutral {
            background: #fff4d9;
            color: #7c4a00;
            border-color: rgba(124, 74, 0, 0.18);
        }

        .meta {
            display: grid;
            gap: 12px;
            margin-top: 12px;
            color: var(--muted);
            font-size: 0.95rem;
        }

        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .pill {
            padding: 9px 12px;
            border-radius: 999px;
            background: rgba(27, 36, 48, 0.05);
            color: var(--ink);
        }

        code {
            font-family: "Courier New", Courier, monospace;
            font-size: 0.92rem;
        }

        @keyframes fadeUp {
            from {
                opacity: 0;
                transform: translateY(6px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @media (max-width: 860px) {
            .grid {
                grid-template-columns: 1fr;
            }

            .scenario-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <p class="eyebrow">FinSafe Transactions Ltd.</p>
            <h1>Pay once. Do not pay twice.</h1>
            <p>
                This page helps you test the payment gateway.
                Send the same payment twice to see the first request create the payment
                and the second request return the saved answer right away.
            </p>
            <p>
                Saved payment keys stay in memory for <strong>{{ ttl_label }}</strong>.
                For quick testing, you can start the app with <code>IDEMPOTENCY_TTL_SECONDS=60</code>
                to make keys expire after 1 minute.
            </p>
            <div class="pill-row">
                <span class="pill">Green means the payment was processed.</span>
                <span class="pill">Blue means the payment was already done before.</span>
                <span class="pill">Red means the request was blocked.</span>
                <span class="pill">Gold means a saved key can expire and reset itself.</span>
            </div>
        </section>

        <section class="grid">
            <div class="panel">
                <h2>Submit Payment</h2>
                <p>Use this form or Postman. Both send requests to the same Flask API and use the same saved payment records.</p>
                <form id="payment-form" class="form-grid">
                    <label>
                        Idempotency Key
                        <input id="idempotencyKey" name="idempotencyKey" value="pay-001" required>
                    </label>
                    <label>
                        Amount
                        <input id="amount" name="amount" type="number" min="1" value="100" required>
                    </label>
                    <label>
                        Currency
                        <input id="currency" name="currency" value="GHS" maxlength="3" required>
                    </label>
                    <button class="primary" id="submitButton" type="submit">Submit Payment</button>
                </form>
            </div>

            <div class="panel stack">
                <div>
                    <h2>Live Result</h2>
                    <p>The result below shows the same message that the API sends back.</p>
                </div>

                <div id="resultBanner" class="banner">
                    <h3 id="resultStatus"></h3>
                    <p id="resultMessage"></p>
                    <small id="resultMeta"></small>
                </div>

                <div class="meta">
                    <div><strong>Simple test:</strong> send once, send again, then change the amount while using the same key.</div>
                    <div><code>DELETE /admin/idempotency-keys/&lt;key&gt;</code> removes a saved key so you can test again from the start.</div>
                </div>
            </div>
        </section>

        <section class="panel stack">
            <div>
                <h2>What Each Scenario Means</h2>
                <p>These are the main cases your gateway handles.</p>
            </div>
            <div class="scenario-grid">
                <article class="scenario-card success">
                    <h3>1. New payment</h3>
                    <p>The key is new, so the gateway waits 2 seconds, processes the payment, and returns a green success result.</p>
                </article>
                <article class="scenario-card cache">
                    <h3>2. Same payment sent again</h3>
                    <p>The key and body match a saved payment, so the gateway skips the 2-second delay and returns the saved answer.</p>
                </article>
                <article class="scenario-card conflict">
                    <h3>3. Same key, different details</h3>
                    <p>If the key is reused with a different amount or body, the gateway blocks it and returns a conflict response.</p>
                </article>
                <article class="scenario-card neutral">
                    <h3>4. Key expires by itself</h3>
                    <p>After <strong>{{ ttl_label }}</strong>, the saved key is removed automatically. If you set the TTL to 60 seconds for testing, you can watch it reset after 1 minute.</p>
                </article>
            </div>
        </section>

        <section class="grid">
            <div class="panel">
                <h2>Admin Cache Eviction</h2>
                <p>Use this when you want to remove a saved key by hand.</p>
                <form id="evict-form" class="form-grid">
                    <label>
                        Key To Evict
                        <input id="evictKey" name="evictKey" value="pay-001" required>
                    </label>
                    <button class="secondary" id="evictButton" type="submit">Evict Key</button>
                </form>
            </div>

            <div class="panel">
                <h2>Why This Matters</h2>
                <p>
                    Payment systems often retry when the network is slow.
                    Without idempotency, the same payment can be charged twice.
                    This gateway saves the first result, waits for in-flight duplicates,
                    and blocks the same key if the payment details change.
                </p>
            </div>
        </section>
    </main>

    <script>
        const paymentForm = document.getElementById("payment-form");
        const evictForm = document.getElementById("evict-form");
        const submitButton = document.getElementById("submitButton");
        const evictButton = document.getElementById("evictButton");
        const resultBanner = document.getElementById("resultBanner");
        const resultStatus = document.getElementById("resultStatus");
        const resultMessage = document.getElementById("resultMessage");
        const resultMeta = document.getElementById("resultMeta");

        function showResult(data, httpStatus, cacheHit) {
            resultBanner.className = "banner visible";

            if (httpStatus >= 400) {
                resultBanner.classList.add("conflict");
            } else if (cacheHit === "true" || data.status === "Duplicate Detected - Already Paid") {
                resultBanner.classList.add("cache");
            } else {
                resultBanner.classList.add("success");
            }

            resultStatus.textContent = data.status || "Response received";
            resultMessage.textContent = data.message || "No message returned.";
            resultMeta.textContent = `HTTP ${httpStatus} - X-Cache-Hit: ${cacheHit ?? "n/a"}`;
        }

        paymentForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            submitButton.disabled = true;
            submitButton.textContent = "Processing...";

            try {
                const idempotencyKey = document.getElementById("idempotencyKey").value.trim();
                const amount = Number(document.getElementById("amount").value);
                const currency = document.getElementById("currency").value.trim().toUpperCase();

                const response = await fetch("/process-payment", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Idempotency-Key": idempotencyKey
                    },
                    body: JSON.stringify({ amount, currency })
                });

                const data = await response.json();
                showResult(data, response.status, response.headers.get("X-Cache-Hit"));
            } catch (error) {
                showResult(
                    { status: "Security Alert - Conflict", message: "The page could not reach the local API." },
                    500,
                    "false"
                );
            } finally {
                submitButton.disabled = false;
                submitButton.textContent = "Submit Payment";
            }
        });

        evictForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            evictButton.disabled = true;
            evictButton.textContent = "Evicting...";

            try {
                const key = document.getElementById("evictKey").value.trim();
                const response = await fetch(`/admin/idempotency-keys/${encodeURIComponent(key)}`, {
                    method: "DELETE"
                });

                const data = await response.json();
                showResult(data, response.status, response.headers.get("X-Cache-Hit"));
            } catch (error) {
                showResult(
                    { status: "Security Alert - Conflict", message: "The page could not reach the local API." },
                    500,
                    "false"
                );
            } finally {
                evictButton.disabled = false;
                evictButton.textContent = "Evict Key";
            }
        });
    </script>
</body>
</html>
"""


def canonical_body_hash(payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_api_response(payload: Dict[str, Any], status_code: int, cache_hit: bool):
    response = make_response(jsonify(payload), status_code)
    response.headers["X-Cache-Hit"] = "true" if cache_hit else "false"
    return response


def validate_payment_payload(payload: Any):
    if payload is None:
        return "Request body must be valid JSON."

    if not isinstance(payload, dict):
        return "Request body must be a JSON object."

    if "amount" not in payload or "currency" not in payload:
        return "Request body must include 'amount' and 'currency'."

    return None


def new_expiry_time() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)


def clear_expired_keys():
    now = datetime.now(timezone.utc)

    with store_lock:
        expired_keys = [
            key
            for key, record in idempotency_store.items()
            if record.get("expires_at") is not None and record["expires_at"] <= now
        ]

        for key in expired_keys:
            del idempotency_store[key]


@app.get("/")
def dashboard():
    ttl_label = "24 hours" if IDEMPOTENCY_TTL_SECONDS == DEFAULT_TTL_SECONDS else f"{IDEMPOTENCY_TTL_SECONDS} seconds"
    return render_template_string(DASHBOARD_TEMPLATE, ttl_label=ttl_label)


@app.post("/process-payment")
def process_payment():
    clear_expired_keys()

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return (
            jsonify(
                {
                    "status": STATUS_CONFLICT,
                    "message": "Idempotency-Key header is required.",
                }
            ),
            400,
        )

    payload = request.get_json(silent=True)
    validation_error = validate_payment_payload(payload)
    if validation_error:
        return (
            jsonify({"status": STATUS_CONFLICT, "message": validation_error}),
            400,
        )

    payload_hash = canonical_body_hash(payload)
    normalized_key = idempotency_key.strip()

    while True:
        with store_lock:
            record = idempotency_store.get(normalized_key)

            if record is None:
                completion_condition = threading.Condition(store_lock)
                idempotency_store[normalized_key] = {
                    "payload_hash": payload_hash,
                    "status": "processing",
                    "condition": completion_condition,
                    "response_body": None,
                    "expires_at": new_expiry_time(),
                }
                break

            if record["payload_hash"] != payload_hash:
                return (
                    jsonify(
                        {
                            "status": STATUS_CONFLICT,
                            "message": "Idempotency key already used for a different request body.",
                        }
                    ),
                    409,
                )

            if record["status"] == "completed":
                replay_body = {
                    "status": STATUS_DUPLICATE,
                    "message": record["response_body"]["message"],
                }
                return build_api_response(replay_body, 200, True)

            # The same payment is already running. Wait here so we can
            # return the saved result instead of charging again.
            record["condition"].wait()

    try:
        time.sleep(2)
        success_body = {
            "status": STATUS_NEW_SUCCESS,
            "message": f"Charged {payload['amount']} {payload['currency']}",
        }

        with store_lock:
            record = idempotency_store.get(normalized_key)
            if record is not None:
                record["status"] = "completed"
                record["response_body"] = success_body
                record["expires_at"] = new_expiry_time()
                record["condition"].notify_all()

        return build_api_response(success_body, 201, False)
    except Exception:
        with store_lock:
            record = idempotency_store.pop(normalized_key, None)
            if record is not None:
                record["condition"].notify_all()
        raise


@app.delete("/admin/idempotency-keys/<key>")
def evict_idempotency_key(key: str):
    clear_expired_keys()

    normalized_key = key.strip()

    with store_lock:
        record = idempotency_store.get(normalized_key)

        if record is None:
            return (
                jsonify(
                    {
                        "status": STATUS_CONFLICT,
                        "message": "Idempotency key not found.",
                    }
                ),
                404,
            )

        if record["status"] == "processing":
            return (
                jsonify(
                    {
                        "status": STATUS_CONFLICT,
                        "message": "Cannot evict a key that is currently processing.",
                    }
                ),
                409,
            )

        del idempotency_store[normalized_key]

    return (
        jsonify(
            {
                "status": STATUS_ADMIN,
                "message": "Key manually evicted from cache.",
            }
        ),
        200,
    )


def reset_store():
    with store_lock:
        idempotency_store.clear()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)


