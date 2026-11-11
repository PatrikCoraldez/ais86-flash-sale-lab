import type { CartLine, Product } from './types';

export const MAX_QUANTITY = 5;
export const MAX_DISTINCT_PRODUCTS = 6;

export type AddResult = 'added' | 'max' | 'out' | 'limit';

export type CartProblem = 'empty' | 'missing' | 'limit' | 'out' | 'stock' | 'quantity';

export type CartValidation =
  | { ok: true }
  | { ok: false; problem: CartProblem; productId?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function productIdIsValid(value: unknown): value is string {
  return typeof value === 'string' && /^[a-z0-9][a-z0-9-]{0,63}$/i.test(value);
}

function integerQuantity(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return null;
  }
  if (value < 1 || value > MAX_QUANTITY) {
    return null;
  }
  return value;
}

export function cartCount(lines: readonly CartLine[]): number {
  return lines.reduce((total, line) => total + line.quantity, 0);
}

export function maxAddable(product: Product): number {
  return Math.min(MAX_QUANTITY, Math.max(0, Math.trunc(product.stock)));
}

export function findLine(lines: readonly CartLine[], productId: string): CartLine | undefined {
  return lines.find((line) => line.productId === productId);
}

export function addLine(
  lines: readonly CartLine[],
  product: Product
): { lines: CartLine[]; result: AddResult } {
  const limit = maxAddable(product);
  const current = findLine(lines, product.id);
  const currentQuantity = current?.quantity ?? 0;

  if (limit <= 0) {
    return { lines: [...lines], result: 'out' };
  }
  if (currentQuantity >= limit) {
    return { lines: [...lines], result: 'max' };
  }
  if (!current && lines.length >= MAX_DISTINCT_PRODUCTS) {
    return { lines: [...lines], result: 'limit' };
  }
  if (current) {
    return {
      lines: lines.map((line) =>
        line.productId === product.id ? { ...line, quantity: currentQuantity + 1 } : line
      ),
      result: 'added'
    };
  }
  return {
    lines: [...lines, { productId: product.id, quantity: 1 }],
    result: 'added'
  };
}

export function setLineQuantity(
  lines: readonly CartLine[],
  product: Product,
  quantity: number
): CartLine[] {
  const limit = maxAddable(product);
  const nextQuantity = Math.max(1, Math.min(MAX_QUANTITY, Math.trunc(quantity), limit || 1));
  return lines.map((line) =>
    line.productId === product.id ? { ...line, quantity: nextQuantity } : line
  );
}

export function removeLine(lines: readonly CartLine[], productId: string): CartLine[] {
  return lines.filter((line) => line.productId !== productId);
}

export function sanitizeLines(raw: unknown, products?: readonly Product[]): CartLine[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  const productIndex = products
    ? new Map(products.map((product) => [product.id, product] as const))
    : null;
  const merged = new Map<string, number>();

  for (const entry of raw) {
    if (!isRecord(entry)) {
      continue;
    }
    if (!productIdIsValid(entry.productId)) {
      continue;
    }
    const quantity = integerQuantity(entry.quantity);
    if (quantity === null) {
      continue;
    }

    const product = productIndex ? productIndex.get(entry.productId) : undefined;
    if (productIndex && !product) {
      continue;
    }

    let nextQuantity = quantity;
    if (product) {
      const limit = maxAddable(product);
      nextQuantity = limit <= 0 ? 1 : Math.min(quantity, limit);
    }

    const existing = merged.get(entry.productId) ?? 0;
    merged.set(entry.productId, Math.max(existing, nextQuantity));
  }

  return Array.from(merged, ([productId, quantity]) => ({ productId, quantity })).slice(
    0,
    MAX_DISTINCT_PRODUCTS
  );
}

export function validateCart(
  lines: readonly CartLine[],
  products: readonly Product[]
): CartValidation {
  if (lines.length === 0) {
    return { ok: false, problem: 'empty' };
  }
  if (lines.length > MAX_DISTINCT_PRODUCTS) {
    return { ok: false, problem: 'limit' };
  }

  const seen = new Set<string>();
  for (const line of lines) {
    if (seen.has(line.productId)) {
      return { ok: false, problem: 'quantity', productId: line.productId };
    }
    seen.add(line.productId);

    if (!Number.isInteger(line.quantity) || line.quantity < 1 || line.quantity > MAX_QUANTITY) {
      return { ok: false, problem: 'quantity', productId: line.productId };
    }

    const product = products.find((item) => item.id === line.productId);
    if (!product) {
      return { ok: false, problem: 'missing', productId: line.productId };
    }
    if (product.stock <= 0) {
      return { ok: false, problem: 'out', productId: line.productId };
    }
    if (line.quantity > product.stock) {
      return { ok: false, problem: 'stock', productId: line.productId };
    }
  }

  return { ok: true };
}

export function toOrderItems(
  lines: readonly CartLine[],
  products: readonly Product[]
): Array<{ product_id: string; quantity: number }> {
  return lines
    .map((line) => {
      const product = products.find((item) => item.id === line.productId);
      return product ? { product_id: product.id, quantity: line.quantity } : null;
    })
    .filter((item): item is { product_id: string; quantity: number } => item !== null)
    .sort((left, right) => left.product_id.localeCompare(right.product_id));
}
