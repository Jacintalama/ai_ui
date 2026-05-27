// src/data.js — Salt & Pan recipe catalog.
// Ingredients use { qty, unit, name } so quantities scale linearly with servings.

const photoIds = [
  "1565299624946-b28f40a0ae38", "1490645935967-10de6ba17061",
  "1565958011703-44f9829ba187", "1546069901-ba9599a7e63c",
  "1565557623262-b51c2513a641", "1551782450-a2132b4ba21d",
  "1567620905732-2d1ec7ab7445", "1551183053-bf91a1d81141",
  "1565299507177-b0ac66763828", "1540189549336-e6e99c3679fe",
  "1502301197179-65228ab57f78", "1572441710269-fda88a25dc46",
  "1543353071-873f17a7a088", "1490645935967-10de6ba17061",
  "1565958011703-44f9829ba187", "1546069901-ba9599a7e63c",
  "1565557623262-b51c2513a641", "1542010589-c5d49a40c69e",
  "1546069901-ba9599a7e63c", "1547592180-85f173990554",
  "1540189549336-e6e99c3679fe", "1502301197179-65228ab57f78",
  "1572441710269-fda88a25dc46", "1543353071-873f17a7a088",
  "1543339494-b4cd0e80c1c8", "1546069901-ba9599a7e63c",
  "1551782450-a2132b4ba21d", "1567620905732-2d1ec7ab7445",
  "1551183053-bf91a1d81141", "1565299507177-b0ac66763828",
];

const recipeSeeds = [
  ["Lemon Garlic Pasta", ["vegan"], "easy", 25, "A bright weeknight pasta with lemon and toasted garlic."],
  ["Cacio e Pepe", ["vegetarian"], "medium", 20, "Three ingredients, all about technique."],
  ["Mushroom Risotto", ["vegetarian", "gluten-free"], "medium", 45, "Wild mushrooms, white wine, parmesan."],
  ["Chickpea Curry", ["vegan", "gluten-free"], "easy", 30, "Coconut, garam masala, basmati rice."],
  ["Roasted Tomato Soup", ["vegan", "gluten-free"], "easy", 40, "Slow-roasted tomatoes blended smooth."],
  ["Bibimbap Bowl", ["vegetarian"], "medium", 45, "Korean rice bowl with sautéed veg and egg."],
  ["Lentil Bolognese", ["vegan"], "medium", 35, "Hearty plant-based ragu."],
  ["Cauliflower Tacos", ["vegan"], "easy", 25, "Spiced cauliflower, salsa verde, cashew cream."],
  ["Greek Salad", ["vegetarian", "gluten-free"], "easy", 12, "Crisp vegetables, feta, olive oil."],
  ["Coconut Curry Soup", ["vegan", "gluten-free"], "easy", 25, "Thai-inspired, lime and ginger."],
  ["Caprese Skewers", ["vegetarian", "gluten-free"], "easy", 10, "Tomato, mozzarella, basil, balsamic."],
  ["Sweet Potato Hash", ["vegan", "gluten-free"], "easy", 30, "Breakfast hash with peppers and onions."],
  ["Beef & Broccoli", [], "medium", 30, "Classic stir-fry with garlic sauce."],
  ["Chicken Tikka Masala", ["gluten-free"], "medium", 45, "Marinated chicken in spiced tomato cream."],
  ["Salmon Teriyaki", ["gluten-free", "dairy-free"], "easy", 20, "Glazed salmon, jasmine rice, edamame."],
  ["Shakshuka", ["vegetarian", "gluten-free"], "easy", 25, "Eggs poached in spiced tomato."],
  ["Roasted Veg Bowl", ["vegan", "gluten-free"], "easy", 35, "Seasonal veg, tahini drizzle."],
  ["Carbonara", ["dairy-free"], "easy", 20, "Pancetta, egg, pecorino, pepper."],
  ["Spinach Lasagna", ["vegetarian"], "medium", 60, "Layered with bechamel and ricotta."],
  ["Pesto Gnocchi", ["vegetarian"], "easy", 15, "Fresh basil pesto, toasted pine nuts."],
  ["Crispy Tofu Bowl", ["vegan", "gluten-free"], "easy", 25, "Cornstarch-crisped tofu, sticky rice."],
  ["Chana Masala", ["vegan", "gluten-free"], "easy", 30, "Chickpeas, onion, ginger, garam masala."],
  ["Quinoa Buddha Bowl", ["vegan", "gluten-free"], "easy", 25, "Roasted veg, tahini, lemon."],
  ["Eggplant Parmesan", ["vegetarian"], "medium", 50, "Layered, baked, golden."],
  ["Banh Mi Bowl", ["dairy-free"], "easy", 30, "Pork, pickled veg, sriracha mayo."],
  ["Black Bean Tacos", ["vegan"], "easy", 15, "Smoky black beans, lime crema."],
  ["Tuscan Bean Soup", ["vegan", "gluten-free"], "easy", 35, "White beans, kale, rosemary."],
  ["Stuffed Bell Peppers", ["gluten-free"], "medium", 50, "Rice, beef, herbs, tomato."],
  ["Spring Rolls", ["vegan", "gluten-free"], "easy", 20, "Rice paper, herbs, peanut sauce."],
  ["Apple Crumble", ["vegetarian"], "easy", 45, "Cinnamon apples, buttery oat topping."],
];

// 8 steps for consistency across all recipes.
const stepTemplates = [
  "Prep ingredients: wash, chop, and measure everything before heating the stove.",
  "Heat oil in a large skillet or pot over medium-high heat until shimmering.",
  "Add aromatics (onion, garlic, ginger) and cook 2–3 minutes until fragrant.",
  "Add the main ingredient and stir to coat evenly with the aromatics.",
  "Pour in liquids (broth, sauce, or water) and bring to a gentle simmer.",
  "Cover and cook for 10–15 minutes, stirring occasionally to prevent sticking.",
  "Taste and adjust seasoning: salt, pepper, and a squeeze of lemon or splash of vinegar.",
  "Plate, garnish with fresh herbs, and serve immediately while hot.",
];

const ingredientTemplates = [
  { qty: 1,    unit: "lb",   name: "main protein or base (substitute as needed)" },
  { qty: 2,    unit: "tbsp", name: "olive oil" },
  { qty: 3,    unit: "clove", name: "garlic, minced" },
  { qty: 1,    unit: "cup",  name: "broth or stock" },
  { qty: 0.5,  unit: "tsp",  name: "salt" },
  { qty: 0.25, unit: "tsp",  name: "black pepper" },
  { qty: 1,    unit: "",     name: "lemon, juiced" },
  { qty: 2,    unit: "tbsp", name: "fresh herbs, chopped" },
];

export const recipes = recipeSeeds.map(([title, diet, difficulty, minutes, intro], i) => ({
  id: `rec-${String(i + 1).padStart(3, "0")}`,
  title, diet, difficulty, minutes, intro,
  hero:  `https://images.unsplash.com/photo-${photoIds[i] || photoIds[0]}?w=800&q=80&auto=format`,
  thumb: `https://images.unsplash.com/photo-${photoIds[i] || photoIds[0]}?w=400&q=80&auto=format`,
  baseServings: 2,
  ingredients: ingredientTemplates.map((ing, j) => ({
    ...ing,
    name: j === 0 ? title.toLowerCase().split(" ")[0] + " (main)" : ing.name,
  })),
  steps: stepTemplates,
}));
