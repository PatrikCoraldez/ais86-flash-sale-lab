import '@fontsource-variable/manrope';
import './styles.css';
import { ApiError, createOrder, fetchCatalog, fetchOrder, friendlyError, isAbortError } from './api';
import {
  MAX_DISTINCT_PRODUCTS,
  addLine,
  cartCount,
  findLine,
  maxAddable,
  removeLine,
  sanitizeLines,
  setLineQuantity,
  toOrderItems,
  validateCart
} from './cart';
import { el, icon, pulse } from './dom';
import { formatMoney, normalizeText } from './format';
import { buildShell, productImage } from './shell';
import type { Elements } from './shell';
import {
  clearAttempt,
  newIdempotencyKey,
  readAttempt,
  readStoredCart,
  saveAttempt,
  writeStoredCart
} from './storage';
import type { AttemptRecord } from './storage';
import type { CartLine, Catalog, Order, Product } from './types';
import {
  applyStockChip,
  cartPanelNodes,
  configureAddButton,
  emptyCatalogNode,
  notificationNode,
  receiptPanelNodes,
  renderProductCard,
  skeletonCards,
  syncProductCard,
  trackPanelNodes
} from './view';
import type { CatalogState, PollState } from './view';

type PanelMode = 'cart' | 'receipt' | 'track';
type ToastTone = 'info' | 'warn';

const pollIntervalMs = 2000;
const pollWarmupMs = 1200;
const maxPollAttempts = 15;

let catalog: Catalog | null = null;
let catalogState: CatalogState = 'loading';
let catalogMessage = '';
let catalogRequestToken = 0;
let cart: CartLine[] = readStoredCart();
let activeCategory = 'all';
let searchQuery = '';
let featuredProduct: Product | null = null;
let panelMode: PanelMode = 'cart';
let activeOrder: Order | null = null;
let orderError = '';
let orderErrorCode = '';
let creating = false;
let trackingBusy = false;
let trackingError = '';
let trackingValue = '';
let trackingAbort: AbortController | null = null;
let pollState: PollState = 'idle';
let pollMessage = '';
let pollAbort: AbortController | null = null;
let pollTimer: number | null = null;
let pollToken = 0;
let pollAttempts = 0;
let lastFocused: HTMLElement | null = null;
let toastTimer: number | null = null;

const ui: Elements = buildShell();

function start(): void {
  ui.search.addEventListener('input', onSearchInput);
  ui.searchClear.addEventListener('click', () => clearFilters(false));
  ui.chips.addEventListener('click', onCategoryClick);
  ui.grid.addEventListener('click', onGridClick);
  ui.heroAdd.addEventListener('click', () => {
    if (featuredProduct) {
      addProduct(featuredProduct.id);
    }
  });
  ui.cartButton.addEventListener('click', () => openPanel('cart'));
  ui.trackButton.addEventListener('click', () => openPanel('track'));
  ui.panelClose.addEventListener('click', () => ui.panel.close());
  ui.panel.addEventListener('cancel', onPanelCancel);
  ui.panel.addEventListener('close', onPanelClose);
  ui.panel.addEventListener('click', onPanelClick);
  ui.panelBody.addEventListener('click', onPanelBodyClick);
  ui.panelBody.addEventListener('submit', onPanelSubmit);
  ui.panelBody.addEventListener('input', onPanelInput);

  updateCartCount(false);
  renderCatalogSkeletons();
  void loadCatalog();
}

