// ── prompt-phrasing pins (models skip passively/negatively framed rules) ──
const assert = require('assert');
const { BASEMEM_RULES_CORE, BASEMEM_RULES_TIER1, INJECTED_TAIL } = require('../rules.js');
const { PLACEHOLDER } = require('../../../src/hooks/lib/output.js');
const { TRACKER_NUDGE } = require('../../../src/hooks/lib/tracker.js');

// output.js replaces this exact sentence with live context — drift silently
// breaks the SessionStart merge, so pin them equal.
assert.strictEqual(PLACEHOLDER, INJECTED_TAIL, 'output.js PLACEHOLDER must equal rules.js INJECTED_TAIL');
console.log('PASS rules/output placeholder pinned');

// The injected-context claim must read as already-satisfied state ("live context
// is below"), never as a bare "Memory context injected" with no visible context —
// otherwise the model treats memory as done and never calls tools.
assert.ok(BASEMEM_RULES_CORE.includes('live context is below'), 'core must ground the injected claim in visible context');
assert.ok(BASEMEM_RULES_TIER1.includes('Call code_find FIRST'), 'tier1 must name code_find as the first action');
assert.ok(BASEMEM_RULES_TIER1.includes('Call logInteraction'), 'tier1 must command logInteraction, not just mention it');
assert.ok(!BASEMEM_RULES_TIER1.includes('Then answer directly'), 'tier1 must not contain the tier2/3 answer-directly escape hatch');
console.log('PASS rules phrasing: positive triggers, no escape hatch in tier1');

// Tracker nudge must lead with an action trigger, not a passive status line.
assert.ok(TRACKER_NUDGE.startsWith('[BaseMem] Before answering'), 'nudge must lead with action trigger');
assert.ok(TRACKER_NUDGE.includes('code_find'), 'nudge must name code_find');
assert.ok(TRACKER_NUDGE.includes('code_read'), 'nudge must name code_read');
assert.ok(TRACKER_NUDGE.includes('logInteraction'), 'nudge must name logInteraction');
console.log('PASS tracker nudge phrasing');
