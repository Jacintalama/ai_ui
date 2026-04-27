import { portfolio } from '../src/components/Portfolio.js';

const p = portfolio();

let passed = true;

if (p.name !== 'Ralph Thunder') {
  console.error(`FAIL: expected name "Ralph Thunder", got "${p.name}"`);
  passed = false;
}

if (p.initials !== 'RT') {
  console.error(`FAIL: expected initials "RT", got "${p.initials}"`);
  passed = false;
}

if (passed) {
  console.log('PASS: name is "Ralph Thunder" and initials are "RT"');
} else {
  process.exit(1);
}
