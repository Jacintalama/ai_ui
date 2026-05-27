// src/data.js — restaurants + menus.

const cuisines = ["Pizza", "Sushi", "Burger", "Asian", "Mexican", "Vegan", "Indian", "Thai"];

// 14 restaurants, deterministic seed-generated.
const restaurantSeeds = [
  ["Tony's Pizza", "Pizza", 4.7, 25],
  ["Sushi Kai", "Sushi", 4.8, 35],
  ["Burger Block", "Burger", 4.5, 20],
  ["Mei Wok", "Asian", 4.6, 30],
  ["Casa Lupita", "Mexican", 4.4, 28],
  ["Green Roots", "Vegan", 4.7, 32],
  ["Taj Spice", "Indian", 4.5, 38],
  ["Bangkok Heat", "Thai", 4.6, 28],
  ["Slice & Co", "Pizza", 4.3, 22],
  ["Nori House", "Sushi", 4.7, 40],
  ["Patty Lane", "Burger", 4.2, 18],
  ["Wok Around", "Asian", 4.5, 32],
  ["Verde", "Vegan", 4.6, 30],
  ["Curry Club", "Indian", 4.4, 35],
];

// Stable Unsplash photo IDs (food + restaurant interiors)
const heroPhotos = [
  "1565299624946-b28f40a0ae38", "1579871494447-9811cf80d66c",
  "1568901346375-23c9450c58cd", "1552566626-52f8b828add9",
  "1564507592333-c60657eea523", "1490645935967-10de6ba17061",
  "1565557623262-b51c2513a641", "1562565652-a0d8f0c59eb4",
  "1513104890138-7c749659a591", "1579584425555-c3ce17fd4351",
  "1568901346375-23c9450c58cd", "1547573854-74d2a71d0826",
  "1490645935967-10de6ba17061", "1565958011703-44f9829ba187",
];

