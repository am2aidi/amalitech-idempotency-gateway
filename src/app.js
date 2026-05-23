const http = require("node:http");
const { createHash, randomUUID } = require("node:crypto");
const { IdempotencyStore } = require("./idempotencyStore");
const { validatePaymentPayload } = require("./paymentValidator");
const { stableStringify } = require("./stableStringify");

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJsonBody(req) {
  let rawBody = "";

  for await (const chunk of req) {
    rawBody += chunk;
  }

  if (!rawBody) {
    return {};
  }

  try {
    return JSON.parse(rawBody);
  } catch (error) {
    const parseError = new Error("Request body must be valid JSON.");
    parseError.statusCode = 400;
    throw parseError;
  }
}

function buildJsonResponse(statusCode, payload, headers = {}) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    },
    body: JSON.stringify(payload),
  };
}

function sendStoredResponse(res, response, cacheHit) {
  res.writeHead(response.statusCode, {
    ...response.headers,
    "X-Cache-Hit": cacheHit ? "true" : "false",
  });
  res.end(response.body);
}

function sendJson(res, statusCode, payload, headers = {}) {
  const response = buildJsonResponse(statusCode, payload, headers);
  sendStoredResponse(res, response, headers["X-Cache-Hit"] === "true");
}

function createRequestFingerprint(payload) {
  return createHash("sha256").update(stableStringify(payload)).digest("hex");
}

function createApp(options = {}) {
  const processingDelayMs = options.processingDelayMs ?? 2_000;
  const store = options.store ?? new IdempotencyStore({ ttlMs: options.ttlMs });

  const server = http.createServer((req, res) => {
    void handleRequest(req, res, { processingDelayMs, store });
  });

  return { server, store };
}

async function handleRequest(req, res, context) {
  try {
    const url = new URL(req.url, "http://localhost");

    if (req.method === "GET" && url.pathname === "/health") {
      return sendJson(res, 200, { status: "ok" });
    }

    if (url.pathname !== "/process-payment") {
      return sendJson(res, 404, { error: "Route not found." });
    }

    if (req.method !== "POST") {
      return sendJson(res, 405, { error: "Method not allowed." }, { Allow: "POST" });
    }

    const idempotencyKey = req.headers["idempotency-key"];

    if (typeof idempotencyKey !== "string" || idempotencyKey.trim() === "") {
      return sendJson(res, 400, { error: "Idempotency-Key header is required." });
    }

    const payload = await readJsonBody(req);
    const validationError = validatePaymentPayload(payload);

    if (validationError) {
      return sendJson(res, 400, { error: validationError });
    }

    const normalizedKey = idempotencyKey.trim();
    const fingerprint = createRequestFingerprint(payload);
    const attempt = context.store.begin(normalizedKey, fingerprint);

    if (attempt.kind === "conflict") {
      return sendJson(res, 409, {
        error: "Idempotency key already used for a different request body.",
      });
    }

    if (attempt.kind === "replay") {
      return sendStoredResponse(res, attempt.response, true);
    }

    if (attempt.kind === "wait") {
      const response = await attempt.promise;
      return sendStoredResponse(res, response, true);
    }

    try {
      await delay(context.processingDelayMs);

      const response = buildJsonResponse(201, {
        message: `Charged ${payload.amount} ${payload.currency}`,
        paymentId: randomUUID(),
        idempotencyKey: normalizedKey,
        processedAt: new Date().toISOString(),
      });

      context.store.complete(normalizedKey, response);
      return sendStoredResponse(res, response, false);
    } catch (error) {
      context.store.fail(normalizedKey, error);
      throw error;
    }
  } catch (error) {
    if (res.headersSent) {
      res.end();
      return;
    }

    const statusCode = error.statusCode ?? 500;
    return sendJson(res, statusCode, {
      error: statusCode === 500 ? "Internal server error." : error.message,
    });
  }
}

module.exports = {
  createApp,
  createRequestFingerprint,
};
