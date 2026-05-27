export function menu() {
  return {
    categories: [
      {
        name: 'Espresso Drinks',
        items: [
          { name: 'Espresso', price: '$3.50', desc: 'Double shot of our house blend — bright citrus notes with a lingering chocolate finish.', tag: 'House blend' },
          { name: 'Cortado', price: '$4.25', desc: 'Equal parts espresso and warm steamed milk, no foam. Bold and balanced.', tag: null },
          { name: 'Cappuccino', price: '$4.75', desc: 'Velvety microfoam over a double shot. Classic Italian proportions, nothing more.', tag: null },
          { name: 'Flat White', price: '$4.75', desc: 'Double ristretto pulled short, topped with silky steamed whole milk.', tag: 'Popular' },
          { name: 'Latte', price: '$5.25', desc: 'Double espresso and your choice of milk, steamed to order. Available in 12 oz or 16 oz.', tag: null },
          { name: 'Oat Honey Latte', price: '$6.00', desc: 'Our latte made with oat milk and a swirl of local wildflower honey. Naturally sweet.', tag: 'Staff pick' },
        ],
      },
      {
        name: 'Pour-Over & Batch Brew',
        items: [
          { name: 'Drip Coffee', price: '$3.00', desc: 'Rotating single-origin, brewed fresh every 45 minutes. Ask your barista what\'s on today.', tag: null },
          { name: 'V60 Pour-Over', price: '$6.50', desc: 'Hand-poured to order using 93°C filtered water. Takes 5–6 minutes — worth every second.', tag: 'Slow brew' },
          { name: 'Cold Brew', price: '$5.50', desc: '20-hour steep in cold filtered water, served over ice. Smooth, low-acid, slightly sweet.', tag: null },
          { name: 'Nitro Cold Brew', price: '$6.25', desc: 'Cold brew on nitrogen tap — creamy head, no ice needed. Like a coffee stout without the ABV.', tag: 'Draft' },
        ],
      },
      {
        name: 'Non-Coffee & Tea',
        items: [
          { name: 'Matcha Latte', price: '$5.75', desc: 'Ceremonial-grade matcha whisked with oat milk. Earthy, grassy, naturally energising.', tag: null },
          { name: 'Golden Turmeric Latte', price: '$5.75', desc: 'Turmeric, ginger, cinnamon, and black pepper blended with steamed oat milk.', tag: 'Vegan' },
          { name: 'Loose-Leaf Tea', price: '$4.00', desc: 'Choice of English Breakfast, Earl Grey, chamomile, or gunpowder green. Pot for one.', tag: null },
          { name: 'Fresh Lemonade', price: '$4.50', desc: 'House-squeezed daily with Meyer lemons and a touch of raw cane sugar. Ask for a lavender shot.', tag: 'Seasonal' },
        ],
      },
      {
        name: 'Pastries & Food',
        items: [
          { name: 'Butter Croissant', price: '$4.00', desc: 'Flaky, laminated layers from our bakery partner Boulangerie Soleil. Baked fresh each morning.', tag: null },
          { name: 'Cardamom Morning Bun', price: '$4.50', desc: 'Swirled with cinnamon sugar and cardamom, rolled in orange zest. A house specialty.', tag: 'House made' },
          { name: 'Avocado Toast', price: '$9.00', desc: 'Smashed avocado on toasted sourdough with chili flakes, everything seasoning, and a lemon wedge.', tag: null },
          { name: 'Seasonal Quiche Slice', price: '$7.50', desc: 'Rotating filling using locally sourced vegetables and Tillamook cheddar. Ask about today\'s.', tag: 'Local' },
        ],
      },
    ],
  };
}
