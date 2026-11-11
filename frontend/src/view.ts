import type { CartProblem } from './cart';
import {
  MAX_DISTINCT_PRODUCTS,
  MAX_QUANTITY,
  cartCount,
  maxAddable,
  validateCart
} from './cart';
import { el, icon } from './dom';
import { formatDateTime, formatMoney } from './format';
import { productImage } from './shell';
import type { CartLine, Catalog, NotificationStatus, Order, Product } from './types';

export type CatalogState = 'loading' | 'ready' | 'error';
export type PollState = 'idle' | 'polling' | 'timeout' | 'error';

export interface CartPanelContext {
  catalog: Catalog | null;
  catalogState: CatalogState;
  catalogMessage: string;
  cart: readonly CartLine[];
  orderError: string;
  orderErrorCode: string;
  creating: boolean;
}

export function applyStockChip(chip: HTMLElement, product: Product): void {
  chip.classList.remove('is-available', 'is-low', 'is-out');
  if (product.stock <= 0) {
    chip.textContent = 'Agotado';
    chip.classList.add('is-out');
    return;
  }
  if (product.stock <= 3) {
    chip.textContent = `Quedan ${product.stock}`;
    chip.classList.add('is-low');
    return;
  }
  chip.textContent = `Stock ${product.stock}`;
  chip.classList.add('is-available');
}

export function applyInCartChip(chip: HTMLElement, quantity: number): void {
  chip.hidden = quantity <= 0;
  chip.textContent = quantity > 0 ? `En carrito ${quantity}` : '';
}

export function configureAddButton(
  button: HTMLButtonElement,
  product: Product,
  quantity: number,
  locked: boolean
): void {
  const limit = maxAddable(product);
  const out = limit <= 0;
  const atMax = limit > 0 && quantity >= limit;
  const label = button.querySelector<HTMLElement>('[data-button-label]');
  const defaultLabel = button.dataset.labelDefault ?? 'Añadir';

  button.disabled = locked || out || atMax;
  if (out) {
    if (label) {
      label.textContent = 'Agotado';
    }
    button.setAttribute('aria-label', `${product.name}: agotado`);
    return;
  }
  if (atMax) {
    if (label) {
      label.textContent = 'Máximo';
    }
    button.setAttribute('aria-label', `Máximo en carrito para ${product.name}`);
    return;
  }
  if (label) {
    label.textContent = defaultLabel;
  }
  button.setAttribute('aria-label', `Añadir ${product.name} al carrito`);
}

export function renderProductCard(product: Product, quantity: number, locked: boolean): HTMLElement {
  const card = el('article', {
    class: 'card',
    'data-product': product.id
  });
  const media = el('div', { class: 'card-media' });
  media.append(productImage(product.image, 'card-image', true));

  const price = el('p', { class: 'card-price' });
  price.append(el('span', { class: 'price-current' }, formatMoney(product.price_cents)));
  if (product.original_price_cents > product.price_cents) {
    const oldPrice = el('s', { class: 'price-old' });
    oldPrice.append(
      el('span', { class: 'visually-hidden' }, 'Precio anterior: '),
      formatMoney(product.original_price_cents)
    );
    price.append(oldPrice);
  }

  const stockChip = el('span', { class: 'chip chip-stock', 'data-role': 'stock' });
  const inCartChip = el('span', { class: 'chip chip-incart', 'data-role': 'incart', hidden: true });
  const addButton = el('button', {
    type: 'button',
    class: 'button button-primary button-add',
    'data-add': product.id
  });
  addButton.dataset.labelDefault = 'Añadir';
  addButton.append(icon('plus'), el('span', { 'data-button-label': '' }, 'Añadir'));

  const body = el(
    'div',
    { class: 'card-body' },
    el('h3', { class: 'card-title' }, product.name),
    el('p', { class: 'card-description' }, product.description),
    price,
    el('div', { class: 'card-stock' }, stockChip, inCartChip),
    addButton
  );

  card.append(media, body);
  syncProductCard(card, product, quantity, locked);
  return card;
}