async function loadCatalog(options: { silent?: boolean } = {}): Promise<void> {
  const silent = options.silent === true;
  const token = ++catalogRequestToken;

  if (!silent) {
    catalogState = 'loading';
    catalogMessage = '';
    if (!catalog) {
      renderCatalogSkeletons();
    } else {
      ui.grid.setAttribute('aria-busy', 'true');
    }
    if (ui.panel.open && panelMode === 'cart') {
      renderPanelBody(false);
    }
  }

  try {
    const data = await fetchCatalog();
    if (token !== catalogRequestToken) {
      return;
    }
    const previousSignature = cartSignature(cart);
    catalog = data;
    catalogState = 'ready';
    catalogMessage = '';
    cart = sanitizeLines(cart, data.items);
    writeStoredCart(cart);
    const changed = previousSignature !== cartSignature(cart);
    renderCatalog();
    renderCampaign();
    renderHero();
    updateCartCount(false);
    if (changed) {
      showToast('Ajustamos el carrito al stock disponible.', 'warn');
    }
    if (ui.panel.open && panelMode === 'cart') {
      renderPanelBody(false);
    }
  } catch (error) {
    if (token !== catalogRequestToken) {
      return;
    }
    if (silent && catalog) {
      showToast('No pudimos actualizar el stock.', 'warn');
      return;
    }
    catalogState = 'error';
    catalogMessage = friendlyError(error, 'catalog').message;
    renderCatalogError();
    renderCampaign();
    renderHeroUnavailable();
    if (ui.panel.open && panelMode === 'cart') {
      renderPanelBody(false);
    }
  }
}

function cartSignature(lines: readonly CartLine[]): string {
  return lines.map((line) => `${line.productId}:${line.quantity}`).join('|');
}

function renderCatalogSkeletons(): void {
  ui.search.disabled = true;
  ui.searchClear.hidden = true;
  ui.chips.replaceChildren();
  ui.catalogStatus.replaceChildren();
  ui.catalogMeta.textContent = 'Cargando catálogo…';
  ui.grid.setAttribute('aria-busy', 'true');
  ui.grid.replaceChildren(...skeletonCards());
}

function renderCatalog(): void {
  if (!catalog) {
    return;
  }
  ui.search.disabled = false;
  ui.searchClear.hidden = searchQuery.length === 0;
  ui.catalogStatus.replaceChildren();
  ui.grid.setAttribute('aria-busy', 'false');
  renderCategories();
  renderGrid();
  syncCardStates();
}

function renderCategories(): void {
  if (!catalog) {
    return;
  }
  const categories = Array.from(new Set(catalog.items.map((product) => product.category))).sort(
    (left, right) => left.localeCompare(right, 'es')
  );
  if (activeCategory !== 'all' && !categories.includes(activeCategory)) {
    activeCategory = 'all';
  }
  const buttons: HTMLButtonElement[] = [categoryButton('all', 'Todos')];
  for (const category of categories) {
    buttons.push(categoryButton(category, category));
  }
  ui.chips.replaceChildren(...buttons);
}

function categoryButton(value: string, label: string): HTMLButtonElement {
  const active = activeCategory === value;
  const button = el(
    'button',
    {
      type: 'button',
      class: 'chip chip-filter',
      'data-category': value,
      'aria-pressed': active ? 'true' : 'false',
      'aria-controls': 'product-grid'
    },
    label
  );
  button.classList.toggle('is-active', active);
  return button;
}

function renderGrid(): void {
  if (!catalog || catalogState !== 'ready') {
    return;
  }
  const term = normalizeText(searchQuery);
  const filtered = catalog.items.filter((product) => {
    const inCategory = activeCategory === 'all' || product.category === activeCategory;
    if (!inCategory) {
      return false;
    }
    if (term.length === 0) {
      return true;
    }
    return normalizeText(`${product.name} ${product.description} ${product.category}`).includes(term);
  });

  ui.grid.replaceChildren();
  if (filtered.length === 0) {
    const noFilters = term.length === 0 && activeCategory === 'all';
    ui.grid.append(emptyCatalogNode(noFilters ? 'catalog' : 'search', searchQuery, activeCategory));
    ui.catalogMeta.textContent =
      catalog.items.length === 0 ? 'Sin productos' : 'Sin resultados';
    return;
  }

  for (const product of filtered) {
    const quantity = findLine(cart, product.id)?.quantity ?? 0;
    ui.grid.append(renderProductCard(product, quantity, creating));
  }
  const total = catalog.items.length;
  ui.catalogMeta.textContent =
    filtered.length === total
      ? `${total} ${total === 1 ? 'producto' : 'productos'}`
      : `${filtered.length} de ${total} productos`;
}

