function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }

  const sortedKeys = Object.keys(value).sort();
  const serializedEntries = sortedKeys.map((key) => {
    return `${JSON.stringify(key)}:${stableStringify(value[key])}`;
  });

  return `{${serializedEntries.join(",")}}`;
}

module.exports = {
  stableStringify,
};
