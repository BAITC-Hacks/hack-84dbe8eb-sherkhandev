(() => {
  'use strict';
  let token = null, currentAction = null, busy = false;
  const $ = id => document.getElementById(id);
  const dialog = $('dialog');

  function isSafeCertUrl(url) {
    if (typeof url !== 'string') return false;
    const trimmed = url.trim();
    if (trimmed.startsWith('/demo-certificates/')) return true;
    try {
      const parsed = new URL(trimmed);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch (_) {
      return false;
    }
  }

  function addBubble(text, kind = 'assistant') {
    const el = document.createElement('div');
    el.className = `bubble ${kind}`;
    el.textContent = text;
    dialog.appendChild(el);
    dialog.scrollTop = dialog.scrollHeight;
    return el;
  }

  function renderWarnings(warnings) {
    if (!Array.isArray(warnings) || warnings.length === 0) return;
    const box = document.createElement('div');
    box.className = 'warning-box';
    const title = document.createElement('strong');
    title.textContent = 'Предупреждения:';
    box.appendChild(title);
    const list = document.createElement('ul');
    for (const w of warnings) {
      const li = document.createElement('li');
      li.textContent = typeof w === 'string' ? w : JSON.stringify(w);
      list.appendChild(li);
    }
    box.appendChild(list);
    dialog.appendChild(box);
    dialog.scrollTop = dialog.scrollHeight;
  }

  function renderProducts(products) {
    if (!Array.isArray(products) || products.length === 0) return;
    const container = document.createElement('div');
    container.className = 'products-grid';
    for (const p of products) {
      const card = document.createElement('div');
      card.className = 'product-card';

      const header = document.createElement('div');
      header.className = 'product-header';

      const title = document.createElement('h3');
      title.className = 'product-title';
      title.textContent = p.name || 'Без названия';
      header.appendChild(title);

      const badge = document.createElement('span');
      badge.className = `badge badge-${p.source_kind === 'synthetic' ? 'synthetic' : 'ekt'}`;
      badge.textContent = p.source_kind === 'synthetic' ? 'демонстрационные данные (synthetic)' : 'данные EKT';
      header.appendChild(badge);
      card.appendChild(header);

      const meta = document.createElement('div');
      meta.className = 'product-meta';

      const article = document.createElement('span');
      article.className = 'product-article';
      article.textContent = `Артикул: ${p.article || '—'}`;
      meta.appendChild(article);

      const price = document.createElement('span');
      price.className = 'product-price';
      const priceText = (p.price != null && p.price !== '') ? `${p.price} KZT` : 'неизвестно';
      price.textContent = `Цена: ${priceText}`;
      meta.appendChild(price);
      card.appendChild(meta);

      if (p.specs && typeof p.specs === 'object' && Object.keys(p.specs).length > 0) {
        const specsList = document.createElement('ul');
        specsList.className = 'product-specs';
        for (const [key, value] of Object.entries(p.specs)) {
          const li = document.createElement('li');
          li.textContent = `${key}: ${value}`;
          specsList.appendChild(li);
        }
        card.appendChild(specsList);
      }

      if (Array.isArray(p.certificate_urls) && p.certificate_urls.length > 0) {
        const certsBlock = document.createElement('div');
        certsBlock.className = 'product-certs';
        const certsTitle = document.createElement('strong');
        certsTitle.textContent = 'Сертификаты: ';
        certsBlock.appendChild(certsTitle);

        let added = 0;
        for (const url of p.certificate_urls) {
          if (isSafeCertUrl(url)) {
            if (added > 0) {
              certsBlock.appendChild(document.createTextNode(', '));
            }
            const link = document.createElement('a');
            link.href = url.trim();
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            const label = url.split('/').pop() || 'Сертификат';
            link.textContent = label;
            certsBlock.appendChild(link);
            added++;
          }
        }
        if (added > 0) {
          card.appendChild(certsBlock);
        }
      }

      container.appendChild(card);
    }
    dialog.appendChild(container);
    dialog.scrollTop = dialog.scrollHeight;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body) headers.set('Content-Type', 'application/json');
    const r = await fetch(path, { ...options, headers });
    const data = await r.json().catch(() => ({ error: { message: 'Некорректный ответ сервера' } }));
    if (!r.ok) throw Object.assign(new Error(data.error?.message || 'Ошибка запроса'), { code: data.error?.code });
    return data;
  }

  function renderCart(cart) {
    const root = $('cart');
    root.textContent = '';
    if (!cart || !Array.isArray(cart.items) || cart.items.length === 0) {
      root.textContent = 'Корзина пока пуста';
      return;
    }
    const list = document.createElement('ul');
    cart.items.forEach(item => {
      const li = document.createElement('li');
      li.textContent = `${item.name}: ${item.quantity} шт. — ${item.line_total} KZT`;
      list.appendChild(li);
    });
    root.appendChild(list);
    const total = document.createElement('p');
    total.textContent = `Итого: ${cart.total} KZT`;
    root.appendChild(total);
    if (cart.cart_url) {
      const a = document.createElement('a');
      a.href = cart.cart_url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = 'Открыть безопасную ссылку просмотра';
      root.appendChild(a);
    }
  }

  function renderAction(action) {
    currentAction = action;
    const card = document.createElement('div');
    card.className = 'card';
    const p = document.createElement('p');
    p.textContent = `Предложение: ${action.product_name}, склад ${action.warehouse_id}, ${action.quantity_to_add} шт. × ${action.unit_price} KZT = ${action.added_amount} KZT. Действует до ${new Date(action.expires_at).toLocaleString()}.`;
    card.appendChild(p);
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = 'Подтвердить добавление';
    b.onclick = () => confirmAction(action.action_id, b);
    card.appendChild(b);
    dialog.appendChild(card);
    dialog.scrollTop = dialog.scrollHeight;
  }

  async function confirmAction(actionId, button) {
    if (busy) return;
    busy = true;
    button.disabled = true;
    try {
      const result = await api(`/api/v1/cart/actions/${encodeURIComponent(actionId)}/confirm`, { method: 'POST' });
      addBubble(result.already_applied ? 'Предложение уже было применено.' : 'Товар добавлен в корзину.');
      renderCart(result.cart);
      currentAction = null;
    } catch (e) {
      addBubble(`Не удалось подтвердить предложение: ${e.message}${e.code ? ' (' + e.code + ')' : ''}`);
      button.disabled = false;
    } finally {
      busy = false;
    }
  }

  async function send(message) {
    if (busy) return;
    busy = true;
    addBubble(message, 'user');
    const pending = currentAction?.action_id;
    try {
      const response = await api('/api/v1/chat', {
        method: 'POST',
        body: JSON.stringify({
          message,
          warehouse_id: $('warehouse').value || null,
          confirmation_action_id: pending || null
        })
      });
      addBubble(response.message);
      if (response.warnings && response.warnings.length) renderWarnings(response.warnings);
      if (response.products && response.products.length) renderProducts(response.products);
      if (response.pending_action) renderAction(response.pending_action);
      if (response.cart) renderCart(response.cart);
    } catch (e) {
      addBubble(`Ошибка: ${e.message}${e.code ? ' (' + e.code + ')' : ''}`, 'assistant');
    } finally {
      busy = false;
    }
  }

  $('chat-form').addEventListener('submit', e => {
    e.preventDefault();
    const input = $('message');
    const value = input.value.trim();
    if (value) {
      input.value = '';
      send(value);
    }
  });

  async function start() {
    try {
      const session = await api('/api/v1/sessions', { method: 'POST' });
      token = session.session_token;
      const warehouses = await api('/api/v1/warehouses');
      const select = $('warehouse');
      select.textContent = '';
      warehouses.warehouses.forEach(w => {
        const o = document.createElement('option');
        o.value = w.warehouse_id;
        o.textContent = `${w.name}${w.eligible === true ? '' : ' — пригодность неизвестна'}`;
        select.appendChild(o);
      });
      select.disabled = false;
      if (!warehouses.warehouses.length) $('warehouse-note').textContent = 'Склады не найдены в доступной выборке.';
      const cart = await api('/api/v1/cart');
      renderCart(cart);
      addBubble('Сессия создана. Выберите склад и задайте вопрос. Для сквозного демо используйте: DEMO-001 → 2 шт.');
    } catch (e) {
      addBubble(`Не удалось запустить сессию: ${e.message}`, 'assistant');
    }
  }

  start();
})();