export function syncProductCard(
  card: HTMLElement,
  product: Product,
  quantity: number,
  locked: boolean
): void {
  const stockChip = card.querySelector<HTMLElement>('[data-role="stock"]');
  const inCartChip = card.querySelector<HTMLElement>('[data-role="incart"]');
  const addButton = card.querySelector<HTMLButtonElement>('[data-add]');
  if (stockChip) {
    applyStockChip(stockChip, product);
  }
  if (inCartChip) {
    applyInCartChip(inCartChip, quantity);
  }
  if (addButton) {
    configureAddButton(addButton, product, quantity, locked);
  }
  card.classList.toggle('is-in-cart', quantity > 0);
}

export function skeletonCards(): HTMLElement[] {
  return Array.from({ length: 6 }, () =>
    el(
      'article',
      { class: 'card skeleton-card', 'aria-hidden': 'true' },
      el('div', { class: 'skeleton-block skeleton-media' }),
      el('div', { class: 'skeleton-block skeleton-line skeleton-line-lg' }),
      el('div', { class: 'skeleton-block skeleton-line' }),
      el('div', { class: 'skeleton-block skeleton-line skeleton-line-sm' }),
      el('div', { class: 'skeleton-block skeleton-button' })
    )
  );
}

export function emptyCatalogNode(
  mode: 'search' | 'catalog',
  query: string,
  category: string
): HTMLElement {
  const wrapper = el('div', { class: 'empty-state' });
  wrapper.append(el('span', { class: 'empty-icon' }, icon(mode === 'search' ? 'search' : 'alert')));
  if (mode === 'search') {
    const parts: string[] = [];
    if (query.trim().length > 0) {
      parts.push(`No encontramos productos para “${query.trim()}”.`);
    }
    if (category !== 'all') {
      parts.push(`La categoría “${category}” no tiene coincidencias.`);
    }
    wrapper.append(
      el('h3', {}, 'Sin resultados'),
      el('p', {}, parts.join(' ')),
      actionButton('clear-filters', 'Limpiar filtros', 'close')
    );
    return wrapper;
  }
  wrapper.append(
    el('h3', {}, 'Catálogo vacío'),
    el('p', {}, 'No hay productos disponibles en este momento.'),
    actionButton('reload-catalog', 'Actualizar catálogo', 'refresh')
  );
  return wrapper;
}

function actionButton(
  action: string,
  label: string,
  iconName: 'close' | 'refresh' | 'arrow' | 'cart' | 'search',
  className = 'button button-secondary'
): HTMLButtonElement {
  const button = el('button', { type: 'button', class: className, 'data-action': action });
  button.append(icon(iconName), el('span', {}, label));
  return button;
}

export function orderWarningNode(
  problem: CartProblem,
  productName: string | null,
  withRefresh: boolean
): HTMLElement {
  const wrapper = el('div', { class: 'alert alert-warning', role: 'status' });
  wrapper.append(icon('alert'));
  const body = el('div', { class: 'alert-body' });
  body.append(el('p', {}, cartProblemText(problem, productName)));
  if (withRefresh) {
    body.append(actionButton('refresh-catalog', 'Actualizar disponibilidad', 'refresh'));
  }
  wrapper.append(body);
  return wrapper;
}

function cartProblemText(problem: CartProblem, productName: string | null): string {
  switch (problem) {
    case 'empty':
      return 'Tu carrito está vacío.';
    case 'limit':
      return `Puedes comprar hasta ${MAX_DISTINCT_PRODUCTS} productos distintos por pedido.`;
    case 'out':
      return `${productName ?? 'Un producto'} está agotado. Quítalo para continuar.`;
    case 'stock':
      return `La cantidad de ${productName ?? 'un producto'} supera el stock disponible. Ajusta el carrito o actualiza la disponibilidad.`;
    case 'missing':
      return 'Un producto ya no está disponible. Actualiza el catálogo y revisa tu carrito.';
    case 'quantity':
      return `Revisa las cantidades: deben ser enteros entre 1 y ${MAX_QUANTITY}.`;
  }
}

