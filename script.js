const catalog = [
  { article: 'EL-101', name: 'Автоматический выключатель 16 A', characteristics: '1P, характеристика C, 6 кА, для бытового щита', price: 1850, stock: 24 },
  { article: 'EL-102', name: 'Светодиодная лампа 12 Вт', characteristics: 'E27, 3000 К, 1050 лм, тёплый свет', price: 1290, stock: 60 },
  { article: 'EL-103', name: 'Кабель ВВГнг-LS 3×2,5', characteristics: 'медный, 0,66 кВ, оболочка LS, бухта 20 м', price: 15900, stock: 12 },
  { article: 'EL-104', name: 'Кабель NYM 3×2,5', characteristics: 'медный, 0,66 кВ, бухта 20 м', price: 17200, stock: 0, analogArticle: 'EL-105' },
  { article: 'EL-105', name: 'Кабель ВВГнг 3×2,5', characteristics: 'медный, 0,66 кВ, оболочка ПВХ, бухта 20 м', price: 14800, stock: 18, analogyReason: 'похожее сечение 3×2,5 и медные жилы' },
  { article: 'EL-106', name: 'Удлинитель 5 розеток, 3 м', characteristics: '16 A, 3×1,5 мм², выключатель, защита от перегрузки', price: 5200, stock: 8 },
];

const CART_KEY = 'hackalem-ai-cart';
let cart = loadCart();
const appliedProposals = new Set();

const elements = {
  messages: document.querySelector('#messages'),
  form: document.querySelector('#chat-form'),
  query: document.querySelector('#query'),
  cartItems: document.querySelector('#cart-items'),
  cartCount: document.querySelector('#cart-count'),
  cartTotal: document.querySelector('#cart-total'),
};

function normalize(value) {
  return String(value || '').toLocaleLowerCase('ru-RU').replace(/ё/g, 'е').replace(/[×x]/g, 'x').replace(/[^a-zа-я0-9.]+/gi, ' ').trim();
}

function findProduct(query) {
  const needle = normalize(query);
  if (!needle) return undefined;
  return catalog.find((product) => normalize(product.article) === needle)
    || catalog.find((product) => normalize(product.name).includes(needle))
    || catalog.find((product) => normalize(product.article).includes(needle));
}

function findAnalog(product) {
  return product && product.analogArticle ? catalog.find((item) => item.article === product.analogArticle) : undefined;
}

function formatPrice(price) { return `${new Intl.NumberFormat('ru-RU').format(price)} ₸`; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char])); }

