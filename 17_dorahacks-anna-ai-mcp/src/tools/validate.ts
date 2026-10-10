import { isRecord } from "../protocol/validate.js";
import type { ValidationError } from "./types.js";

/**
 * Hand-rolled JSON Schema subset validator for MCP tool `inputSchema` / `outputSchema`.
 * Zero dependencies; deterministic. Any non-empty `ValidationError[]` maps to a JSON-RPC
 * -32602 with `data: { errors }` at the dispatch layer.
 *
 * Supported keyword surface (the frozen tool set depends on exactly this):
 *   type, required, properties, additionalProperties, items, enum, minimum, maximum,
 *   minLength, maxLength, pattern, default, oneOf, format (uri | date-time | date),
 *   minItems, maxItems.
 */

const URI_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;
const DATE_TIME_RE =
  /^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})?$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function checkFormat(
  value: unknown,
  format: string,
  path: string,
  errors: ValidationError[],
): void {
  if (typeof value !== "string") return;
  if (format === "uri" || format === "uri-reference") {
    if (!URI_RE.test(value)) {
      errors.push({ path, message: `must be a valid URI (format "${format}")` });
    }
  } else if (format === "date-time") {
    if (!DATE_TIME_RE.test(value)) {
      errors.push({ path, message: `must be an ISO 8601 date-time (format "date-time")` });
    }
  } else if (format === "date") {
    if (!DATE_RE.test(value)) {
      errors.push({ path, message: `must be a full date (format "date")` });
    }
  }
}

function validateNode(
  schema: Record<string, unknown>,
  value: unknown,
  path: string,
  errors: ValidationError[],
): void {
  const type = schema["type"];
  if (typeof type === "string") {
    const actual = typeOf(value);
    const ok =
      (type === "number" && (actual === "number" || actual === "integer")) ||
      (type !== "number" && actual === type);
    if (!ok) {
      errors.push({ path, message: `expected type "${type}", got "${actual}"` });
      return;
    }
  }

  const enumVals = schema["enum"];
  if (Array.isArray(enumVals)) {
    const hit = enumVals.some((e) => JSON.stringify(e) === JSON.stringify(value));
    if (!hit) {
      errors.push({ path, message: `value must be one of ${JSON.stringify(enumVals)}` });
    }
  }

  const format = schema["format"];
  if (typeof format === "string") {
    checkFormat(value, format, path, errors);
  }

  const oneOf = schema["oneOf"];
  if (Array.isArray(oneOf) && oneOf.length > 0) {
    const anyMatch = oneOf.some((branch) => {
      const scratch: ValidationError[] = [];
      if (isRecord(branch)) validateNode(branch, value, path, scratch);
      return scratch.length === 0;
    });
    if (!anyMatch) {
      errors.push({ path, message: `does not match any schema in "oneOf"` });
    }
    return;
  }

  // string
  if (typeof value === "string") {
    const min = schema["minLength"];
    if (typeof min === "number" && value.length < min) {
      errors.push({ path, message: `length ${value.length} < minLength ${min}` });
    }
    const max = schema["maxLength"];
    if (typeof max === "number" && value.length > max) {
      errors.push({ path, message: `length ${value.length} > maxLength ${max}` });
    }
    const pattern = schema["pattern"];
    if (typeof pattern === "string") {
      let re: RegExp | undefined;
      try {
        re = new RegExp(pattern);
      } catch {
        re = undefined;
      }
      if (re !== undefined && !re.test(value)) {
        errors.push({ path, message: `does not match pattern /${pattern}/` });
      }
    }
  }

  // number
  if (typeof value === "number") {
    const min = schema["minimum"];
    if (typeof min === "number" && value < min) {
      errors.push({ path, message: `${value} < minimum ${min}` });
    }
    const max = schema["maximum"];
    if (typeof max === "number" && value > max) {
      errors.push({ path, message: `${value} > maximum ${max}` });
    }
  }

  // array
  if (Array.isArray(value)) {
    const minItems = schema["minItems"];
    if (typeof minItems === "number" && value.length < minItems) {
      errors.push({ path, message: `length ${value.length} < minItems ${minItems}` });
    }
    const maxItems = schema["maxItems"];
    if (typeof maxItems === "number" && value.length > maxItems) {
      errors.push({ path, message: `length ${value.length} > maxItems ${maxItems}` });
    }
    const items = schema["items"];
    if (isRecord(items)) {
      for (const [i, el] of value.entries()) {
        validateNode(items, el, `${path}[${i}]`, errors);
      }
    }
  }

  // object
  if (isRecord(value)) {
    const required = schema["required"];
    if (Array.isArray(required)) {
      for (const name of required) {
        if (typeof name !== "string") continue;
        if (value[name] === undefined) {
          errors.push({
            path: path.length === 0 ? name : `${path}.${name}`,
            message: `missing required property "${name}"`,
          });
        }
      }
    }

    const properties = schema["properties"];
    if (isRecord(properties)) {
      for (const [key, propSchema] of Object.entries(properties)) {
        if (!isRecord(propSchema)) continue;
        const child = value[key];
        if (child === undefined) continue;
        const childPath = path.length === 0 ? key : `${path}.${key}`;
        validateNode(propSchema, child, childPath, errors);
      }
    }

    const additional = schema["additionalProperties"];
    if (additional === false && isRecord(properties)) {
      const known = new Set(Object.keys(properties));
      for (const key of Object.keys(value)) {
        if (!known.has(key)) {
          const childPath = path.length === 0 ? key : `${path}.${key}`;
          errors.push({ path: childPath, message: `unexpected property "${key}"` });
        }
      }
    } else if (isRecord(additional)) {
      const known = new Set(isRecord(properties) ? Object.keys(properties) : []);
      for (const [key, child] of Object.entries(value)) {
        if (known.has(key)) continue;
        const childPath = path.length === 0 ? key : `${path}.${key}`;
        validateNode(additional, child, childPath, errors);
      }
    }
  }
}

export function validateAgainstSchema(
  schema: Record<string, unknown>,
  value: unknown,
): ValidationError[] {
  const errors: ValidationError[] = [];
  if (!isRecord(schema)) return errors;
  validateNode(schema, value, "", errors);
  return errors;
}

export function applyDefaults(
  schema: Record<string, unknown>,
  value: Record<string, unknown>,
): Record<string, unknown> {
  if (!isRecord(schema)) return value;
  const properties = schema["properties"];
  if (!isRecord(properties)) return value;
  const out: Record<string, unknown> = { ...value };
  for (const [key, propSchema] of Object.entries(properties)) {
    if (!isRecord(propSchema)) continue;
    if (out[key] === undefined && propSchema["default"] !== undefined) {
      out[key] = propSchema["default"];
    }
  }
  return out;
}
