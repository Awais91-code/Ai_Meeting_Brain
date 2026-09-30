const assert = require('node:assert/strict');
const {richText, summarySections} = require('../app/static/js/presentation.js');

const sample = `**Meeting Summary: Product Launch Finalization**

**Main Topics Discussed**
* Product launch schedule confirmation
* Budget approval

**Important Decisions**
* Product launch date set for **Friday**.
* Approved budget confirmed at **$50,000**.

**Important Deadlines**
* **Wednesday:** Marketing campaign begins.
* **Friday:** Product launch (Engineering Team).

**Important Responsibilities**
* **Engineering Team:** Execute product launch on Friday.`;
const sections = summarySections(sample);
assert.deepEqual(sections.map(s=>s.title), ['Discussion','Decisions','Dates & deadlines','Responsibilities']);
assert.equal(sections[1].items.length, 2);
assert.ok(richText(sections[1].items[1]).includes('<strong>$50,000</strong>'));
assert.ok(!richText(sections[1].items[1]).includes('**'));
assert.equal(summarySections('Overview\nWe approved the launch.\n\nDecisions\n- Launch Friday.')[1].title, 'Decisions');
assert.equal(summarySections('')[0], undefined);
const untrusted = '<img src=x onerror=alert(1)> **budget** <script>alert(1)</script>';
assert.ok(!richText(untrusted).includes('<img'));
assert.ok(!richText(untrusted).includes('<script'));
assert.ok(richText(untrusted).includes('&lt;script&gt;'));
assert.ok(richText('Budget: $1,000. [Source 1]').includes('class="citation"'));
assert.ok(!richText('[click](javascript:alert(1))').includes('href'));
assert.equal((richText('- One\n- Two\n\nDone.').match(/<ul>/g)||[]).length,1);
console.log('PASS: legacy summary sections, Markdown formatting, citations, and HTML injection safety');
