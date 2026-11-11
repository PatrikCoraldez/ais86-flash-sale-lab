type AttrValue = string | number | boolean | null | undefined;
type Child = Node | string | null | undefined;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, AttrValue> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) {
      continue;
    }
    node.setAttribute(name, value === true ? '' : String(value));
  }
  appendChildren(node, children);
  return node;
}

export function appendChildren(parent: Node, children: readonly Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined) {
      continue;
    }
    parent.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
}

export function setText(node: Node, text: string): void {
  node.textContent = text;
}

const iconPaths = {
  cart: 'M2.5 4H5l2.3 10.7a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.6L20.5 7H6.2M9 19h.01M18 19h.01',
  search: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM15.5 15.5 20 20',
  close: 'M6 6l12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  trash: 'M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13M10 11v6M14 11v6',
  check: 'M5 12.5 10 17.5 19 7',
  copy: 'M9 9h10v10H9zM5 15V5h10',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  refresh: 'M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5',
  alert: 'M12 3 2 21h20L12 3Zm0 6v6m0 3h.01'
} as const;

export type IconName = keyof typeof iconPaths;

export function icon(name: IconName): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.classList.add('icon');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', iconPaths[name]);
  svg.appendChild(path);
  return svg;
}

export function pulse(node: Element, className = 'is-pulsing'): void {
  node.classList.remove(className);
  void (node as HTMLElement).offsetWidth;
  node.classList.add(className);
  window.setTimeout(() => node.classList.remove(className), 420);
}
