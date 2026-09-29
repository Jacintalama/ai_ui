export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Food & Wine', 'Bon Appétit', 'TimeOut', 'Eater', 'The Infatuation'],
    features: [
      { icon: 'leaf', title: 'Farm-fresh dairy', description: 'Whole milk and cream from a single family farm in the Hudson Valley, delivered to our churn the morning after milking.' },
      { icon: 'flame', title: 'Slow-cooked custard base', description: 'Every flavor starts with a 24-hour aged French custard — silkier mouthfeel, less ice, more flavor in every spoonful.' },
      { icon: 'sparkles', title: 'Small-batch flavors', description: 'We churn forty pints at a time. Limited drops every Friday and seasonal flavors you will not find anywhere else.' },
      { icon: 'leaf', title: 'Real ingredients only', description: 'No gums, no stabilizers, no artificial colors. If it is not in your pantry, it is not in our pint.' },
      { icon: 'truck', title: 'Free local delivery', description: 'Insulated dry-ice shipping across the five boroughs and same-day delivery in Brooklyn for orders before noon.' },
      { icon: 'heart', title: 'Vegan & DF options', description: 'Eight oat-milk and coconut-cream flavors so good you will not believe they are dairy free. Pinky promise.' }
    ],
    steps: [
      { title: 'Pick your pints', description: 'Choose four, six, or eight pints from twenty-plus rotating flavors. Mix classics with this week’s limited drop.' },
      { title: 'We pack on dry ice', description: 'Hand-packed in compostable insulation the morning of your delivery — arrives frozen solid, every time.' },
      { title: 'Scoop, share, repeat', description: 'Doorstep delivery in NYC or overnight nationwide. Subscribe and save 15% on a monthly pint club.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Brooklyn, NY', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'The brown butter pecan is genuinely the best ice cream I have ever eaten — and I grew up two blocks from Ample Hills.' },
      { name: 'Jordan Lee', role: 'Subscriber since 2023', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'The Friday flavor drops are my favorite part of the week. Strawberry basil sorbet ruined every other sorbet for me.' },
      { name: 'Sara Chen', role: 'Pastry chef, Loftwork Bakery', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'I serve their vanilla bean alongside my tarts. Customers ask whose ice cream it is every single service.' }
    ],
    plans: [
      {
        name: 'Single Scoop', price: '$24', cadence: '/4 pints', cta: 'Order now', featured: false,
        description: 'A taste of the creamery. Perfect for a quiet weekend in.',
        features: ['4 pints, your choice', 'One-time order', 'Local NYC delivery', 'Free with $40+ orders']
      },
      {
        name: 'Pint Club', price: '$54', cadence: '/month', cta: 'Start subscription', featured: true,
        description: 'Six pints a month, including the new Friday drop.',
        features: ['6 pints monthly', 'First access to limited flavors', 'Skip or pause any month', '15% subscriber discount', 'Free shipping nationwide']
      },
      {
        name: 'Family Freezer', price: '$98', cadence: '/month', cta: 'Stock the freezer', featured: false,
        description: 'Twelve pints for the household that takes dessert seriously.',
        features: ['12 pints monthly', 'Choose-your-own flavors', 'Includes kids’ classics box', 'Dedicated concierge', 'Surprise tasting pint each drop']
      }
    ],
    faqs: [
      { q: 'How is the ice cream shipped?', a: 'Every order is hand-packed in compostable wool insulation with food-grade dry ice and shipped overnight via FedEx Priority. Local NYC orders go out on our refrigerated vans the same day.' },
      { q: 'What if a pint melts in transit?', a: 'It will not — but if it does, send us a photo and we will replace the entire order, no questions asked. We have a 100% Frozen Guarantee.' },
      { q: 'Are your flavors gluten-free?', a: 'About 70% of our flavors are gluten-free. We label every pint clearly and run a dedicated GF production day each week to avoid cross-contact.' },
      { q: 'Can I gift a subscription?', a: 'Yes. Gift Pint Club for 3, 6, or 12 months. We will email the recipient a hand-illustrated card on the date you choose, no shipping address needed at checkout.' },
      { q: 'Where does the dairy come from?', a: 'Every drop of cream comes from Ronnybrook Farm in Pine Plains, NY — a fourth-generation family dairy with grass-fed Holsteins. We have visited the cows. They are very content.' },
      { q: 'How do I skip a month?', a: 'Log in any time before the 25th to skip, pause, swap flavors, or cancel. No phone calls, no retention emails — your freezer, your rules.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
