import { portfolio } from '../src/components/Portfolio.js';

const p = portfolio();

let passed = true;

if (p.name !== 'Ralph Benítez') {
  console.error(`FAIL: expected name "Ralph Benítez", got "${p.name}"`);
  passed = false;
}

if (p.initials !== 'RB') {
  console.error(`FAIL: expected initials "RB", got "${p.initials}"`);
  passed = false;
}

if (passed) {
  console.log('PASS: name is "Ralph Benítez" and initials are "RB"');
} else {
  process.exit(1);
}