export function cartPanelNodes(context: CartPanelContext): Node[] {
  const units = cartCount(context.cart);

  if (context.catalogState !== 'ready' || !context.catalog) {
    return [catalogProblemNode(context, units)];
  }

  if (context.cart.length === 0) {
    return [emptyCartNode()];
  }

  const products = context.catalog.items;
  const validation = validateCart(context.cart, products);
  const totalCents = context.cart.reduce((total, line) => {
    const product = products.find((item) => item.id === line.productId);
    return product ? total + product.price_cents * line.quantity : total;
  }, 0);

  const list = el('ul', { class: 'cart-list' });
  for (const line of context.cart) {
    const product = products.find((item) => item.id === line.productId);
    if (!product) {
      continue;
    }
    list.append(cartItemNode(product, line, context.creating));
  }

  const summary = el('div', { class: 'cart-summary' });
  const totals = el('dl', { class: 'totals' });
  totals.append(
    el('div', { class: 'total-row' }, el('dt', {}, 'Subtotal'), el('dd', {}, formatMoney(totalCents))),
    el('div', { class: 'total-row total-row-strong' }, el('dt', {}, 'Total'), el('dd', {}, formatMoney(totalCents)))
  );

  const notes = el(
    'div',
    { class: 'cart-notes', id: 'cart-terms' },
    el('p', {}, `Máximo ${MAX_QUANTITY} unidades por producto y ${MAX_DISTINCT_PRODUCTS} productos distintos por pedido.`),
    el('p', {}, 'El stock se descuenta cuando el servidor confirma el pedido.'),
    el('p', {}, 'Pago simulado: no se procesa ningún cobro.')
  );

  const confirmLabel = context.creating
    ? 'Confirmando pedido…'
    : isNetworkRetry(context.orderErrorCode)
      ? 'Reintentar confirmación'
      : 'Confirmar pedido';
  const confirmButton = el('button', {
    type: 'button',
    class: 'button button-primary button-full',
    'data-action': 'confirm',
    'data-focus-key': 'confirm',
    'aria-describedby': 'cart-terms'
  });
  confirmButton.disabled = context.creating || !validation.ok;
  confirmButton.append(icon('check'), el('span', { 'data-confirm-label': '' }, confirmLabel));

  summary.append(totals);

  if (context.orderError) {
    summary.append(orderErrorNode(context.orderError, context.orderErrorCode));
  }
  if (!validation.ok) {
    const problem = validation.problem;
    const productName = validation.productId
      ? products.find((item) => item.id === validation.productId)?.name ?? null
      : null;
    summary.append(
      orderWarningNode(
        problem,
        productName,
        problem === 'out' || problem === 'stock' || problem === 'missing'
      )
    );
  }

  if (context.creating) {
    summary.append(
      el(
        'p',
        { class: 'cart-processing', role: 'status' },
        'Confirmando el pedido ante el servidor. No cierres esta ventana.'
      )
    );
  }

  summary.append(notes, confirmButton);

  return [list, summary];
}

function isNetworkRetry(code: string): boolean {
  return code === 'NETWORK_ERROR' || code === 'NETWORK_TIMEOUT' || code === 'RESPONSE_INVALID';
}

function orderErrorNode(message: string, code: string): HTMLElement {
  const wrapper = el('div', {
    class: 'alert alert-error',
    role: 'alert',
    tabindex: '-1',
    'data-order-error': ''
  });
  wrapper.append(icon('alert'));
  const body = el('div', { class: 'alert-body' }, el('p', {}, message));
  if (code === 'OUT_OF_STOCK') {
    body.append(actionButton('refresh-catalog', 'Actualizar disponibilidad', 'refresh'));
  }
  wrapper.append(body);
  return wrapper;
}

