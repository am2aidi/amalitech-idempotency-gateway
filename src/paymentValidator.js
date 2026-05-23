function validatePaymentPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return "Request body must be a JSON object.";
  }

  if (typeof payload.amount !== "number" || !Number.isFinite(payload.amount) || payload.amount <= 0) {
    return "amount must be a positive number.";
  }

  if (typeof payload.currency !== "string" || !/^[A-Z]{3}$/.test(payload.currency)) {
    return "currency must be a 3-letter uppercase ISO code.";
  }

  return null;
}

module.exports = {
  validatePaymentPayload,
};