// Generic menu-item templates per cuisine (8 base items, varied by restaurant).
const itemTemplatesByCuisine = {
  Pizza: [
    ["Margherita", 14, "Tomato, mozzarella, basil"],
    ["Pepperoni", 16, "Cured pepperoni, mozzarella"],
    ["Quattro Formaggi", 17, "Four-cheese blend"],
    ["Funghi", 16, "Wild mushroom, thyme"],
    ["Diavola", 17, "Spicy salami, chili oil"],
    ["Bianca", 15, "White pizza, ricotta, garlic"],
    ["Capricciosa", 18, "Ham, mushroom, artichoke, olive"],
    ["Marinara", 13, "Tomato, garlic, oregano"],
  ],
  Sushi: [
    ["Salmon Nigiri (2pc)", 7, "Fresh Atlantic salmon"],
    ["Tuna Nigiri (2pc)", 8, "Yellowfin tuna"],
    ["California Roll", 11, "Crab, avocado, cucumber"],
    ["Spicy Tuna Roll", 12, "Tuna, sriracha mayo"],
    ["Dragon Roll", 15, "Eel, avocado, tobiko"],
    ["Rainbow Roll", 16, "Assorted sashimi over California"],
    ["Miso Soup", 4, "Tofu, scallion, wakame"],
    ["Edamame", 5, "Steamed soy beans, sea salt"],
  ],
  Burger: [
    ["Classic Burger", 12, "Beef, lettuce, tomato, pickle"],
    ["Cheese Burger", 13, "Add aged cheddar"],
    ["Bacon Burger", 15, "Bacon, cheddar, mayo"],
    ["Mushroom Swiss", 14, "Mushroom, swiss cheese"],
    ["BBQ Burger", 15, "BBQ sauce, onion ring"],
    ["Veggie Burger", 13, "Black bean, avocado"],
    ["Truffle Fries", 8, "Parmesan, truffle oil"],
    ["Onion Rings", 6, "Beer-battered, ranch"],
  ],
  Asian: [
    ["Beef & Broccoli", 14, "Garlic, soy, ginger"],
    ["Sweet & Sour Chicken", 13, "Pineapple, peppers"],
    ["Mongolian Beef", 15, "Scallion, soy glaze"],
    ["Kung Pao Chicken", 13, "Peanuts, chili"],
    ["Vegetable Lo Mein", 11, "Soft noodles, garden veg"],
    ["Pork Dumplings (6pc)", 9, "Soy-vinegar dip"],
    ["Hot & Sour Soup", 6, "Tofu, bamboo, egg"],
    ["Fried Rice", 10, "Egg, scallion, peas"],
  ],
  Mexican: [
    ["Beef Tacos (3pc)", 12, "Cilantro, onion, lime"],
    ["Chicken Burrito", 13, "Rice, beans, salsa"],
    ["Veggie Quesadilla", 11, "Cheese, peppers"],
    ["Chips & Guac", 8, "Fresh avocado, lime"],
    ["Pork Carnitas Bowl", 14, "Rice, beans, pico"],
    ["Fish Tacos (2pc)", 13, "Baja crema, cabbage"],
    ["Nachos Grande", 13, "Cheese, jalapeño, sour cream"],
    ["Churros (4pc)", 7, "Cinnamon sugar, chocolate"],
  ],
  Vegan: [
    ["Buddha Bowl", 13, "Quinoa, kale, tahini"],
    ["Cauliflower Tacos (3pc)", 12, "Salsa verde, cashew cream"],
    ["Chickpea Curry", 13, "Coconut, basmati rice"],
    ["Lentil Soup", 8, "Hearty, lemon-finished"],
    ["Veggie Sushi (8pc)", 11, "Avocado, cucumber, carrot"],
    ["Mushroom Risotto", 14, "Arborio, white wine"],
    ["Kale Caesar", 11, "Tempeh croutons"],
    ["Chocolate Avocado Mousse", 7, "Cacao, maple"],
  ],
  Indian: [
    ["Butter Chicken", 14, "Tomato, cream, basmati"],
    ["Chana Masala", 12, "Chickpeas, garam masala"],
    ["Lamb Vindaloo", 15, "Spicy, with potato"],
    ["Paneer Tikka", 13, "Tandoori-spiced cheese"],
    ["Vegetable Biryani", 12, "Aromatic basmati"],
    ["Naan", 4, "Brick-oven baked"],
    ["Garlic Naan", 5, "Fresh garlic, butter"],
    ["Mango Lassi", 5, "Yogurt smoothie"],
  ],
  Thai: [
    ["Pad Thai", 13, "Rice noodles, peanuts, lime"],
    ["Green Curry", 14, "Coconut, basil, chili"],
    ["Massaman Beef", 15, "Slow-cooked, peanut sauce"],
    ["Tom Yum Soup", 9, "Lemongrass, lime, chili"],
    ["Drunken Noodles", 13, "Wide rice noodles, basil"],
    ["Mango Sticky Rice", 8, "Coconut cream, fresh mango"],
    ["Thai Iced Tea", 4, "Sweet, creamy"],
    ["Spring Rolls (3pc)", 7, "Fresh herbs, peanut dip"],
  ],
};

export const restaurants = restaurantSeeds.map(([name, cuisine, rating, eta], i) => ({
  id: `rest-${String(i + 1).padStart(3, "0")}`,
  name,
  cuisine,
  rating,
  eta,
  deliveryFee: 3.99,
  hero: `https://images.unsplash.com/photo-${heroPhotos[i]}?w=800&q=80&auto=format`,
  thumb: `https://images.unsplash.com/photo-${heroPhotos[i]}?w=400&q=80&auto=format`,
  description: `${cuisine} restaurant. ${rating} stars · ~${eta} min.`,
  // Items: 12 per restaurant. 8 from the cuisine template + 4 picked from neighbors.
  items: (() => {
    const base = itemTemplatesByCuisine[cuisine].map(([n, p, d], j) => ({
      id: `rest-${String(i + 1).padStart(3, "0")}-item-${j + 1}`,
      name: n,
      price: p,
      description: d,
      photo: `https://picsum.photos/seed/${name.replace(/\s+/g, "")}${j}/400/300`,
    }));
    // Pad to 12 with cross-cuisine items.
    const cross = Object.values(itemTemplatesByCuisine)
      .flat()
      .filter((_, k) => k % 11 === (i % 11))
      .slice(0, 4)
      .map(([n, p, d], j) => ({
        id: `rest-${String(i + 1).padStart(3, "0")}-extra-${j + 1}`,
        name: n,
        price: p,
        description: d,
        photo: `https://picsum.photos/seed/${name.replace(/\s+/g, "")}x${j}/400/300`,
      }));
    return [...base, ...cross].slice(0, 12);
  })(),
}));

export { cuisines };