function syncCardStates(): void {
  if (!catalog) {
    return;
  }
  for (const card of Array.from(ui.grid.querySelectorAll<HTMLElement>('.card[data-product]'))) {
    const productId = card.dataset.product;
    if (!productId) {
      continue;
    }
    const product = findProduct(productId);
    if (!product) {
      continue;
    }
    const quantity = findLine(cart, productId)?.quantity ?? 0;
    syncProductCard(card, product, quantity, creating);
  }
  if (featuredProduct) {
    applyStockChip(ui.heroStock, featuredProduct);
    configureAddButton(
      ui.heroAdd,
      featuredProduct,
      findLine(cart, featuredProduct.id)?.quantity ?? 0,
      creating
    );
  }
}

function renderHero(): void {
  if (!catalog || catalog.items.length === 0) {
    renderHeroUnavailable();
    return;
  }
  const product =
    catalog.items.find((item) => item.id === 'nova-headphones') ?? catalog.items[0] ?? null;
  if (!product) {
    renderHeroUnavailable();
    return;
  }
  featuredProduct = product;
  ui.heroImage.classList.remove('is-skeleton', 'is-unavailable');
  ui.heroImage.replaceChildren();
  const image = productImage(product.image, 'hero-product-image', false);
  image.setAttribute('fetchpriority', 'high');
  ui.heroImage.append(image);
  ui.heroName.textContent = product.name;
  ui.heroPrice.textContent = formatMoney(product.price_cents);
  if (product.original_price_cents > product.price_cents) {
    ui.heroOldPrice.textContent = formatMoney(product.original_price_cents);
    ui.heroOldPrice.hidden = false;
  } else {
    ui.heroOldPrice.textContent = '';
    ui.heroOldPrice.hidden = true;
  }
  ui.heroStock.hidden = false;
  applyStockChip(ui.heroStock, product);
  configureAddButton(
    ui.heroAdd,
    product,
    findLine(cart, product.id)?.quantity ?? 0,
    creating
  );
}

function renderHeroUnavailable(): void {
  featuredProduct = null;
  ui.heroImage.classList.remove('is-skeleton');
  ui.heroImage.classList.add('is-unavailable');
  ui.heroImage.replaceChildren(el('p', { class: 'hero-unavailable' }, 'Catálogo no disponible'));
  ui.heroName.textContent = 'Catálogo no disponible';
  ui.heroPrice.textContent = '—';
  ui.heroOldPrice.textContent = '';
  ui.heroOldPrice.hidden = true;
  ui.heroStock.hidden = true;
  ui.heroStock.textContent = '';
  ui.heroStock.classList.remove('is-available', 'is-low', 'is-out');
  ui.heroAdd.disabled = true;
  const label = ui.heroAdd.querySelector<HTMLElement>('[data-button-label]');
  if (label) {
    label.textContent = 'No disponible';
  }
  ui.heroAdd.setAttribute('aria-label', 'Añadir no disponible: catálogo sin cargar');
}

function renderCampaign(): void {
  ui.campaign.classList.remove('is-ended', 'is-muted');
  ui.campaign.textContent = 'Campaña de práctica · stock limitado';
}

function renderCatalogError(): void {
  ui.search.disabled = true;
  ui.searchClear.hidden = true;
  ui.chips.replaceChildren();
  ui.grid.replaceChildren();
  ui.grid.setAttribute('aria-busy', 'false');
  ui.catalogMeta.textContent = 'Catálogo no disponible';
  const retry = el('button', { type: 'button', class: 'button button-secondary' });
  retry.append(icon('refresh'), el('span', {}, 'Reintentar'));
  retry.addEventListener('click', () => {
    void loadCatalog();
  });
  const alert = el(
    'div',
    { class: 'alert alert-error catalog-alert', role: 'alert' },
    icon('alert'),
    el(
      'div',
      { class: 'alert-body' },
      el('h3', {}, 'No pudimos cargar el catálogo'),
      el('p', {}, catalogMessage),
      retry
    )
  );
  ui.catalogStatus.replaceChildren(alert);
}

