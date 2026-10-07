export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['The Verge', 'Wirecutter', 'RTINGS', 'Hacker News', 'Linus Tech Tips'],
    features: [
      { icon: 'keyboard', title: 'Hot-swappable switches', description: 'Swap Cherry, Gateron, or Kailh switches in seconds — no soldering, no tools, no warranty void.' },
      { icon: 'volume-2', title: 'Tuned for sound', description: 'Foam-dampened tray, PE film mod, and silicone bottom plate deliver a deep, marbly thock out of the box.' },
      { icon: 'palette', title: 'Per-key RGB', description: '16.8 million colors, 22 onboard effects, and a web configurator that actually saves to firmware.' },
      { icon: 'battery-charging', title: '4-month battery', description: 'Tri-mode connectivity over USB-C, 2.4GHz, or Bluetooth 5.3 — pair up to three devices and switch instantly.' },
      { icon: 'shield-check', title: 'Aircraft-grade aluminum', description: 'CNC-milled 6063 aluminum case with a gasket-mounted PCB for a soft, forgiving typing feel.' },
      { icon: 'cpu', title: 'QMK + VIA ready', description: 'Remap every key, build macros, and flash custom layers. Your keyboard, your rules — no cloud account required.' }
    ],
    steps: [
      { title: 'Pick your layout', description: 'Choose 65%, 75%, TKL, or full-size. Each layout ships in three colorways and two switch profiles.' },
      { title: 'Choose your switches', description: 'Linear, tactile, or clicky — sample any of our 14 stocked switches with a free $5 switch tester.' },
      { title: 'Type happily ever after', description: 'Plug it in, install VIA, and start typing. Free returns for 30 days if it isn\'t the one.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Software engineer, Northwind', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'I have owned six mechanical keyboards. This is the first one I haven\'t immediately wanted to mod. The stock sound is unreal.' },
      { name: 'Jordan Lee', role: 'Streamer & writer, Globex', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'The gasket mount is genuinely softer than my GMMK Pro and it costs less. Battery on Bluetooth lasted me almost the full quarter.' },
      { name: 'Sara Chen', role: 'Mechanical engineer, Loftwork', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'Hot-swap that actually clicks home, doubleshot PBT that doesn\'t shine after six months, and VIA support out of the box. Sold.' }
    ],
    plans: [
      {
        name: 'Klakk 65', price: '$129', cadence: 'one-time', cta: 'Add to cart', featured: false,
        description: 'Compact 65% layout for desks that mean business.',
        features: ['67 keys, hot-swappable', 'Gasket-mounted PCB', 'Doubleshot PBT keycaps', 'USB-C wired', 'VIA + QMK firmware']
      },
      {
        name: 'Klakk 75 Pro', price: '$189', cadence: 'one-time', cta: 'Add to cart', featured: true,
        description: 'Our best-seller. Knob, screen, wireless, the works.',
        features: ['81 keys + rotary knob', 'Tri-mode wireless (BT/2.4G/USB)', 'Per-key RGB + south-facing LEDs', '1.14" customizable TFT screen', 'Aluminum case, 1.9 kg']
      },
      {
        name: 'Klakk TKL', price: '$229', cadence: 'one-time', cta: 'Add to cart', featured: false,
        description: 'Tenkeyless for writers, coders, and pixel pushers.',
        features: ['87 keys, screw-in stabs', 'Brass weight, 2.3 kg total', 'PC plate + FR4 PCB', 'Bluetooth 5.3, 6000 mAh battery', 'Free engraved badge']
      }
    ],
    faqs: [
      { q: 'Is the keyboard hot-swappable?', a: 'Yes. Every Klakk keyboard uses 5-pin Kailh hot-swap sockets, so you can change switches without ever touching a soldering iron. Both 3-pin and 5-pin switches are supported.' },
      { q: 'Which switches come pre-installed?', a: 'You choose at checkout. We stock Gateron Oil Kings (linear), Kailh Box Jades (clicky), and Akko V3 Cream Yellows (tactile) — all lubed and filmed in-house at no extra cost.' },
      { q: 'Does it work on Mac and Windows?', a: 'Both. A physical toggle on the back flips between Mac and Windows layouts, and the Mod and Option/Alt keycaps are included in the box so the legends always match.' },
      { q: 'How long does shipping take?', a: 'In-stock orders ship from our Austin warehouse within 24 hours and arrive in 2–5 business days within the US. International orders typically arrive in 7–12 business days, DDP available at checkout.' },
      { q: 'What if I don\'t like it?', a: 'Type on it for 30 days. If it isn\'t the keyboard for you, send it back for a full refund — no restocking fees, no awkward questions. We even cover the return label.' },
      { q: 'Do you sell extra keycaps and switches?', a: 'We carry over 40 keycap sets and 14 switch types in our accessories shop. All keycap sets are MX-compatible and ship with the novelty keys you actually need.' },
      { q: 'Is firmware open source?', a: 'Yes. Every Klakk board runs QMK with VIA support and the source for each layout is on our GitHub. Build your own firmware or import community layouts in one click.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