function catalogProblemNode(context: CartPanelContext, units: number): HTMLElement {
  const wrapper = el('div', { class: 'panel-message' });
  wrapper.append(
    el('span', { class: 'panel-message-icon' }, icon(context.catalogState === 'error' ? 'alert' : 'cart')),
    el(
      'h3',
      {},
      context.catalogState === 'error' ? 'No pudimos cargar tu carrito' : 'Cargando tu carrito'
    ),
    el(
      'p',
      {},
      context.catalogState === 'error'
        ? context.catalogMessage
        : 'Estamos consultando el catálogo para mostrar precios y disponibilidad.'
    ),
    el(
      'p',
      { class: 'panel-message-meta' },
      `Tu selección guardada tiene ${units} ${units === 1 ? 'unidad' : 'unidades'}.`
    )
  );
  if (context.catalogState === 'error') {
    wrapper.append(actionButton('reload-catalog', 'Reintentar catálogo', 'refresh'));
  }
  return wrapper;
}

function emptyCartNode(): HTMLElement {
  const wrapper = el('div', { class: 'panel-message' });
  wrapper.append(
    el('span', { class: 'panel-message-icon' }, icon('cart')),
    el('h3', {}, 'Tu carrito está vacío'),
    el('p', {}, 'Explora el drop y añade audio u objetos de escritorio. Las cantidades se guardan en este navegador.'),
    actionButton('browse', 'Ver el catálogo', 'arrow', 'button button-primary')
  );
  return wrapper;
}

function cartItemNode(product: Product, line: CartLine, creating: boolean): HTMLElement {
  const limit = maxAddable(product);
  const media = el('div', { class: 'cart-item-media' });
  media.append(productImage(product.image, 'cart-image', true));

  const removeButton = el('button', {
    type: 'button',
    class: 'icon-button remove-button',
    'data-action': 'remove',
    'data-product-id': product.id,
    'data-focus-key': `remove-${product.id}`,
    'aria-label': `Quitar ${product.name} del carrito`
  });
  removeButton.disabled = creating;
  removeButton.append(icon('trash'));

  const minusButton = el('button', {
    type: 'button',
    class: 'qty-button',
    'data-action': 'qty-minus',
    'data-product-id': product.id,
    'data-focus-key': `qty-minus-${product.id}`,
    'aria-label': `Quitar una unidad de ${product.name}`
  });
  minusButton.disabled = creating || line.quantity <= 1;
  minusButton.append(icon('minus'));

  const plusButton = el('button', {
    type: 'button',
    class: 'qty-button',
    'data-action': 'qty-plus',
    'data-product-id': product.id,
    'data-focus-key': `qty-plus-${product.id}`,
    'aria-label': `Añadir una unidad de ${product.name}`
  });
  plusButton.disabled = creating || line.quantity >= limit;
  plusButton.append(icon('plus'));

  const quantityValue = el(
    'span',
    {
      class: 'qty-value',
      'data-focus-key': `qty-value-${product.id}`,
      tabindex: '-1',
      'aria-label': `Cantidad de ${product.name}: ${line.quantity}`
    },
    String(line.quantity)
  );

  const controls = el(
    'div',
    { class: 'qty-control', role: 'group', 'aria-label': `Cantidad de ${product.name}` },
    minusButton,
    quantityValue,
    plusButton
  );

  const note = stockNote(product, line.quantity, limit);

  const info = el(
    'div',
    { class: 'cart-item-info' },
    el(
      'div',
      { class: 'cart-item-head' },
      el('h3', { class: 'cart-item-name' }, product.name),
      removeButton
    ),
    el('p', { class: 'cart-item-meta' }, `${formatMoney(product.price_cents)} c/u`),
    el(
      'div',
      { class: 'cart-item-controls' },
      controls,
      el('p', { class: 'cart-line-total' }, formatMoney(product.price_cents * line.quantity))
    ),
    el('p', { class: `cart-item-note ${note.tone}` }, note.text)
  );

  return el('li', { class: 'cart-item' }, media, info);
}