function findProduct(productId: string): Product | null {
  return catalog?.items.find((product) => product.id === productId) ?? null;
}

function findCard(productId: string): HTMLElement | null {
  return (
    Array.from(ui.grid.querySelectorAll<HTMLElement>('.card')).find(
      (card) => card.dataset.product === productId
    ) ?? null
  );
}

function onSearchInput(): void {
  searchQuery = ui.search.value;
  ui.searchClear.hidden = searchQuery.length === 0;
  if (catalogState === 'ready') {
    renderGrid();
  }
}

function clearFilters(resetCategory: boolean): void {
  searchQuery = '';
  ui.search.value = '';
  ui.searchClear.hidden = true;
  if (resetCategory) {
    activeCategory = 'all';
  }
  syncCategoryChips();
  renderGrid();
  ui.search.focus();
}

function onCategoryClick(event: MouseEvent): void {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest<HTMLButtonElement>('button[data-category]');
  if (!button || !ui.chips.contains(button)) {
    return;
  }
  const value = button.dataset.category;
  if (!value || value === activeCategory) {
    return;
  }
  activeCategory = value;
  syncCategoryChips();
  renderGrid();
}

function syncCategoryChips(): void {
  for (const button of Array.from(
    ui.chips.querySelectorAll<HTMLButtonElement>('button[data-category]')
  )) {
    const active = button.dataset.category === activeCategory;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  }
}

function onGridClick(event: MouseEvent): void {
  if (!(event.target instanceof Element)) {
    return;
  }
  const actionButton = event.target.closest<HTMLElement>('[data-action]');
  if (actionButton && ui.grid.contains(actionButton)) {
    const action = actionButton.dataset.action;
    if (action === 'clear-filters') {
      clearFilters(true);
      return;
    }
    if (action === 'reload-catalog') {
      void loadCatalog();
      return;
    }
  }
  const addButton = event.target.closest<HTMLButtonElement>('button[data-add]');
  if (addButton && ui.grid.contains(addButton) && addButton.dataset.add) {
    addProduct(addButton.dataset.add);
  }
}

function addProduct(productId: string): void {
  if (catalogState !== 'ready' || !catalog) {
    showToast('El catálogo aún no está disponible.', 'warn');
    return;
  }
  if (creating) {
    showToast('Espera a que termine la confirmación del pedido.', 'warn');
    return;
  }
  const product = findProduct(productId);
  if (!product) {
    showToast('Ese producto ya no está disponible.', 'warn');
    return;
  }
  const result = addLine(cart, product);
  if (result.result === 'out') {
    showToast(`${product.name} está agotado.`, 'warn');
    return;
  }
  if (result.result === 'max') {
    showToast(`Ya tienes el máximo disponible de ${product.name}.`, 'warn');
    const card = findCard(product.id);
    const inCartChip = card?.querySelector<HTMLElement>('[data-role="incart"]');
    if (inCartChip) {
      pulse(inCartChip);
    }
    return;
  }
  if (result.result === 'limit') {
    showToast(`Máximo ${MAX_DISTINCT_PRODUCTS} productos distintos por pedido.`, 'warn');
    return;
  }

  cart = result.lines;
  clearOrderError();
  writeStoredCart(cart);
  updateCartCount(true);
  syncCardStates();
  const quantity = findLine(cart, product.id)?.quantity ?? 1;
  const card = findCard(product.id);
  if (card) {
    const stockChip = card.querySelector<HTMLElement>('[data-role="stock"]');
    const inCartChip = card.querySelector<HTMLElement>('[data-role="incart"]');
    if (stockChip) {
      pulse(stockChip);
    }
    if (inCartChip) {
      pulse(inCartChip);
    }
  }
  if (featuredProduct?.id === product.id) {
    pulse(ui.heroStock);
  }
  showToast(`Añadido: ${product.name} · ${quantity} en el carrito.`);
}

