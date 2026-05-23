const test = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/app");

async function startTestServer(options = {}) {
  const app = createApp(options);

  await new Promise((resolve) => {
    app.server.listen(0, resolve);
  });

  const address = app.server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;

  return {
    ...app,
    baseUrl,
    async close() {
      await new Promise((resolve, reject) => {
        app.server.close((error) => {
          if (error) {
            reject(error);
            return;
          }

          resolve();
        });
      });
      app.store.shutdown();
    },
  };
}

async function postPayment(baseUrl, key, payload) {
  const response = await fetch(`${baseUrl}/process-payment`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    },
    body: JSON.stringify(payload),
  });

  return {
    status: response.status,
    headers: {
      cacheHit: response.headers.get("x-cache-hit"),
    },
    body: await response.json(),
  };
}

test("processes a first-time payment request", async () => {
  const app = await startTestServer({ processingDelayMs: 40, ttlMs: 5_000 });

  try {
    const response = await postPayment(app.baseUrl, "txn-001", {
      amount: 100,
      currency: "GHS",
    });

    assert.equal(response.status, 201);
    assert.equal(response.headers.cacheHit, "false");
    assert.equal(response.body.message, "Charged 100 GHS");
    assert.equal(response.body.idempotencyKey, "txn-001");
    assert.ok(response.body.paymentId);
    assert.ok(response.body.processedAt);
  } finally {
    await app.close();
  }
});

test("returns the original response immediately for duplicate requests", async () => {
  const app = await startTestServer({ processingDelayMs: 40, ttlMs: 5_000 });
  const payload = { amount: 100, currency: "GHS" };

  try {
    const firstResponse = await postPayment(app.baseUrl, "txn-002", payload);
    const secondResponse = await postPayment(app.baseUrl, "txn-002", payload);

    assert.equal(secondResponse.status, firstResponse.status);
    assert.equal(secondResponse.headers.cacheHit, "true");
    assert.deepEqual(secondResponse.body, firstResponse.body);
  } finally {
    await app.close();
  }
});

test("rejects reused keys with a different payment body", async () => {
  const app = await startTestServer({ processingDelayMs: 40, ttlMs: 5_000 });

  try {
    const firstResponse = await postPayment(app.baseUrl, "txn-003", {
      amount: 100,
      currency: "GHS",
    });

    assert.equal(firstResponse.status, 201);

    const secondResponse = await postPayment(app.baseUrl, "txn-003", {
      amount: 500,
      currency: "GHS",
    });

    assert.equal(secondResponse.status, 409);
    assert.equal(
      secondResponse.body.error,
      "Idempotency key already used for a different request body.",
    );
  } finally {
    await app.close();
  }
});

test("waits for an in-flight request and replays its result", async () => {
  const app = await startTestServer({ processingDelayMs: 120, ttlMs: 5_000 });
  const payload = { amount: 250, currency: "USD" };

  try {
    const firstRequest = postPayment(app.baseUrl, "txn-004", payload);
    await new Promise((resolve) => setTimeout(resolve, 25));
    const secondRequest = postPayment(app.baseUrl, "txn-004", payload);

    const [firstResponse, secondResponse] = await Promise.all([firstRequest, secondRequest]);

    assert.equal(firstResponse.status, 201);
    assert.equal(secondResponse.status, 201);
    assert.equal(firstResponse.headers.cacheHit, "false");
    assert.equal(secondResponse.headers.cacheHit, "true");
    assert.deepEqual(secondResponse.body, firstResponse.body);
  } finally {
    await app.close();
  }
});
