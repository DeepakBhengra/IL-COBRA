export const MAX_ERROR_FIELD_INPUT_LEN = 30;

export type FocusedSearchResult =
  | { kind: "error_code"; value: string }
  | { kind: "error_field"; value: string }
  | { kind: "invalid"; message: string };

const ERROR_FIELD_PATTERN = /^[A-Za-z][A-Za-z0-9-]*$/;

export function classifyFocusedSearchInput(raw: string): FocusedSearchResult {
  const trimmed = raw.trim();
  if (!trimmed) {
    return {
      kind: "invalid",
      message: "Enter a 2-character error code (e.g. EV) or an error field name (e.g. ERROR-SHIP-VIA).",
    };
  }

  if (trimmed.length === 2 && /^[A-Za-z0-9]{2}$/.test(trimmed)) {
    return { kind: "error_code", value: trimmed.toUpperCase() };
  }

  if (
    trimmed.length >= 3 &&
    trimmed.length <= MAX_ERROR_FIELD_INPUT_LEN &&
    trimmed.includes("-") &&
    ERROR_FIELD_PATTERN.test(trimmed)
  ) {
    return {
      kind: "error_field",
      value: trimmed.toUpperCase().slice(0, MAX_ERROR_FIELD_INPUT_LEN),
    };
  }

  if (trimmed.length === 2) {
    return {
      kind: "invalid",
      message: "Error codes must be exactly 2 alphanumeric characters (e.g. EV).",
    };
  }

  if (trimmed.length > MAX_ERROR_FIELD_INPUT_LEN) {
    return {
      kind: "invalid",
      message: `Error field names must be at most ${MAX_ERROR_FIELD_INPUT_LEN} characters.`,
    };
  }

  if (!trimmed.includes("-")) {
    return {
      kind: "invalid",
      message:
        "Enter a 2-character error code (e.g. EV) or a hyphenated error field name (e.g. ERROR-SHIP-VIA).",
    };
  }

  return {
    kind: "invalid",
    message:
      "Error field names may only contain letters, digits, and hyphens, and must start with a letter.",
  };
}