function clearOrderError(): void {
  orderError = '';
  orderErrorCode = '';
}

function updateCartCount(animate: boolean): void {
  const count = cartCount(cart);
  ui.cartCount.textContent = String(count);
  ui.cartButton.setAttribute(
    'aria-label',
    `Abrir carrito, ${count} ${count === 1 ? 'unidad' : 'unidades'}`
  );
  ui.cartButton.classList.toggle('has-items', count > 0);
  if (animate) {
    pulse(ui.cartCount, 'is-bumping');
  }
}

function showToast(message: string, tone: ToastTone = 'info'): void {
  ui.toast.dataset.tone = tone;
  ui.toast.textContent = message;
  ui.toast.hidden = false;
  if (toastTimer !== null) {
    window.clearTimeout(toastTimer);
  }
  toastTimer = window.setTimeout(() => {
    ui.toast.hidden = true;
    toastTimer = null;
  }, 3400);
}

function hideToast(): void {
  if (toastTimer !== null) {
    window.clearTimeout(toastTimer);
    toastTimer = null;
  }
  ui.toast.hidden = true;
}

function openPanel(mode: PanelMode): void {
  if (ui.panel.open) {
    if (panelMode !== mode) {
      setPanelMode(mode);
    }
    return;
  }
  lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  if (mode === 'track') {
    abortTracking();
    trackingError = '';
    trackingBusy = false;
    trackingValue = '';
  }
  panelMode = mode;
  renderPanel(true);
  ui.panel.showModal();
  document.documentElement.classList.add('has-dialog');
  focusPanelStart(mode);
}

function setPanelMode(mode: PanelMode): void {
  if (panelMode === 'receipt' && mode !== 'receipt') {
    stopPolling();
  }
  if (panelMode === 'track' && mode !== 'track') {
    abortTracking();
  }
  if (mode === 'track') {
    trackingError = '';
    trackingBusy = false;
    trackingValue = '';
  }
  panelMode = mode;
  renderPanel(true);
  focusPanelStart(mode);
}

function focusPanelStart(mode: PanelMode): void {
  window.requestAnimationFrame(() => {
    if (mode === 'track') {
      const input = ui.panelBody.querySelector<HTMLInputElement>('#order-lookup');
      if (input) {
        input.focus();
        input.select();
        return;
      }
    }
    ui.panelClose.focus();
  });
}

function onPanelCancel(event: Event): void {
  if (creating) {
    event.preventDefault();
  }
}

function onPanelClose(): void {
  stopPolling();
  abortTracking();
  document.documentElement.classList.remove('has-dialog');
  const target = lastFocused;
  lastFocused = null;
  if (target?.isConnected) {
    target.focus();
  }
}

function onPanelClick(event: MouseEvent): void {
  if (event.target === ui.panel && !creating) {
    ui.panel.close();
  }
}

function onPanelInput(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLInputElement && target.id === 'order-lookup') {
    trackingValue = target.value;
    if (trackingError) {
      clearTrackError();
    }
  }
}

function onPanelSubmit(event: SubmitEvent): void {
  if (!(event.target instanceof HTMLFormElement) || !event.target.matches('[data-lookup-form]')) {
    return;
  }
  event.preventDefault();
  void lookupOrder();
}

function onPanelBodyClick(event: MouseEvent): void {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest<HTMLElement>('[data-action]');
  if (!button) {
    return;
  }
  const action = button.dataset.action;
  const productId = button.dataset.productId;
  const focusKey = button.dataset.focusKey;
  switch (action) {
    case 'qty-minus':
      if (productId) {
        updateCartQuantity(productId, -1, focusKey);
      }
      break;
    case 'qty-plus':
      if (productId) {
        updateCartQuantity(productId, 1, focusKey);
      }
      break;
    case 'remove':
      if (productId) {
        removeCartProduct(productId);
      }
      break;
    case 'confirm':
      void confirmOrder();
      break;
    case 'refresh-catalog':
      void loadCatalog({ silent: catalog !== null });
      break;
    case 'reload-catalog':
      void loadCatalog();
      break;
    case 'copy-id':
      if (activeOrder && button instanceof HTMLButtonElement) {
        void copyOrderId(activeOrder.id, button);
      }
      break;
    case 'poll-again':
      startPolling();
      break;
    case 'open-track':
      setPanelMode('track');
      break;
    case 'browse':
      ui.panel.close();
      window.setTimeout(() => {
        focusCatalog();
      }, 0);
      break;
  }
}

