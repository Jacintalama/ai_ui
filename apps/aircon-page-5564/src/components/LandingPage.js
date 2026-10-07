export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Daikin Certified', 'Mitsubishi Pro', 'LG Partner', 'Trustpilot 4.9★', 'NATE Certified'],
    features: [
      { icon: 'snowflake', title: 'Same-day installation', description: 'Book before noon and our techs can have a new split system cooling your home by dinner — most jobs done in under 4 hours.' },
      { icon: 'wrench', title: 'Tune-ups & repairs', description: 'From refrigerant top-ups to compressor swaps, our NATE-certified team services every major brand with a 12-month workmanship warranty.' },
      { icon: 'leaf', title: 'Energy-efficient units', description: 'We only fit inverter systems rated 5-star or higher, cutting average summer power bills by 30–45% versus older ducted setups.' },
      { icon: 'shield-check', title: 'Lifetime support', description: 'Every install includes free annual filter checks and a 24/7 priority hotline for the lifetime of the unit.' },
      { icon: 'badge-dollar-sign', title: 'Upfront fixed pricing', description: 'No hourly surprises. You see the exact total — supply, install, and disposal of the old unit — before we lift a tool.' },
      { icon: 'clock', title: '24/7 emergency service', description: 'Aircon down in a 38°C heatwave? A licensed technician is dispatched within 90 minutes anywhere in the metro area.' }
    ],
    steps: [
      { title: 'Free in-home quote', description: 'A senior estimator measures your space, checks insulation and existing ductwork, and emails a fixed-price quote within 24 hours.' },
      { title: 'We handle the paperwork', description: 'Permits, rebates, and manufacturer registration — we file everything so you pocket the state energy rebate without lifting a finger.' },
      { title: 'Install, test, and relax', description: 'Our two-person crew installs, vacuum-tests, commissions the unit, walks you through the remote, and hauls away the old gear.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Homeowner, Brunswick', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'Quoted Tuesday, installed Thursday. The crew was tidier than my cleaner and the new Daikin is whisper-quiet — best $3.2k I’ve spent on this house.' },
      { name: 'Jordan Lee', role: 'Café Owner, Fitzroy', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'They replaced our 16-year-old commercial unit on a Sunday so we didn’t lose a trading day. Power bill is already down 38% in the first month.' },
      { name: 'Sara Chen', role: 'Property Manager, Carlton', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'I manage 40 rentals and these are the only HVAC team I trust with tenant call-outs. Fast, fair, and they actually answer the phone after hours.' }
    ],
    plans: [
      {
        name: 'Service Call', price: '$129', cadence: 'flat fee', cta: 'Book a tech', featured: false,
        description: 'Diagnosis and minor repairs for any brand.',
        features: ['Same-week booking', 'Up to 1 hour on-site', 'Refrigerant top-up included', 'Written fault report', '30-day repair guarantee']
      },
      {
        name: 'Split System Install', price: 'from $2,490', cadence: 'fully fitted', cta: 'Get my quote', featured: true,
        description: 'Most popular — 5kW inverter, supplied & installed.',
        features: ['Daikin, Mitsubishi or LG', 'Up to 5m pipe run included', 'Old unit removal & disposal', '5-year parts + labour warranty', 'Government rebate filed for you']
      },
      {
        name: 'Annual Care Plan', price: '$249', cadence: '/ year', cta: 'Start cover', featured: false,
        description: 'Set-and-forget maintenance for one unit.',
        features: ['2 scheduled tune-ups', 'Filter & coil clean', 'Priority emergency call-out', '15% off any repairs', 'Transferable if you move']
      }
    ],
    faqs: [
      { q: 'How quickly can you install a new system?', a: 'Standard back-to-back split systems are usually fitted within 48 hours of accepting your quote. Ducted or multi-head systems take 5–10 business days depending on supplier stock.' },
      { q: 'Do you service all brands or only the ones you sell?', a: 'We service every major brand including Daikin, Mitsubishi Electric, Mitsubishi Heavy, Fujitsu, LG, Panasonic, Samsung, Hitachi, and Kelvinator — even if we didn’t install it.' },
      { q: 'What warranty comes with a new install?', a: 'You get the full manufacturer warranty (typically 5 years parts) plus our own 5-year workmanship warranty. We register the unit on your behalf so the clock starts the day it’s commissioned.' },
      { q: 'Are you licensed and insured?', a: 'Yes. We hold an ARC refrigerant handling licence (AU12345), a full electrical contractor licence, and $20m public liability insurance. Certificates are provided with every quote.' },
      { q: 'Can I claim a government rebate?', a: 'Most homeowners qualify for the Victorian Energy Upgrades rebate when replacing an older system with a 5-star inverter. We calculate the exact rebate amount in your quote and apply it as an instant discount.' },
      { q: 'Do you offer finance or payment plans?', a: 'Yes — interest-free finance up to $5,000 over 24 months via Humm, and longer terms via Brighte for solar-paired systems. Approvals usually take under 10 minutes.' },
      { q: 'What if my aircon breaks down on a weekend?', a: 'Our emergency line is staffed 24/7 including public holidays. A licensed tech is dispatched within 90 minutes inside the metro area; after-hours call-out fee is $189.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