function addMessage(content, role = 'bot') {
  const message = document.createElement('div');
  message.className = `message ${role}`;
  message.innerHTML = role === 'bot'
    ? `<div class="bot-mark">AI</div><div class="message-bubble">${content}</div>`
    : `<div class="message-bubble">${escapeHtml(content)}</div>`;
  elements.messages.append(message);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function productCard(product, options = {}) {
  const { analog = false, proposalId = `${product.article}-${Date.now()}-${Math.random().toString(36).slice(2)}` } = options;
  const current = cart.find((item) => item.article === product.article);
  const remaining = Math.max(0, product.stock - (current ? current.quantity : 0));
  const disabled = product.stock === 0 || remaining === 0;
  const status = product.stock === 0 ? 'Нет в наличии' : `В наличии: ${remaining} шт.`;

  return `<div class="product-card ${analog ? 'analog' : ''}">
    <div class="product-top"><div><p class="product-name">${escapeHtml(product.name)}</p><span class="article">${product.article}</span></div><span class="price">${formatPrice(product.price)}</span></div>
    <p class="specs">${escapeHtml(product.characteristics)}</p>
    <span class="stock ${product.stock === 0 ? 'empty' : ''}">${status}</span>
    ${disabled ? '' : `<div class="add-row"><input class="quantity" type="number" min="1" max="${remaining}" value="1" aria-label="Количество ${escapeHtml(product.name)}" data-quantity-for="${proposalId}"><button type="button" class="confirm-button" data-proposal-id="${proposalId}" data-article="${product.article}">Подтвердить добавление</button></div>`}
  </div>`;
}

function respondToQuery(query) {
  const text = normalize(query);
  if (!text) {
    addMessage('Напишите артикул или название товара. Например: <strong>EL-101</strong>, <strong>удлинитель</strong> или спросите про доставку.');
    return;
  }

  const product = findProduct(query);
  if (product) {
    if (product.stock === 0) {
      const analog = findAnalog(product);
      addMessage(`<strong>${escapeHtml(product.name)}</strong> (${product.article}) сейчас отсутствует. Цена: ${formatPrice(product.price)}. Могу предложить аналог с ${escapeHtml(analog.analogyReason || 'похожими характеристиками')}: ${productCard(analog, { analog })}`);
    } else {
      addMessage(`<strong>Нашёл товар:</strong> ${productCard(product)}`);
    }
    return;
  }

  if (/оплат|платеж|рассчит|карта|наличн/.test(text)) {
    addMessage('<strong>Оплата:</strong> в демо доступны условные способы — карта или наличные при получении. Это демонстрационные условия, реальная оплата не подключена.');
    return;
  }

  if (/достав|курьер|самовывоз|получ/.test(text)) {
    addMessage('<strong>Доставка:</strong> в демо заказ можно забрать самовывозом или выбрать условную доставку по городу. Это демонстрационные условия, оформление доставки не подключено.');
    return;
  }

  addMessage('Пока я отвечаю по тестовому каталогу, оплате и доставке. Попробуйте найти товар по артикулу или названию — например: <strong>EL-104</strong>, <strong>кабель</strong> или <strong>условия оплаты</strong>.');
}

function loadCart() {
  try {
    const saved = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
    return Array.isArray(saved) ? saved.filter((item) => {
      const product = catalog.find((candidate) => candidate.article === item.article);
      return product && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= product.stock;
    }).map((item) => ({ ...item, price: catalog.find((product) => product.article === item.article).price })) : [];
  } catch (error) {
    return [];
  }
}

function saveCart() { localStorage.setItem(CART_KEY, JSON.stringify(cart)); }

function renderCart() {
  const count = cart.reduce((total, item) => total + item.quantity, 0);
  const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
  elements.cartCount.textContent = count;
  elements.cartTotal.textContent = formatPrice(total);
  elements.cartItems.innerHTML = cart.length ? cart.map((item) => `<div class="cart-item"><div><div class="cart-item-name">${escapeHtml(item.name)}</div><div class="cart-item-meta">${item.article} · ${item.quantity} шт.</div></div><div class="cart-item-price">${formatPrice(item.price * item.quantity)}<div class="cart-item-qty">${formatPrice(item.price)} / шт.</div></div></div>`).join('') : '<div class="empty-cart"><b>Корзина пока пуста</b>Найдите товар в чате и подтвердите добавление.</div>';
}

function confirmProposal(button) {
  const proposalId = button.dataset.proposalId;
  if (appliedProposals.has(proposalId)) return;
  const product = catalog.find((item) => item.article === button.dataset.article);
  const input = document.querySelector(`[data-quantity-for="${proposalId}"]`);
  const requested = Number(input.value);
  const current = cart.find((item) => item.article === product.article);
  const available = Math.max(0, product.stock - (current ? current.quantity : 0));
  const quantity = Number.isInteger(requested) && requested > 0 ? Math.min(requested, available) : 0;
  if (!quantity) {
    input.setCustomValidity(`Укажите целое число от 1 до ${available}.`);
    input.reportValidity();
    return;
  }
  if (current) current.quantity += quantity;
  else cart.push({ article: product.article, name: product.name, price: product.price, quantity });
  appliedProposals.add(proposalId);
  saveCart();
  renderCart();
  button.disabled = true;
  button.textContent = 'Добавлено в корзину';
  addMessage(`Готово — добавил(а) <strong>${quantity} шт.</strong> товара «${escapeHtml(product.name)}». <a href="#cart">Открыть корзину</a>.`);
}

elements.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const query = elements.query.value.trim();
  if (!query) return;
  addMessage(query, 'user');
  elements.query.value = '';
  respondToQuery(query);
});

document.addEventListener('click', (event) => {
  const example = event.target.closest('[data-query]');
  if (example) {
    elements.query.value = example.dataset.query;
    elements.form.requestSubmit();
  }
  const button = event.target.closest('.confirm-button');
  if (button) confirmProposal(button);
});

addMessage('Здравствуйте! Я помогу найти тестовые электротовары по артикулу или названию. Можно также спросить про <strong>оплату</strong> и <strong>доставку</strong>.');
renderCart();