function focusCatalog(): void {
  const heading = document.getElementById('catalog-title');
  heading?.focus();
  heading?.scrollIntoView({ block: 'start' });
}

function renderPanel(resetScroll: boolean): void {
  const titles: Record<PanelMode, string> = {
    cart: 'Carrito',
    receipt: 'Pedido confirmado',
    track: 'Seguimiento'
  };
  const closeLabels: Record<PanelMode, string> = {
    cart: 'Cerrar carrito',
    receipt: 'Cerrar recibo',
    track: 'Cerrar seguimiento'
  };
  ui.panelTitle.textContent = titles[panelMode];
  ui.panelClose.setAttribute('aria-label', closeLabels[panelMode]);
  ui.panelClose.disabled = creating;
  if (creating) {
    ui.panel.setAttribute('aria-busy', 'true');
  } else {
    ui.panel.removeAttribute('aria-busy');
  }
  renderPanelBody(resetScroll);
}

function renderPanelBody(resetScroll: boolean): void {
  const scrollTop = resetScroll ? 0 : ui.panelBody.scrollTop;
  let nodes: Node[];
  if (panelMode === 'cart') {
    nodes = cartPanelNodes({
      catalog,
      catalogState,
      catalogMessage,
      cart,
      orderError,
      orderErrorCode,
      creating
    });
  } else if (panelMode === 'receipt') {
    nodes = receiptPanelNodes(activeOrder, pollState, pollMessage);
  } else {
    nodes = trackPanelNodes(trackingValue, trackingError, trackingBusy);
  }
  ui.panelBody.replaceChildren(...nodes);
  ui.panelBody.scrollTop = scrollTop;
}

function updateCartQuantity(productId: string, delta: number, focusKey: string | undefined): void {
  if (!catalog || creating) {
    return;
  }
  const product = findProduct(productId);
  const line = findLine(cart, productId);
  if (!product || !line) {
    return;
  }
  const next = line.quantity + delta;
  const limit = maxAddable(product);
  if (next < 1 || next > limit) {
    return;
  }
  cart = setLineQuantity(cart, product, next);
  clearOrderError();
  writeStoredCart(cart);
  updateCartCount(true);
  syncCardStates();
  renderPanelBody(false);
  focusByKey(focusKey);
}

function removeCartProduct(productId: string): void {
  if (!catalog || creating) {
    return;
  }
  cart = removeLine(cart, productId);
  clearOrderError();
  writeStoredCart(cart);
  updateCartCount(true);
  syncCardStates();
  renderPanelBody(false);
  const next =
    ui.panelBody.querySelector<HTMLElement>('[data-action="remove"]') ??
    ui.panelBody.querySelector<HTMLElement>('[data-action="browse"]');
  (next ?? ui.panelClose).focus();
}

function focusByKey(focusKey: string | undefined): void {
  if (focusKey) {
    const target = Array.from(
      ui.panelBody.querySelectorAll<HTMLElement>('[data-focus-key]')
    ).find((node) => node.dataset.focusKey === focusKey);
    if (target) {
      if (!(target instanceof HTMLButtonElement && target.disabled)) {
        target.focus();
        return;
      }
      const value = target
        .closest('.qty-control')
        ?.querySelector<HTMLElement>('.qty-value');
      if (value) {
        value.focus();
        return;
      }
    }
  }
  ui.panelClose.focus();
}

