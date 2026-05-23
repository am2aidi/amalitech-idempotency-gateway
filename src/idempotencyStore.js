function createDeferred() {
  let resolve;
  let reject;

  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });

  return { promise, resolve, reject };
}

class IdempotencyStore {
  constructor(options = {}) {
    this.ttlMs = options.ttlMs ?? 24 * 60 * 60 * 1000;
    this.records = new Map();

    const sweepIntervalMs = Math.max(1_000, Math.floor(this.ttlMs / 2));
    this.cleanupTimer = setInterval(() => this.purgeExpired(), sweepIntervalMs);
    this.cleanupTimer.unref?.();
  }

  begin(key, fingerprint) {
    this.purgeExpired();

    const existingRecord = this.records.get(key);

    if (!existingRecord) {
      const deferred = createDeferred();

      this.records.set(key, {
        fingerprint,
        status: "processing",
        deferred,
        createdAt: Date.now(),
      });

      return { kind: "started" };
    }

    if (existingRecord.fingerprint !== fingerprint) {
      return { kind: "conflict" };
    }

    if (existingRecord.status === "completed") {
      return {
        kind: "replay",
        response: existingRecord.response,
      };
    }

    return {
      kind: "wait",
      promise: existingRecord.deferred.promise,
    };
  }

  complete(key, response) {
    const record = this.records.get(key);

    if (!record || record.status !== "processing") {
      return;
    }

    const completedAt = Date.now();
    record.status = "completed";
    record.response = response;
    record.completedAt = completedAt;
    record.expiresAt = completedAt + this.ttlMs;
    record.deferred.resolve(response);
  }

  fail(key, error) {
    const record = this.records.get(key);

    if (!record || record.status !== "processing") {
      return;
    }

    this.records.delete(key);
    record.deferred.reject(error);
  }

  purgeExpired(now = Date.now()) {
    for (const [key, record] of this.records.entries()) {
      if (record.status === "completed" && record.expiresAt <= now) {
        this.records.delete(key);
      }
    }
  }

  shutdown() {
    clearInterval(this.cleanupTimer);
  }
}

module.exports = {
  IdempotencyStore,
};
