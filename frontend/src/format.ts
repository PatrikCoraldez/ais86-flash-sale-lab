const moneyFormatter = new Intl.NumberFormat('es-PE', {
  style: 'currency',
  currency: 'PEN',
  currencyDisplay: 'symbol',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const dateTimeFormatter = new Intl.DateTimeFormat('es-PE', {
  dateStyle: 'long',
  timeStyle: 'short'
});

export function formatMoney(cents: number): string {
  if (!Number.isFinite(cents)) {
    return '—';
  }
  return moneyFormatter.format(cents / 100);
}

export function parseDate(value: string): Date | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string): string {
  const date = parseDate(value);
  return date ? dateTimeFormatter.format(date) : 'Fecha no disponible';
}

export function normalizeText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('es')
    .trim();
}
