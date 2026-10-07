export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Foodie Weekly', 'Eater', 'Time Out', 'Bon Appétit', 'The Infatuation'],
    features: [
      { icon: 'flame', title: 'Hand-breaded, twice fried', description: 'Buttermilk-brined 24 hours, then double-fried for the crackliest crust you have ever heard.' },
      { icon: 'leaf', title: 'Locally raised birds', description: 'Free-range chickens from family farms within 80 miles — never frozen, antibiotic free.' },
      { icon: 'clock', title: 'Lunch in under 8 minutes', description: 'Order ahead from the app and skip the line. Your bucket is hot and ready when you arrive.' },
      { icon: 'utensils', title: 'Made-from-scratch sides', description: 'Buttermilk biscuits, mac & cheese, slaw, and gravy — all made in-house every single morning.' },
      { icon: 'truck', title: 'Free delivery over $25', description: 'Hot chicken delivered in our insulated boxes that keep crunch crunchy for up to 30 minutes.' },
      { icon: 'sparkles', title: 'Joy Rewards', description: 'Every $1 earns a feather. Ten feathers gets you a free 3-piece combo. Birthdays come with cake.' }
    ],
    steps: [
      { title: 'Pick your pieces', description: 'Choose Original, Spicy, or Honey Butter. Solo meal, family bucket, or party platter — we sized them all.' },
      { title: 'Add the joy', description: 'Pair with biscuits, mac, slaw, and a dipping sauce flight. Vegetarian? Try the crispy cauliflower.' },
      { title: 'Eat, smile, repeat', description: 'Dine in, take out, or get it delivered. Hot, crisp, and ready in about the time it takes to wash your hands.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Food writer, Foodie Weekly', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'The crust shatters like glass and the meat is somehow even juicier than the bite before. Chicken Joy is the new standard.' },
      { name: 'Jordan Lee', role: 'Regular since opening day', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'I have tried every chicken spot in three cities. Nothing else makes me drive 20 minutes out of my way on a Tuesday.' },
      { name: 'Sara Chen', role: 'Mom of three', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'A family bucket and a stack of biscuits ends every argument in my house. The kids ask for it by name now.' }
    ],
    plans: [
      {
        name: 'Solo Joy', price: '$11', cadence: 'meal', cta: 'Order solo', featured: false,
        description: 'A perfect lunch for one happy human.',
        features: ['2 pieces, your choice', '1 biscuit', '1 side', '1 dipping sauce', 'Free drink refill (dine in)']
      },
      {
        name: 'Family Bucket', price: '$32', cadence: 'feeds 4', cta: 'Get the bucket', featured: true,
        description: 'Our most-ordered combo for a reason.',
        features: ['12 pieces, mixed', '6 buttermilk biscuits', '2 large sides', '4 dipping sauces', 'Free cookie pack']
      },
      {
        name: 'Party Platter', price: '$78', cadence: 'feeds 10–12', cta: 'Plan a party', featured: false,
        description: 'For game day, office lunch, or block parties.',
        features: ['24 pieces, mixed', '12 biscuits', '4 large sides', 'Sauce flight (8 cups)', 'Disposable plates + napkins']
      }
    ],
    faqs: [
      { q: 'What makes Chicken Joy different from other chicken spots?', a: 'Three things: a 24-hour buttermilk brine that seasons the meat all the way through, a double-fry method that locks in juice, and a from-scratch kitchen that bakes every biscuit and stirs every gravy in-house.' },
      { q: 'Do you have spicy options?', a: 'Yes. Our Nashville-style Hot dredge comes in three heat levels: Warm Welcome, Real Heat, and "Are You Sure". Honey Butter is a sweet alternative for the heat-averse.' },
      { q: 'Are there options for vegetarians?', a: 'Absolutely. Our crispy cauliflower uses the same brine and dredge as the chicken, plus mushroom "wings" and a fried green tomato sandwich. All sides except mac & cheese are vegetarian.' },
      { q: 'Can I order ahead or get delivery?', a: 'Yes — order through our app for pickup in 8 minutes, or get free delivery on orders over $25 within a 4-mile radius. We also list on the major delivery apps.' },
      { q: 'Do you cater parties or events?', a: 'We cater anything from a 10-person office lunch to a 300-guest wedding. Book at least 48 hours ahead through the catering page and we will handle plates, napkins, and setup.' },
      { q: 'Where are you located?', a: 'Our flagship is at 412 Maple Avenue, with a second location in Riverside opening this fall. Hours: 11am–10pm daily, kitchen closes 30 minutes before close.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
