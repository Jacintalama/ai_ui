export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['The Bark Post', 'Dogster', 'Modern Dog', 'Rover Reviews', 'Puppy Today'],
    features: [
      { icon: 'leaf', title: 'Real, whole ingredients', description: 'Cage-free chicken, wild-caught salmon, sweet potato, and leafy greens — never meat by-products or mystery meals.' },
      { icon: 'flame', title: 'Gently cooked, never fried', description: 'Slow-cooked at low temperatures to lock in nutrients and the rich flavor dogs actually beg for at mealtime.' },
      { icon: 'heart-pulse', title: 'Vet-formulated recipes', description: 'Every recipe is balanced by board-certified veterinary nutritionists and meets AAFCO standards for all life stages.' },
      { icon: 'truck', title: 'Free delivery to your door', description: 'Pre-portioned packs arrive on your schedule. Skip, pause, or change recipes any time from your account.' },
      { icon: 'shield-check', title: 'Picky-eater guarantee', description: 'If your dog turns up their nose at their first box, we refund every cent — no questions, no fine print.' },
      { icon: 'sparkles', title: 'Personalized for your pup', description: 'Take our 2-minute quiz and we tailor portions to your dog’s age, weight, breed, and activity level.' }
    ],
    steps: [
      { title: 'Tell us about your dog', description: 'Answer a few quick questions about Bella or Max — breed, weight, age, allergies, and how active they are day to day.' },
      { title: 'Get a custom meal plan', description: 'Our nutritionists build a portion-controlled plan with the right calories, protein, and fats for your specific dog.' },
      { title: 'Fresh food arrives weekly', description: 'Vacuum-sealed packs ship in an insulated, recyclable box. Just open, serve, and watch the tail wags.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Mom to Biscuit, 4yr Golden', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'Biscuit’s coat is shinier, his energy is back, and his vet asked what we changed. Worth every penny.' },
      { name: 'Jordan Lee', role: 'Dad to Olive, 7yr Beagle', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'Olive was a picky eater for years. She now sprints to the bowl. The portion sizing alone saved us guesswork.' },
      { name: 'Sara Chen', role: 'Mom to Mochi, 2yr Frenchie', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'Mochi’s sensitive stomach issues cleared up within three weeks. No more 3am vet panics — total game changer.' }
    ],
    plans: [
      {
        name: 'Starter', price: '$3', cadence: '/day', cta: 'Build my plan', featured: false,
        description: 'For small dogs under 25 lbs.',
        features: ['Custom portions', 'Free weekly delivery', '1 recipe per box', 'Skip or pause anytime']
      },
      {
        name: 'Full Bowl', price: '$5', cadence: '/day', cta: 'Start 50% off trial', featured: true,
        description: 'For medium dogs, 25–60 lbs.',
        features: ['Custom portions', 'Free weekly delivery', '2 rotating recipes', 'Nutritionist chat support', 'First box 50% off']
      },
      {
        name: 'Big Dog', price: '$8', cadence: '/day', cta: 'Build my plan', featured: false,
        description: 'For large breeds over 60 lbs.',
        features: ['Custom portions', 'Free weekly delivery', 'All 4 recipes', 'Priority support', 'Joint-support topper included']
      }
    ],
    faqs: [
      { q: 'Is fresh dog food really better than kibble?', a: 'Lightly cooked whole-ingredient meals retain more vitamins, moisture, and natural protein than dry kibble that’s been extruded at 400°F. Most dogs digest fresh food more easily, which often shows up as smaller, firmer stools and a shinier coat.' },
      { q: 'How do I transition my dog from their old food?', a: 'We recommend a 7-day transition: start with 25% Pawfect and 75% old food for two days, then 50/50, then 75/25, then 100%. Every order includes a free transition guide.' },
      { q: 'How long does the food stay fresh?', a: 'Unopened packs keep for up to 7 days in the fridge and 6 months in the freezer. Each pack is pre-portioned for one meal so there are no leftovers to worry about.' },
      { q: 'What if my dog has allergies?', a: 'Our quiz screens for the most common allergens (chicken, beef, grain, dairy) and we offer single-protein recipes — turkey, lamb, and salmon — formulated for sensitive stomachs.' },
      { q: 'Can I pause or cancel my subscription?', a: 'Yes, anytime, with no fees. Manage everything from your account dashboard: skip a week, change recipes, adjust portions, or pause indefinitely.' },
      { q: 'Where do you source your ingredients?', a: 'All meat is sourced from USDA-inspected farms in the United States. Produce comes from regional growers. Nothing in our recipes is sourced from China.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
