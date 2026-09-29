export function iceCreamApp() {
  return {
    flavors: [
      { name: 'Madagascar Vanilla', emoji: '🌼', tag: 'Classic', price: 5.50,
        description: 'Real vanilla beans steeped overnight in cream. Speckled, fragrant, the gold standard.' },
      { name: 'Dark Chocolate Sorbet', emoji: '🍫', tag: 'Vegan', price: 5.75,
        description: 'Single-origin Ecuadorian cocoa. Dense, almost fudge-like. Zero dairy.' },
      { name: 'Strawberry Buttermilk', emoji: '🍓', tag: 'Seasonal', price: 6.00,
        description: 'Roasted Tristar strawberries and tangy local buttermilk. Tastes like June.' },
      { name: 'Salted Honeycomb', emoji: '🍯', tag: 'Classic', price: 5.75,
        description: 'Caramelized honeycomb shards folded into salted-cream base. Crunch, then melt.' },
      { name: 'Matcha Black Sesame', emoji: '🍵', tag: 'Seasonal', price: 6.25,
        description: 'Ceremonial-grade matcha swirled with toasty black sesame paste. Earthy and grown-up.' },
      { name: 'Brown Butter Pecan', emoji: '🥮', tag: 'Classic', price: 5.75,
        description: 'Butter cooked till nutty, candied pecans, a whisper of bourbon.' },
      { name: 'Coconut Lime Sorbet', emoji: '🥥', tag: 'Vegan', price: 5.50,
        description: 'Young coconut cream and key lime juice. Bright, creamy, dairy-free.' },
      { name: 'Coffee Toffee Crunch', emoji: '☕', tag: 'Classic', price: 5.75,
        description: 'Cold-brew concentrate from our neighbors at Parlor Roasters, plus shattered toffee.' },
      { name: 'Peach Basil', emoji: '🍑', tag: 'Seasonal', price: 6.00,
        description: 'Sun-warm Jersey peaches and a confetti of fresh basil. Surprisingly perfect.' },
    ],
    bases: ['Waffle cone', 'Sugar cone', 'Cup', 'Brioche bun (ice cream sandwich)'],
    toppings: ['Rainbow sprinkles', 'Chocolate sprinkles', 'Hot fudge', 'Salted caramel', 'Whipped cream', 'Crushed pretzels', 'Fresh berries', 'Toasted almonds'],
    order: { base: 'Waffle cone', scoops: [], toppings: [] },
    message: '',
    savedOrders: [],

    init() {
      const raw = localStorage.getItem('icecream:orders');
      if (raw) {
        try { this.savedOrders = JSON.parse(raw); } catch { this.savedOrders = []; }
      }
    },

    total() {
      const baseCost = this.order.base === 'Waffle cone' ? 1.50
        : this.order.base === 'Brioche bun (ice cream sandwich)' ? 2.00
        : this.order.base === 'Sugar cone' ? 0.75 : 0;
      const scoopCost = this.order.scoops.reduce((sum, name) => {
        const f = this.flavors.find(x => x.name === name);
        return sum + (f ? f.price : 0);
      }, 0);
      const toppingCost = this.order.toppings.length * 0.50;
      return baseCost + scoopCost + toppingCost;
    },

    placeOrder() {
      if (!this.order.scoops.length) {
        this.message = 'Pick at least one scoop first!';
        setTimeout(() => this.message = '', 2500);
        return;
      }
      const entry = {
        base: this.order.base,
        scoops: [...this.order.scoops],
        toppings: [...this.order.toppings],
        total: this.total(),
        at: new Date().toISOString(),
      };
      this.savedOrders.unshift(entry);
      localStorage.setItem('icecream:orders', JSON.stringify(this.savedOrders));
      this.message = `Saved! Show this screen at the counter. 🍦`;
      this.order = { base: 'Waffle cone', scoops: [], toppings: [] };
      setTimeout(() => this.message = '', 3000);
    },

    removeOrder(i) {
      this.savedOrders.splice(i, 1);
      localStorage.setItem('icecream:orders', JSON.stringify(this.savedOrders));
    },
  };
}