function ensureAttempt(items: Array<{ product_id: string; quantity: number }>): AttemptRecord {
  const signature = JSON.stringify(items);
  const stored = readAttempt();
  if (stored && stored.signature === signature) {
    return stored;
  }
  const record: AttemptRecord = { key: newIdempotencyKey(), signature };
  saveAttempt(record);
  return record;
}

async function confirmOrder(): Promise<void> {
  if (creating || !catalog) {
    return;
  }
  const validation = validateCart(cart, catalog.items);
  if (!validation.ok) {
    renderPanelBody(false);
    const warning = ui.panelBody.querySelector<HTMLElement>('.alert-warning, [data-order-error]');
    if (warning) {
      warning.setAttribute('tabindex', '-1');
      warning.focus();
    }
    return;
  }

  const items = toOrderItems(cart, catalog.items);
  if (items.length === 0) {
    return;
  }
  const attempt = ensureAttempt(items);
  hideToast();
  creating = true;
  orderError = '';
  orderErrorCode = '';
  renderPanel(false);
  syncCardStates();
  window.requestAnimationFrame(() => {
    if (creating) {
      ui.panelTitle.focus();
    }
  });

  try {
    const order = await createOrder(items, attempt.key);
    clearAttempt();
    creating = false;
    cart = [];
    writeStoredCart(cart);
    updateCartCount(true);
    syncCardStates();
    beginReceipt(order);
    void loadCatalog({ silent: true });
  } catch (error) {
    creating = false;
    const info = friendlyError(error, 'create');
    orderError = info.message;
    orderErrorCode = info.code;
    if (error instanceof ApiError) {
      if (error.code === 'IDEMPOTENCY_CONFLICT' || error.code === 'VALIDATION_ERROR') {
        clearAttempt();
      }
      if (error.code === 'OUT_OF_STOCK') {
        void loadCatalog({ silent: catalog !== null });
      }
    }
    renderPanel(false);
    syncCardStates();
    const alert = ui.panelBody.querySelector<HTMLElement>('[data-order-error]');
    alert?.focus();
  }
}

function beginReceipt(order: Order): void {
  abortTracking();
  stopPolling();
  activeOrder = order;
  panelMode = 'receipt';
  pollState = order.notification_status === 'pending' ? 'polling' : 'idle';
  pollMessage = '';
  renderPanel(true);
  focusPanelStart('receipt');
  if (order.notification_status === 'pending') {
    startPolling();
  }
}

function startPolling(): void {
  if (!activeOrder) {
    return;
  }
  const order = activeOrder;
  stopPolling();
  if (order.notification_status !== 'pending') {
    updateReceiptNotification();
    return;
  }

  pollState = 'polling';
  pollMessage = '';
  pollAttempts = 0;
  const token = ++pollToken;
  const controller = new AbortController();
  pollAbort = controller;
  updateReceiptNotification();

  const tick = async (): Promise<void> => {
    if (token !== pollToken) {
      return;
    }
    pollAttempts += 1;
    try {
      const next = await fetchOrder(order.id, controller.signal);
      if (token !== pollToken) {
        return;
      }
      activeOrder = next;
      if (next.notification_status !== 'pending') {
        pollState = 'idle';
        pollMessage = '';
        clearPolling();
        updateReceiptNotification();
        return;
      }
      if (pollAttempts >= maxPollAttempts) {
        pollState = 'timeout';
        pollMessage = 'La notificación sigue pendiente. Puedes consultar el pedido de nuevo con su ID.';
        clearPolling();
        updateReceiptNotification();
        return;
      }
      updateReceiptNotification();
      pollTimer = window.setTimeout(() => {
        void tick();
      }, pollIntervalMs);
    } catch (error) {
      if (isAbortError(error) || token !== pollToken) {
        return;
      }
      pollState = 'error';
      pollMessage = friendlyError(error, 'order').message;
      clearPolling();
      updateReceiptNotification();
    }
  };

  pollTimer = window.setTimeout(() => {
    void tick();
  }, pollWarmupMs);
}

