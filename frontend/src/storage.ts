import { sanitizeLines } from './cart';
import type { CartLine } from './types';

const cartKey = 'flash-sale:cart:v1';
const attemptKey = 'flash-sale:attempt:v1';
const cartVersion = 1;
const idempotencyPattern = /^[A-Za-z0-9_-]{8,80}$/;

export interface AttemptRecord {
  key: string;
  signature: string;
}

let memoryAttempt: AttemptRecord | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function storageFor(kind: 'local' | 'session'): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function readJson(storage: Storage | null, key: string): unknown {
  if (!storage) {
    return null;
  }
  try {
    const raw = storage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

function writeJson(storage: Storage | null, key: string, value: unknown): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    return;
  }
}

function removeKey(storage: Storage | null, key: string): void {
  if (!storage) {
    return;
  }
  try {
    storage.removeItem(key);
  } catch {
    return;
  }
}

export function readStoredCart(): CartLine[] {
  const parsed = readJson(storageFor('local'), cartKey);
  if (!isRecord(parsed) || parsed.version !== cartVersion || !Array.isArray(parsed.items)) {
    return [];
  }
  return sanitizeLines(parsed.items);
}

export function writeStoredCart(lines: readonly CartLine[]): void {
  writeJson(storageFor('local'), cartKey, {
    version: cartVersion,
    items: lines.map((line) => ({ productId: line.productId, quantity: line.quantity }))
  });
}

export function readAttempt(): AttemptRecord | null {
  const parsed = readJson(storageFor('session'), attemptKey);
  if (isRecord(parsed)) {
    if (
      typeof parsed.key === 'string' &&
      idempotencyPattern.test(parsed.key) &&
      typeof parsed.signature === 'string' &&
      parsed.signature.length > 0
    ) {
      return { key: parsed.key, signature: parsed.signature };
    }
  }
  return memoryAttempt;
}

export function saveAttempt(record: AttemptRecord): void {
  memoryAttempt = record;
  writeJson(storageFor('session'), attemptKey, record);
}

export function clearAttempt(): void {
  memoryAttempt = null;
  removeKey(storageFor('session'), attemptKey);
}

export function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  const uuid =
    typeof cryptoApi.randomUUID === 'function' ? cryptoApi.randomUUID() : fallbackUuid(cryptoApi);
  return `fs-${uuid}`;
}

function fallbackUuid(cryptoApi: Crypto): string {
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
