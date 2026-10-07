import { promoPlayer } from './components/PromoPlayer.js';
import { featureGrid } from './components/FeatureGrid.js';
import { steps } from './components/Steps.js';
import { pricing } from './components/Pricing.js';
import { faq } from './components/Faq.js';
import { waitlist } from './components/Waitlist.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.store('waitlist', { count: 0, message: '' });
  window.Alpine.data('promoPlayer', promoPlayer);
  window.Alpine.data('featureGrid', featureGrid);
  window.Alpine.data('steps', steps);
  window.Alpine.data('pricing', pricing);
  window.Alpine.data('faq', faq);
  window.Alpine.data('waitlist', waitlist);
});
