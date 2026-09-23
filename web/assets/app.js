(() => {
  'use strict';

  let token = null, currentAction = null, busy = false;
  const $ = id => document.getElementById(id);
  const dialog = $('dialog');

  function escapeHtml(str) {
    if (typeof str !== 'string') return String(str ?? '');
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatMoney(amount) {
    if (amount == null || amount === '') return '—';
    const num = Number(amount);
    if (isNaN(num)) return `${amount} KZT`;
    return `${num.toLocaleString('ru-RU')} KZT`;
  }

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
    const row = document.createElement('div');
    row.className = `message-row ${kind}`;

    const avatar = document.createElement('div');
    avatar.className = `message-avatar ${kind === 'assistant' ? 'ai' : 'user-avatar'}`;
    avatar.textContent = kind === 'assistant' ? '✦' : '👤';
    row.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = `bubble ${kind}`;
    bubble.textContent = text;
    row.appendChild(bubble);

    dialog.appendChild(row);
    dialog.scrollTop = dialog.scrollHeight;
    return bubble;
  }

  function showTypingIndicator() {
    removeTypingIndicator();
    const row = document.createElement('div');
    row.id = 'typing-indicator';
    row.className = 'typing-row';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar ai';
    avatar.textContent = '✦';
    row.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = 'typing-bubble';
    bubble.innerHTML = `
      <span>AI обрабатывает запрос</span>
      <span class="typing-dots">
        <span></span><span></span><span></span>
      </span>
    `;
    row.appendChild(bubble);

    dialog.appendChild(row);
    dialog.scrollTop = dialog.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = $('typing-indicator');
    if (el) el.remove();
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

      const isSynthetic = p.source_kind === 'synthetic';
      const badge = document.createElement('span');
      badge.className = `badge badge-${isSynthetic ? 'synthetic' : 'ekt'}`;
      badge.textContent = isSynthetic ? 'демо-данные (synthetic)' : 'данные EKT';
      header.appendChild(badge);
      card.appendChild(header);

      const meta = document.createElement('div');
      meta.className = 'product-meta';

      const article = document.createElement('span');
      article.className = 'product-article';
      article.textContent = `Арт: ${p.article || '—'}`;
      meta.appendChild(article);

      const price = document.createElement('span');
      price.className = 'product-price';
      price.textContent = formatMoney(p.price);
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
            link.textContent = `📄 ${label}`;
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
    const badge = $('cart-badge');
    root.textContent = '';

    if (!cart || !Array.isArray(cart.items) || cart.items.length === 0) {
      if (badge) badge.textContent = '0';
      root.innerHTML = `
        <div class="cart-empty">
          <div class="cart-empty-icon">🛒</div>
          <div class="cart-empty-title">Корзина пуста</div>
          <div class="cart-empty-subtitle">Спросите консультанта подобрать товары или введите артикул.</div>
        </div>
      `;
      return;
    }

    const totalCount = cart.items.reduce((acc, item) => acc + (item.quantity || 1), 0);
    if (badge) badge.textContent = String(totalCount);

    const list = document.createElement('ul');
    list.className = 'cart-list';

    cart.items.forEach(item => {
      const li = document.createElement('li');
      li.className = 'cart-item';

      const details = document.createElement('div');
      details.className = 'cart-item-details';

      const name = document.createElement('span');
      name.className = 'cart-item-name';
      name.textContent = item.name;
      details.appendChild(name);

      const qty = document.createElement('span');
      qty.className = 'cart-item-qty';
      qty.textContent = `${item.quantity} шт.`;
      details.appendChild(qty);

      li.appendChild(details);

      const total = document.createElement('span');
      total.className = 'cart-item-total';
      total.textContent = formatMoney(item.line_total);
      li.appendChild(total);

      list.appendChild(li);
    });
    root.appendChild(list);

    const summary = document.createElement('div');
    summary.className = 'cart-summary';
    summary.innerHTML = `
      <span class="cart-summary-label">Итого:</span>
      <strong class="cart-total-value">${formatMoney(cart.total)}</strong>
    `;
    root.appendChild(summary);

    if (cart.cart_url) {
      const a = document.createElement('a');
      a.href = cart.cart_url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.className = 'cart-view-link';
      a.innerHTML = `
        <span>Безопасная ссылка просмотра</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      `;
      root.appendChild(a);
    }
  }

  function renderAction(action) {
    currentAction = action;
    const card = document.createElement('div');
    card.className = 'card action-offer-card';

    const title = document.createElement('div');
    title.className = 'card-title';
    title.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <polyline points="12 6 12 12 16 14"></polyline>
      </svg>
      <span>Предложение к подтверждению</span>
    `;
    card.appendChild(title);

    const detailsGrid = document.createElement('div');
    detailsGrid.className = 'card-details-grid';

    const expiryTime = action.expires_at ? new Date(action.expires_at).toLocaleTimeString() : '5 мин.';

    detailsGrid.innerHTML = `
      <div class="card-detail-item">
        <span class="card-detail-label">Товар</span>
        <span class="card-detail-val">${escapeHtml(action.product_name)}</span>
      </div>
      <div class="card-detail-item">
        <span class="card-detail-label">Склад</span>
        <span class="card-detail-val">${escapeHtml(action.warehouse_id)}</span>
      </div>
      <div class="card-detail-item">
        <span class="card-detail-label">Количество</span>
        <span class="card-detail-val">${action.quantity_to_add} шт.</span>
      </div>
      <div class="card-detail-item">
        <span class="card-detail-label">Цена за ед.</span>
        <span class="card-detail-val">${formatMoney(action.unit_price)}</span>
      </div>
      <div class="card-detail-item">
        <span class="card-detail-label">Сумма</span>
        <span class="card-detail-val" style="color: var(--primary);">${formatMoney(action.added_amount)}</span>
      </div>
      <div class="card-detail-item">
        <span class="card-detail-label">Действует до</span>
        <span class="card-detail-val" style="font-size: 0.85rem; font-weight: 550;">${expiryTime}</span>
      </div>
    `;
    card.appendChild(detailsGrid);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'card-confirm-btn';
    btn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"></polyline>
      </svg>
      <span>Подтвердить добавление в корзину</span>
    `;
    btn.onclick = () => confirmAction(action.action_id, btn);
    card.appendChild(btn);

    dialog.appendChild(card);
    dialog.scrollTop = dialog.scrollHeight;
  }

  async function confirmAction(actionId, button) {
    if (busy) return;
    busy = true;
    button.disabled = true;
    try {
      const result = await api(`/api/v1/cart/actions/${encodeURIComponent(actionId)}/confirm`, { method: 'POST' });
      addBubble(result.already_applied ? 'Предложение уже было применено.' : '✓ Товар успешно добавлен в корзину.');
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
    const sendBtn = $('send-btn');
    if (sendBtn) sendBtn.disabled = true;

    addBubble(message, 'user');
    showTypingIndicator();

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
      removeTypingIndicator();
      addBubble(response.message);
      if (response.warnings && response.warnings.length) renderWarnings(response.warnings);
      if (response.products && response.products.length) renderProducts(response.products);
      if (response.pending_action) renderAction(response.pending_action);
      if (response.cart) renderCart(response.cart);
    } catch (e) {
      removeTypingIndicator();
      let errText = e.message;
      if (e.code === 'WAREHOUSE_NOT_ELIGIBLE') {
        errText = 'Выбранный склад не предназначен для продажи. Пожалуйста, переключитесь на склад с подтверждённой доступностью (например, «Учебный склад»).';
      }
      addBubble(`Ошибка: ${errText}${e.code ? ' (' + e.code + ')' : ''}`, 'assistant');
    } finally {
      busy = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  // Quick Chips interaction
  document.querySelectorAll('.quick-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.getAttribute('data-prompt');
      if (prompt && !busy) {
        const input = $('message');
        if (input) input.value = '';
        send(prompt);
      }
    });
  });

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
      const whMap = {};
      let firstEligibleValue = null;

      warehouses.warehouses.forEach(w => {
        whMap[w.warehouse_id] = w;
        const o = document.createElement('option');
        o.value = w.warehouse_id;
        const isEligible = w.eligible === true;
        o.textContent = `${w.name}${isEligible ? ' (Доступен для заказа)' : ' — пригодность неизвестна'}`;
        if (isEligible && firstEligibleValue === null) {
          firstEligibleValue = w.warehouse_id;
        }
        select.appendChild(o);
      });

      if (firstEligibleValue !== null) {
        select.value = firstEligibleValue;
      }
      select.disabled = false;

      function updateWarehouseNote() {
        const currentWh = whMap[select.value];
        const note = $('warehouse-note');
        if (!currentWh) {
          if (!warehouses.warehouses.length) note.textContent = 'Склады не найдены в доступной выборке.';
          return;
        }
        if (currentWh.eligible === true) {
          note.textContent = '✓ Склад доступен для продажи и оформления заказа.';
          note.style.color = 'var(--success-text)';
        } else {
          note.textContent = '⚠️ Данный склад не подтверждён для продажи (заказ недоступен).';
          note.style.color = 'var(--warning-text)';
        }
      }

      select.addEventListener('change', updateWarehouseNote);
      updateWarehouseNote();

      const cart = await api('/api/v1/cart');
      renderCart(cart);
      addBubble('Здравствуйте! Сессия создана. Выберите склад и задайте вопрос по каталогу EKT.\n\nДля проверки сквозного сценария воспользуйтесь кнопкой «DEMO-001, 2 шт.» или введите артикул вручную.');
    } catch (e) {
      addBubble(`Не удалось запустить сессию: ${e.message}`, 'assistant');
    }
  }

  start();
})();
