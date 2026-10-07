export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Heritage Homes', 'Oakridge Builders', 'Modern Living Co.', 'BrightSpace Architects', 'StoneGate Developments'],
    features: [
      { icon: 'door-open', title: 'Solid hardwood craftsmanship', description: 'Every door is built from kiln-dried oak, walnut, or mahogany — joined, sanded, and finished by hand in our Ohio workshop.' },
      { icon: 'ruler', title: 'Made to your exact size', description: 'Standard sizes ship in 48 hours. Custom dimensions, panel counts, and glass cutouts arrive within 3 weeks.' },
      { icon: 'shield-check', title: 'Lifetime structural warranty', description: 'Warp, split, or delaminate within the lifetime of the original owner and we replace it — no questions, no fine print.' },
      { icon: 'palette', title: '120+ finishes & stains', description: 'From matte charcoal to natural white oak. Order swatches free, or send us a paint chip and we will match it.' },
      { icon: 'truck', title: 'White-glove delivery', description: 'Two-person delivery teams uncrate, inspect, and place your door inside the room of your choice. Old door haul-away included.' },
      { icon: 'wrench', title: 'Professional installation', description: 'Vetted, insured installers in 38 states. Most installs finish in under three hours, frame and hardware included.' }
    ],
    steps: [
      { title: 'Browse or design your door', description: 'Pick from 80 in-stock styles or use our 3D configurator to design panel layout, glass inserts, and hardware in real time.' },
      { title: 'Get an instant quote', description: 'Enter dimensions and finish. Pricing — including delivery and optional install — appears in seconds. No quote calls, no waiting.' },
      { title: 'Delivered & installed', description: 'Choose a delivery window that suits you. Our crew handles the heavy lifting and tunes the swing so it closes with a whisper.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Homeowner, Columbus OH', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'I replaced every interior door in our 1920s craftsman. The shaker panels are flawless and the installers respected our floors like surgeons.' },
      { name: 'Jordan Lee', role: 'General Contractor, Globex Build', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'We spec their solid-core doors on every renovation now. Lead times are honest, the hinges line up the first time, and clients keep thanking us.' },
      { name: 'Sara Chen', role: 'Interior Designer, Loftwork Studio', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'The custom arched walnut door for our client’s entryway turned into the centerpiece of the whole house. Stain match was perfect.' }
    ],
    plans: [
      {
        name: 'Interior', price: 'from $389', cadence: '/door', cta: 'Shop interior', featured: false,
        description: 'Solid-core interior doors for bedrooms, offices, and pantries.',
        features: ['Pre-hung or slab', '6 panel styles', '24 stock finishes', 'Ships in 48 hours', 'Free swatches']
      },
      {
        name: 'Entry', price: 'from $1,290', cadence: '/door', cta: 'Build my entry door', featured: true,
        description: 'Insulated solid hardwood entry doors built for curb appeal and security.',
        features: ['R-value 5.6 insulated core', 'Multi-point deadbolt ready', 'Optional sidelights & transom', 'Glass insert library', 'Weather-sealed for 25+ years']
      },
      {
        name: 'Custom', price: 'Quote', cadence: 'in 24 hours', cta: 'Start a custom build', featured: false,
        description: 'Bespoke barn, pivot, arched, and oversized doors for design-led projects.',
        features: ['Pivot & barn hardware', 'Up to 60" wide × 10\' tall', 'Reclaimed wood available', 'Hand-carved details', 'Dedicated project manager']
      }
    ],
    faqs: [
      { q: 'What is the lead time on a custom door?', a: 'Stock interior doors ship within 48 hours. Configured doors (custom size, finish, or glass) ship in 2-3 weeks. Fully bespoke entry and pivot doors run 4-6 weeks depending on hardware and finish.' },
      { q: 'Do you install, or just deliver?', a: 'Both. Delivery is included on every order over $500. Professional installation is optional and available in 38 states starting at $249 per door, including haul-away of the old door.' },
      { q: 'Can I see samples before I commit?', a: 'Yes — we ship a free swatch pack of up to 5 stains and 3 wood species anywhere in the continental US. Order through any product page or call the studio.' },
      { q: 'What is the warranty?', a: 'Lifetime structural warranty against warping, splitting, or joinery failure for the original owner. Finishes carry a 10-year warranty against fading and peeling under normal use.' },
      { q: 'Do you offer financing?', a: 'Yes. We partner with Affirm for 6, 12, and 24-month plans. Most homeowners qualify in under a minute at checkout with no impact to their credit score.' },
      { q: 'Will a new entry door really improve energy efficiency?', a: 'Our insulated entry doors carry an R-value of 5.6, roughly 4x a hollow builder-grade door. Most customers report noticeably warmer foyers and a measurable drop in HVAC cycling within the first winter.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
