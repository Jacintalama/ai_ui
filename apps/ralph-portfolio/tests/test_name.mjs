import { portfolio } from '../src/components/Portfolio.js';

const p = portfolio();

let passed = true;

if (p.name !== 'Ralph Benitez') {
  console.error(`FAIL: expected name "Ralph Benitez", got "${p.name}"`);
  passed = false;
}

if (p.initials !== 'RB') {
  console.error(`FAIL: expected initials "RB", got "${p.initials}"`);
  passed = false;
}

if (passed) {
  console.log('PASS: name is "Ralph Benitez" and initials are "RB"');
} else {
  process.exit(1);
}