function stockNote(
  product: Product,
  quantity: number,
  limit: number
): { text: string; tone: string } {
  if (product.stock <= 0) {
    return { text: 'Agotado. Quita este producto para continuar.', tone: 'is-out' };
  }
  if (quantity >= limit) {
    return { text: `Máximo permitido: ${limit} ${limit === 1 ? 'unidad' : 'unidades'}.`, tone: 'is-low' };
  }
  return {
    text: `${product.stock} disponibles · el stock se descuenta al confirmar.`,
    tone: 'is-available'
  };
}

export function receiptPanelNodes(
  order: Order | null,
  pollState: PollState,
  pollMessage: string
): Node[] {
  if (!order) {
    const wrapper = el('div', { class: 'panel-message' });
    wrapper.append(
      el('span', { class: 'panel-message-icon' }, icon('copy')),
      el('h3', {}, 'Sin recibo'),
      el('p', {}, 'Consulta un pedido por su ID para ver el estado y los productos.'),
      actionButton('open-track', 'Consultar un pedido', 'search', 'button button-primary')
    );
    return [wrapper];
  }

  const banner = el(
    'div',
    { class: 'receipt-banner' },
    el('span', { class: 'receipt-check', 'aria-hidden': 'true' }, icon('check')),
    el(
      'div',
      {},
      el('h3', {}, 'Pedido confirmado'),
      el('p', {}, `Registrado el ${formatDateTime(order.created_at)}`)
    )
  );

  const idInput = el('input', {
    id: 'receipt-id',
    class: 'receipt-id-input',
    type: 'text',
    readonly: true,
    'data-order-id': '',
    'aria-describedby': 'receipt-id-hint'
  });
  idInput.value = order.id;
  const copyButton = el('button', {
    type: 'button',
    class: 'button button-secondary copy-button',
    'data-action': 'copy-id'
  });
  copyButton.append(icon('copy'), el('span', { 'data-copy-label': '' }, 'Copiar ID'));

  const idBlock = el(
    'div',
    { class: 'receipt-id-block' },
    el('label', { for: 'receipt-id', class: 'field-label' }, 'ID del pedido'),
    el('div', { class: 'receipt-id-row' }, idInput, copyButton),
    el('p', {
      class: 'field-hint',
      id: 'receipt-id-hint',
      'data-copy-hint': '',
      role: 'status',
      hidden: true
    })
  );

  const notification = notificationNode(order, pollState, pollMessage);

  const items = el('ul', { class: 'receipt-items' });
  for (const line of order.items) {
    items.append(
      el(
        'li',
        { class: 'receipt-item' },
        el(
          'div',
          { class: 'receipt-item-main' },
          el('span', { class: 'receipt-item-name' }, line.name),
          el(
            'span',
            { class: 'receipt-item-meta' },
            `${line.quantity} × ${formatMoney(line.unit_price_cents)}`
          )
        ),
        el('span', { class: 'receipt-line-total' }, formatMoney(line.unit_price_cents * line.quantity))
      )
    );
  }

  const total = el(
    'div',
    { class: 'receipt-total' },
    el('span', {}, 'Total'),
    el('strong', {}, formatMoney(order.total_cents))
  );

  const actions = el(
    'div',
    { class: 'receipt-actions' },
    actionButton('open-track', 'Consultar otro pedido', 'search'),
    actionButton('browse', 'Seguir comprando', 'arrow', 'button button-primary')
  );

  return [
    banner,
    idBlock,
    notification,
    el('h3', { class: 'section-label' }, 'Productos'),
    items,
    total,
    el(
      'p',
      { class: 'receipt-note' },
      'Pago simulado: no se realizó ningún cobro. El pedido ya está confirmado en el servidor; la notificación simulada es independiente.'
    ),
    actions
  ];
}

