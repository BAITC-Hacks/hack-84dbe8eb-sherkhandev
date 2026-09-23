const assert = require('assert');
const {
  catalog,
  findProduct,
  findAnalog,
  prepareCartAddition,
  confirmCartAddition,
  getCartTotal,
} = require('../app.js');

function test(name, fn) {
  try {
    fn();
    console.log(`✓ ${name}`);
  } catch (error) {
    console.error(`✗ ${name}`);
    throw error;
  }
}

test('находит товар по артикулу и названию', () => {
  assert.strictEqual(findProduct('EL-101').article, 'EL-101');
  assert.strictEqual(findProduct('удлинитель').article, 'EL-106');
});

test('предлагает заранее заданный аналог для отсутствующего товара', () => {
  const unavailable = findProduct('EL-104');
  const analog = findAnalog(unavailable);

  assert.strictEqual(unavailable.stock, 0);
  assert.strictEqual(analog.article, 'EL-105');
  assert.match(analog.analogyReason, /сечение|характеристик/i);
});

test('подготовка добавления не меняет корзину до подтверждения', () => {
  const product = findProduct('EL-101');
  const cart = [];
  const pending = prepareCartAddition(cart, product, 2);

  assert.strictEqual(getCartTotal(cart), 0);
  assert.strictEqual(pending.quantity, 2);
});

test('ограничивает добавление остатком и не дублирует повторное подтверждение', () => {
  const product = findProduct('EL-101');
  let cart = [{ article: product.article, quantity: product.stock - 1 }];
  const pending = prepareCartAddition(cart, product, 10);
  const appliedIds = new Set();

  assert.strictEqual(pending.quantity, 1);
  cart = confirmCartAddition(cart, pending, appliedIds).cart;
  cart = confirmCartAddition(cart, pending, appliedIds).cart;

  assert.strictEqual(cart[0].quantity, product.stock);
  assert.strictEqual(getCartTotal(cart), product.stock * product.price);
});

console.log(`Проверено товаров в каталоге: ${catalog.length}`);