function clearPolling(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (pollAbort) {
    pollAbort.abort();
    pollAbort = null;
  }
}

function stopPolling(): void {
  pollToken += 1;
  clearPolling();
  pollState = 'idle';
  pollMessage = '';
}

function updateReceiptNotification(): void {
  if (!ui.panel.open || panelMode !== 'receipt' || !activeOrder) {
    return;
  }
  const current = ui.panelBody.querySelector('[data-receipt-status]');
  if (current) {
    current.replaceWith(notificationNode(activeOrder, pollState, pollMessage));
  }
}

async function lookupOrder(): Promise<void> {
  if (trackingBusy) {
    return;
  }
  const input = ui.panelBody.querySelector<HTMLInputElement>('#order-lookup');
  const id = (input?.value ?? trackingValue).trim();
  trackingValue = id;
  if (id.length === 0) {
    showTrackError('Introduce el ID del pedido.');
    input?.focus();
    return;
  }
  if (id.length > 120) {
    showTrackError('El ID del pedido no es válido.');
    input?.focus();
    return;
  }

  trackingBusy = true;
  trackingError = '';
  setTrackBusyUi(true);
  const controller = new AbortController();
  trackingAbort = controller;

  try {
    const order = await fetchOrder(id, controller.signal);
    if (controller.signal.aborted) {
      return;
    }
    trackingAbort = null;
    trackingBusy = false;
    beginReceipt(order);
  } catch (error) {
    if (isAbortError(error) || controller.signal.aborted) {
      return;
    }
    trackingAbort = null;
    trackingBusy = false;
    setTrackBusyUi(false);
    showTrackError(friendlyError(error, 'order').message);
  }
}

function setTrackBusyUi(busy: boolean): void {
  const form = ui.panelBody.querySelector<HTMLFormElement>('[data-lookup-form]');
  const button = form?.querySelector<HTMLButtonElement>('[data-track-submit]');
  const label = form?.querySelector<HTMLElement>('[data-track-submit-label]');
  if (button) {
    button.disabled = busy;
  }
  if (label) {
    label.textContent = busy ? 'Consultando…' : 'Consultar pedido';
  }
  if (form) {
    if (busy) {
      form.setAttribute('aria-busy', 'true');
    } else {
      form.removeAttribute('aria-busy');
    }
  }
}

function showTrackError(message: string): void {
  trackingError = message;
  const box = ui.panelBody.querySelector<HTMLElement>('[data-track-error]');
  if (box) {
    box.textContent = message;
    box.hidden = false;
    box.focus();
  }
}

function clearTrackError(): void {
  trackingError = '';
  const box = ui.panelBody.querySelector<HTMLElement>('[data-track-error]');
  if (box) {
    box.textContent = '';
    box.hidden = true;
  }
}

function abortTracking(): void {
  if (trackingAbort) {
    trackingAbort.abort();
    trackingAbort = null;
  }
  trackingBusy = false;
}

async function copyOrderId(orderId: string, button: HTMLButtonElement): Promise<void> {
  const input = ui.panelBody.querySelector<HTMLInputElement>('[data-order-id]');
  const hint = ui.panelBody.querySelector<HTMLElement>('[data-copy-hint]');
  const label = button.querySelector<HTMLElement>('[data-copy-label]');
  try {
    await navigator.clipboard.writeText(orderId);
    if (label) {
      label.textContent = 'Copiado';
    }
    if (hint) {
      hint.hidden = true;
      hint.textContent = '';
    }
    window.setTimeout(() => {
      if (label?.isConnected) {
        label.textContent = 'Copiar ID';
      }
    }, 2200);
  } catch {
    if (hint) {
      hint.hidden = false;
      hint.textContent = 'Selecciona el ID y cópialo manualmente.';
    }
    if (label) {
      label.textContent = 'Copia manual';
    }
    input?.focus();
    input?.select();
    window.setTimeout(() => {
      if (label?.isConnected) {
        label.textContent = 'Copiar ID';
      }
    }, 2200);
  }
}

start();
