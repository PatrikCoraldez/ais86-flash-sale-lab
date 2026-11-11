import { el, icon } from './dom';

export interface Elements {
  campaign: HTMLElement;
  heroImage: HTMLElement;
  heroName: HTMLElement;
  heroPrice: HTMLElement;
  heroOldPrice: HTMLElement;
  heroStock: HTMLElement;
  heroAdd: HTMLButtonElement;
  search: HTMLInputElement;
  searchClear: HTMLButtonElement;
  chips: HTMLElement;
  catalogStatus: HTMLElement;
  catalogMeta: HTMLElement;
  grid: HTMLElement;
  cartButton: HTMLButtonElement;
  cartCount: HTMLElement;
  trackButton: HTMLButtonElement;
  panel: HTMLDialogElement;
  panelTitle: HTMLElement;
  panelClose: HTMLButtonElement;
  panelBody: HTMLElement;
  toast: HTMLElement;
}

export function buildShell(): Elements {
  const app = document.getElementById('app');
  if (!app) {
    throw new Error('Falta el nodo de la aplicación.');
  }

  const demoBar = el(
    'div',
    { class: 'demo-bar' },
    el(
      'div',
      { class: 'shell demo-bar-inner' },
      el('span', { class: 'demo-dot', 'aria-hidden': 'true' }),
      el(
        'p',
        { class: 'demo-copy' },
        el('strong', {}, 'Demostración · sin cobros reales'),
        el('span', {}, 'Precios y stock ficticios')
      )
    )
  );

  const cartButton = el('button', {
    type: 'button',
    class: 'cart-button',
    'aria-label': 'Abrir carrito, 0 unidades',
    'aria-haspopup': 'dialog'
  });
  const cartCount = el('span', { class: 'cart-count', 'aria-hidden': 'true' }, '0');
  cartButton.append(icon('cart'), el('span', { class: 'cart-label' }, 'Carrito'), cartCount);

  const trackButton = el(
    'button',
    { type: 'button', class: 'nav-link', 'aria-haspopup': 'dialog' },
    'Seguimiento'
  );

  const header = el(
    'header',
    { class: 'site-header' },
    el(
      'div',
      { class: 'shell header-inner' },
      el(
        'a',
        { class: 'brand', href: '#inicio', 'aria-label': 'FLASH, ir al inicio' },
        el('span', { class: 'brand-name' }, 'FLASH'),
        el('span', { class: 'brand-slash', 'aria-hidden': 'true' }, '/09')
      ),
      el(
        'nav',
        { class: 'primary-nav', 'aria-label': 'Principal' },
        el('a', { class: 'nav-link', href: '#catalogo' }, 'Tienda'),
        trackButton,
        cartButton
      )
    )
  );

  const campaign = el('span', { class: 'campaign' });
  campaign.append(el('span', { class: 'skeleton-line skeleton-line-sm', 'aria-hidden': 'true' }));

  const heroCopy = el(
    'div',
    { class: 'hero-copy' },
    el(
      'h1',
      { class: 'hero-title', id: 'hero-title' },
      'Sonido claro.',
      el('br'),
      'Tu próximo drop.'
    ),
    el(
      'p',
      { class: 'hero-text' },
      'Audio y accesorios para tu escritorio. Explora el catálogo y prueba una compra sin cobros reales.'
    ),
    el(
      'div',
      { class: 'hero-actions' },
      el(
        'a',
        { class: 'button button-primary', href: '#catalogo' },
        el('span', {}, 'Explorar el drop'),
        icon('arrow')
      ),
      campaign
    )
  );

  const heroImage = el('div', { class: 'hero-image is-skeleton', 'aria-hidden': 'true' });
  const heroName = el(
    'p',
    { class: 'hero-product' },
    el('span', { class: 'skeleton-line skeleton-line-md', 'aria-hidden': 'true' })
  );
  const heroPrice = el(
    'p',
    { class: 'hero-price' },
    el('span', { class: 'skeleton-line skeleton-line-sm', 'aria-hidden': 'true' })
  );
  const heroOldPrice = el('s', { class: 'hero-old-price', hidden: true });
  const heroStock = el('span', { class: 'chip chip-stock', hidden: true });
  const heroAdd = el('button', {
    type: 'button',
    class: 'button button-secondary',
    disabled: true,
    'aria-label': 'Añadir el producto destacado al carrito'
  });
  heroAdd.dataset.labelDefault = 'Añadir al carrito';
  heroAdd.append(icon('plus'), el('span', { 'data-button-label': '' }, 'Añadir al carrito'));

  const heroFigure = el(
    'figure',
    { class: 'hero-figure' },
    heroImage,
    el(
      'figcaption',
      { class: 'hero-caption' },
      el(
        'div',
        { class: 'hero-caption-copy' },
        heroName,
        el('div', { class: 'hero-price-row' }, heroPrice, heroOldPrice, heroStock)
      ),
      heroAdd
    )
  );

  const hero = el(
    'section',
    { class: 'hero shell', id: 'inicio', 'aria-labelledby': 'hero-title' },
    heroCopy,
    heroFigure
  );

  const search = el('input', {
    id: 'search',
    type: 'search',
    placeholder: 'Buscar por nombre o categoría',
    autocomplete: 'off',
    spellcheck: 'false',
    disabled: true
  });
  const searchClear = el('button', {
    type: 'button',
    class: 'icon-button search-clear',
    'aria-label': 'Limpiar búsqueda',
    hidden: true
  });
  searchClear.append(icon('close'));

  const filters = el(
    'div',
    { class: 'catalog-filters' },
    el('label', { class: 'visually-hidden', for: 'search' }, 'Buscar en el catálogo'),
    el('div', { class: 'search-field' }, icon('search'), search, searchClear),
    el('div', {
      class: 'category-chips',
      role: 'group',
      'aria-label': 'Filtrar por categoría',
      id: 'category-chips'
    })
  );

  const catalogMeta = el(
    'p',
    { class: 'catalog-meta', id: 'catalog-meta', 'aria-live': 'polite' },
    'Cargando catálogo…'
  );
  const catalogStatus = el('div', { class: 'catalog-status' });
  const grid = el('div', {
    class: 'product-grid',
    id: 'product-grid',
    'aria-busy': 'true'
  });

  const catalogSection = el(
    'section',
    { class: 'catalog shell', id: 'catalogo', 'aria-labelledby': 'catalog-title' },
    el(
      'div',
      { class: 'section-head' },
      el('h2', { class: 'section-title', id: 'catalog-title', tabindex: '-1' }, 'El drop'),
      catalogMeta
    ),
    filters,
    catalogStatus,
    grid
  );

  const footer = el(
    'footer',
    { class: 'site-footer' },
    el(
      'div',
      { class: 'shell footer-inner' },
      el('p', {}, 'FLASH · Tienda de demostración'),
      el('p', {}, 'Precios y stock ficticios. Ningún pago se procesa.')
    )
  );

  const panelTitle = el(
    'h2',
    { class: 'panel-title', id: 'panel-title', tabindex: '-1' },
    'Carrito'
  );
  const panelClose = el('button', {
    type: 'button',
    class: 'icon-button',
    'aria-label': 'Cerrar carrito'
  });
  panelClose.append(icon('close'));
  const panelBody = el('div', { class: 'panel-body', id: 'panel-body' });
  const panel = el(
    'dialog',
    { class: 'panel', id: 'panel', 'aria-labelledby': 'panel-title' },
    el(
      'div',
      { class: 'panel-shell' },
      el('div', { class: 'panel-head' }, panelTitle, panelClose),
      panelBody
    )
  );

  const toast = el('div', {
    class: 'toast',
    role: 'status',
    'aria-live': 'polite',
    hidden: true
  });

  const main = el('main', {}, hero, catalogSection);
  app.replaceChildren(demoBar, header, main, footer, panel, toast);

  return {
    campaign,
    heroImage,
    heroName,
    heroPrice,
    heroOldPrice,
    heroStock,
    heroAdd,
    search,
    searchClear,
    chips: filters.querySelector<HTMLElement>('#category-chips') as HTMLElement,
    catalogStatus,
    catalogMeta,
    grid,
    cartButton,
    cartCount,
    trackButton,
    panel,
    panelTitle,
    panelClose,
    panelBody,
    toast
  };
}

export function productImage(productImageUrl: string, className: string, lazy: boolean): HTMLImageElement {
  const image = document.createElement('img');
  image.src = productImageUrl;
  image.alt = '';
  image.width = 640;
  image.height = 480;
  image.decoding = 'async';
  image.className = className;
  image.loading = lazy ? 'lazy' : 'eager';
  return image;
}