export function notificationNode(
  order: Order,
  pollState: PollState,
  pollMessage: string
): HTMLElement {
  const info = notificationInfo(order.notification_status);
  const wrapper = el('div', {
    class: `notice notice-${info.tone}`,
    role: 'status',
    'aria-live': 'polite',
    'data-receipt-status': ''
  });
  const head = el(
    'div',
    { class: 'notice-head' },
    el('span', { class: `status-dot status-dot-${info.tone}`, 'aria-hidden': 'true' }),
    el('p', { class: 'notice-title' }, info.label)
  );
  wrapper.append(head, el('p', { class: 'notice-text' }, info.detail));

  if (order.notification_status === 'pending') {
    if (pollState === 'polling') {
      wrapper.append(
        el(
          'p',
          { class: 'notice-meta' },
          el('span', { class: 'spinner', 'aria-hidden': 'true' }),
          'Consultando el estado…'
        )
      );
    } else if (pollState === 'timeout' || pollState === 'error' || pollState === 'idle') {
      wrapper.append(
        el(
          'p',
          { class: 'notice-meta' },
          pollMessage ||
            'La notificación sigue pendiente. Puedes consultar el pedido de nuevo con su ID.'
        )
      );
      wrapper.append(actionButton('poll-again', 'Consultar de nuevo', 'refresh'));
    }
  }

  return wrapper;
}

function notificationInfo(status: NotificationStatus): {
  label: string;
  detail: string;
  tone: NotificationStatus;
} {
  if (status === 'sent') {
    return {
      label: 'Enviada',
      detail: 'La notificación simulada se envió correctamente.',
      tone: 'sent'
    };
  }
  if (status === 'failed') {
    return {
      label: 'No se pudo enviar',
      detail: 'La notificación simulada falló. El pedido sigue confirmado.',
      tone: 'failed'
    };
  }
  return {
    label: 'Pendiente',
    detail: 'La notificación simulada todavía se está procesando.',
    tone: 'pending'
  };
}

export function trackPanelNodes(
  value: string,
  error: string,
  busy: boolean
): Node[] {
  const input = el('input', {
    id: 'order-lookup',
    class: 'field-input',
    type: 'text',
    name: 'order_id',
    autocomplete: 'off',
    autocapitalize: 'off',
    spellcheck: 'false',
    maxlength: '120',
    placeholder: '00000000-0000-0000-0000-000000000000',
    'aria-describedby': 'order-lookup-hint order-lookup-error'
  });
  input.value = value;

  const submitButton = el('button', {
    type: 'submit',
    class: 'button button-primary button-full',
    'data-track-submit': ''
  });
  submitButton.disabled = busy;
  submitButton.append(
    icon('search'),
    el('span', { 'data-track-submit-label': '' }, busy ? 'Consultando…' : 'Consultar pedido')
  );

  const form = el(
    'form',
    { class: 'track-form', 'data-lookup-form': '', novalidate: true },
    el('label', { for: 'order-lookup', class: 'field-label' }, 'ID del pedido'),
    input,
    el(
      'p',
      { class: 'field-hint', id: 'order-lookup-hint' },
      'Introduce el ID que aparece en el recibo del pedido.'
    ),
    el('p', {
      class: 'field-error',
      id: 'order-lookup-error',
      role: 'alert',
      tabindex: '-1',
      'data-track-error': '',
      hidden: error.length === 0
    }),
    submitButton
  );
  const errorBox = form.querySelector<HTMLElement>('[data-track-error]');
  if (errorBox) {
    errorBox.textContent = error;
  }
  if (busy) {
    form.setAttribute('aria-busy', 'true');
  }

  return [
    el('h3', { class: 'section-label' }, 'Consultar un pedido'),
    el('p', { class: 'panel-intro' }, 'El seguimiento consulta el estado real guardado en el servidor.'),
    form
  ];
}
