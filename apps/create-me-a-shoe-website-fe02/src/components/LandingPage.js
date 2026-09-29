export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Vogue', 'GQ', 'Hypebeast', 'Highsnobiety', 'Esquire', 'Complex'],
    features: [
      { icon: 'feather', title: 'Cloud-soft cushioning', description: 'Our proprietary AirFlex foam absorbs impact and springs back, mile after mile.' },
      { icon: 'leaf', title: 'Recycled materials', description: 'Uppers knit from 8 recycled plastic bottles. Soles made with 30% bio-based rubber.' },
      { icon: 'wind', title: 'Breathable knit upper', description: 'Engineered mesh keeps your feet cool from morning commute to evening run.' },
      { icon: 'shield-check', title: 'Built to last 800+ miles', description: 'Reinforced heel counter and abrasion-resistant outsole rated for two years of daily wear.' },
      { icon: 'droplets', title: 'Water-resistant finish', description: 'A DWR coating sheds light rain and puddles without trapping moisture inside.' },
      { icon: 'sparkles', title: 'Designed in Copenhagen', description: 'Clean Scandinavian silhouettes that pair with denim, suits, and everything between.' }
    ],
    steps: [
      { title: 'Find your fit', description: 'Take our 60-second sizing quiz. We account for arch height, width, and how you actually walk.' },
      { title: 'Pick your pair', description: 'Three silhouettes, twelve colorways. Free swatches mailed if you want to see them in person first.' },
      { title: 'Wear them in (or send them back)', description: 'Free shipping both ways. Try them for 30 days — if they are not perfect, we refund every cent.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Architect, Brooklyn', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'I walk 15,000 steps a day on job sites. These are the first sneakers that look sharp enough for client meetings and still feel great at 6pm.' },
      { name: 'Jordan Lee', role: 'Marathon runner, Austin', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'I put 600 miles on my pair before the tread even started to fade. The foam still feels like day one.' },
      { name: 'Sara Chen', role: 'Founder, Loftwork Studio', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'Bought one pair, ordered three more the next week. The recycled story is real — and they are genuinely the most comfortable shoes I own.' }
    ],
    plans: [
      {
        name: 'The Daily', price: '$120', cadence: 'per pair', cta: 'Shop The Daily', featured: false,
        description: 'Our everyday low-top. Goes with everything.',
        features: ['Knit recycled upper', 'AirFlex foam midsole', 'Rubber outsole', '8 colorways', 'Free shipping & returns']
      },
      {
        name: 'The Runner', price: '$145', cadence: 'per pair', cta: 'Shop The Runner', featured: true,
        description: 'Engineered for distance and daily commutes.',
        features: ['Extra-cushion AirFlex Pro foam', 'Reinforced heel counter', '800-mile durability rating', 'Reflective accents', '12 colorways', 'Free shipping & returns']
      },
      {
        name: 'The Trail', price: '$165', cadence: 'per pair', cta: 'Shop The Trail', featured: false,
        description: 'Grippy, water-resistant, weekend-ready.',
        features: ['Lugged Vibram-style outsole', 'DWR water-resistant upper', 'Padded ankle collar', '6 colorways', 'Free shipping & returns']
      }
    ],
    faqs: [
      { q: 'How do Nice shoes fit?', a: 'Most customers find them true to size. If you are between sizes, we recommend going up half a size — the knit upper softens slightly with wear.' },
      { q: 'What is your return policy?', a: 'You have 30 days to wear them anywhere — outside, inside, in the rain. If they are not right, send them back free of charge for a full refund.' },
      { q: 'Are they actually sustainable, or is it greenwashing?', a: 'Each pair uses 8 recycled plastic bottles in the upper and 30% bio-based rubber in the sole. We publish a full materials breakdown and our annual impact report on the site.' },
      { q: 'Can I machine wash them?', a: 'Yes. Remove the insoles and laces, use a cold gentle cycle inside a mesh bag, and air dry. They come out looking brand new.' },
      { q: 'Do you ship internationally?', a: 'We ship to 38 countries with free returns from anywhere in the US, UK, EU, Canada, and Australia. Other regions incur a flat $15 return fee.' },
      { q: 'How long until my order arrives?', a: 'Standard shipping is 2-4 business days in the US and 5-7 days internationally. Express options are available at checkout.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
