export interface ResourceJsonSchema {
  type?: string | string[]
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  properties?: Record<string, ResourceJsonSchema>
  items?: ResourceJsonSchema
  required?: string[]
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  minItems?: number
  maxItems?: number
  uniqueItems?: boolean
}

export interface ResourceSchemaField {
  name: string
  schema: ResourceJsonSchema
  required: boolean
}

const STRUCTURED_FIELD_TYPES = new Set(['string', 'integer', 'number', 'boolean'])

export function resourceSchemaFields(schemaValue: Record<string, unknown>): ResourceSchemaField[] | null {
  const schema = schemaValue as ResourceJsonSchema
  if (schema.type !== 'object' || !schema.properties || Array.isArray(schema.properties)) return null

  const required = new Set(schema.required || [])
  const fields = Object.entries(schema.properties).map(([name, fieldSchema]) => ({
    name,
    schema: fieldSchema,
    required: required.has(name),
  }))
  return fields.every(field => isStructuredField(field.schema))
    ? fields
    : null
}

export function createResourceDraft(schema: Record<string, unknown>, configuredValue?: unknown): unknown {
  const fields = resourceSchemaFields(schema)
  if (!fields) {
    if (configuredValue === undefined || configuredValue === null) return ''
    return typeof configuredValue === 'string'
      ? configuredValue
      : JSON.stringify(configuredValue, null, 2)
  }
  const configured = configuredValue && typeof configuredValue === 'object' && !Array.isArray(configuredValue)
    ? configuredValue as Record<string, unknown>
    : {}
  return Object.fromEntries(
    fields.map(field => [
      field.name,
      configured[field.name] === undefined ? initialFieldValue(field.schema) : configured[field.name],
    ]),
  )
}

export function resourceDraftComplete(schema: Record<string, unknown>, draft: unknown): boolean {
  const fields = resourceSchemaFields(schema)
  if (!fields) return typeof draft === 'string' && draft.trim().length > 0
  if (!draft || typeof draft !== 'object' || Array.isArray(draft)) return false
  const values = draft as Record<string, unknown>
  return fields
    .filter(field => field.required)
    .every(field => resourceFieldComplete(field.schema, values[field.name]))
}

export function resourceDraftValue(schema: Record<string, unknown>, draft: unknown): unknown {
  const fields = resourceSchemaFields(schema)
  if (!fields) {
    if (typeof draft !== 'string') return draft
    const raw = draft.trim()
    try {
      return JSON.parse(raw)
    } catch {
      return raw
    }
  }
  const values = draft && typeof draft === 'object' && !Array.isArray(draft)
    ? draft as Record<string, unknown>
    : {}
  return Object.fromEntries(
    fields
      .filter(field => field.required || !isEmptyResourceValue(values[field.name]))
      .map(field => [field.name, values[field.name]]),
  )
}

function initialFieldValue(schema: ResourceJsonSchema): unknown {
  if (schema.default !== undefined) return schema.default
  if (schema.type === 'boolean') return false
  if (schema.type === 'array') return []
  return null
}

function isEmptyResourceValue(value: unknown): boolean {
  return value === undefined || value === null ||
    (typeof value === 'string' && value.trim() === '') ||
    (Array.isArray(value) && value.length === 0)
}

function isStructuredField(schema: ResourceJsonSchema): boolean {
  if (schema.enum?.length) return true
  if (STRUCTURED_FIELD_TYPES.has(String(schema.type))) return true
  return schema.type === 'array' && schema.items?.type === 'string'
}

function resourceFieldComplete(schema: ResourceJsonSchema, value: unknown): boolean {
  if (isEmptyResourceValue(value)) return false
  if (schema.type !== 'array' || !Array.isArray(value)) return true
  return value.length >= Math.max(1, schema.minItems || 0) &&
    (schema.maxItems === undefined || value.length <= schema.maxItems)
}
