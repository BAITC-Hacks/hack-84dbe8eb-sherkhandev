const catalog = [
  {
    article: 'EL-101',
    name: 'Автоматический выключатель 16 A',
    characteristics: '1P, характеристика C, 6 кА, для бытового щита',
    price: 1850,
    stock: 24,
  },
  {
    article: 'EL-102',
    name: 'Светодиодная лампа 12 Вт',
    characteristics: 'E27, 3000 К, 1050 лм, тёплый свет',
    price: 1290,
    stock: 60,
  },
  {
    article: 'EL-103',
    name: 'Кабель ВВГнг-LS 3×2,5',
    characteristics: 'медный, 0,66 кВ, оболочка LS, бухта 20 м',
    price: 15900,
    stock: 12,
  },
  {
    article: 'EL-104',
    name: 'Кабель NYM 3×2,5',
    characteristics: 'медный, 0,66 кВ, бухта 20 м',
    price: 17200,
    stock: 0,
    analogArticle: 'EL-105',
  },
  {
    article: 'EL-105',
    name: 'Кабель ВВГнг 3×2,5',
    characteristics: 'медный, 0,66 кВ, оболочка ПВХ, бухта 20 м',
    price: 14800,
    stock: 18,
    analogyReason: 'похожее сечение 3×2,5 и медные жилы',
  },
  {
    article: 'EL-106',
    name: 'Удлинитель 5 розеток, 3 м',
    characteristics: '16 A, 3×1,5 мм², выключатель, защита от перегрузки',
    price: 5200,
    stock: 8,
  },
];

function normalize(value) {
  return String(value || '')
    .toLocaleLowerCase('ru-RU')
    .replace(/ё/g, 'е')
    .replace(/[×x]/g, 'x')
    .replace(/[^a-zа-я0-9.]+/gi, ' ')
    .trim();
}

function findProduct(query) {
  const needle = normalize(query);
  if (!needle) return undefined;

  return catalog.find((product) => normalize(product.article) === needle)
    || catalog.find((product) => normalize(product.name).includes(needle))
    || catalog.find((product) => normalize(product.article).includes(needle));
}

function findAnalog(product) {
  if (!product || !product.analogArticle) return undefined;
  return catalog.find((candidate) => candidate.article === product.analogArticle);
}

function getCartTotal(cart) {
  return cart.reduce((total, item) => {
    const product = catalog.find((candidate) => candidate.article === item.article);
    return total + (item.price || (product ? product.price : 0)) * item.quantity;
  }, 0);
}

function prepareCartAddition(cart, product, requestedQuantity) {
  const requested = Number(requestedQuantity);
  const currentItem = cart.find((item) => item.article === product.article);
  const currentQuantity = currentItem ? currentItem.quantity : 0;
  const available = Math.max(0, product.stock - currentQuantity);
  const quantity = Number.isInteger(requested) && requested > 0
    ? Math.min(requested, available)
    : 0;

  return {
    id: `${product.article}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    article: product.article,
    product,
    quantity,
  };
}

function confirmCartAddition(cart, pending, appliedIds = new Set()) {
  if (!pending || !pending.quantity || appliedIds.has(pending.id)) {
    return { cart, added: false };
  }

  const nextCart = cart.map((item) => ({ ...item }));
  const currentIndex = nextCart.findIndex((item) => item.article === pending.article);
  const existing = currentIndex >= 0 ? nextCart[currentIndex] : null;
  const product = pending.product;
  const nextQuantity = Math.min(
    product.stock,
    (existing ? existing.quantity : 0) + pending.quantity,
  );

  if (currentIndex >= 0) {
    nextCart[currentIndex].quantity = nextQuantity;
  } else if (nextQuantity > 0) {
    nextCart.push({
      article: product.article,
      name: product.name,
      price: product.price,
      quantity: nextQuantity,
    });
  }

  appliedIds.add(pending.id);
  return { cart: nextCart, added: nextQuantity > 0 };
}

module.exports = {
  catalog,
  findProduct,
  findAnalog,
  prepareCartAddition,
  confirmCartAddition,
  getCartTotal,
};
