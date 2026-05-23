const { createApp } = require("./src/app");

const port = Number(process.env.PORT ?? 3000);
const { server, store } = createApp({
  ttlMs: Number(process.env.IDEMPOTENCY_TTL_MS ?? 24 * 60 * 60 * 1000),
  processingDelayMs: Number(process.env.PROCESSING_DELAY_MS ?? 2_000),
});

server.listen(port, () => {
  console.log(`Idempotency Gateway listening on port ${port}`);
});

function shutdown() {
  store.shutdown();
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
