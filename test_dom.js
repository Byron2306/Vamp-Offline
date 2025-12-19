const fs = require('fs');
const { JSDOM } = require('jsdom');

// Load app.js and extract the three helper functions using regex
const appJs = fs.readFileSync('./app.js', 'utf8');

function extract(fnName) {
  const re = new RegExp(`function ${fnName}\\s*\\([\\s\\S]*?\\)\\s*\\{`);
  const start = appJs.search(re);
  if (start === -1) return null;
  // find matching braces from start of function
  let i = start;
  // find first '{'
  while (i < appJs.length && appJs[i] !== '{') i++;
  let depth = 0;
  let end = i;
  for (; end < appJs.length; end++) {
    if (appJs[end] === '{') depth++;
    else if (appJs[end] === '}') depth--;
    if (depth === 0) { end++; break; }
  }
  return appJs.slice(start, end);
}

const fnNames = ['rememberScanPanelHome','restoreScanPanelHome','attachScanPanelTo','clearTargetedScanState'];
let combined = '';
for (const n of fnNames) {
  const code = extract(n);
  if (!code) {
    console.error('Could not extract', n);
    process.exit(2);
  }
  combined += code + '\n\n';
}

// Create a minimal DOM
const dom = new JSDOM(`<!doctype html><html><body>
  <div id="scanAreaParent">
    <section id="scanEvidenceSection" style="display:none;">
      <input id="scanFiles" type="file">
      <label id="scanTargetTaskLabel" style="display:none;">Target</label>
    </section>
  </div>
  <div id="host1"></div>
  <div id="host2"></div>
</body></html>`, { runScripts: "dangerously", resources: "usable" });

const { window } = dom;
const { document } = window;

// Provide minimal `$` helper used by functions
window.$ = function(id) { return document.getElementById(id); };

// Inject the extracted helper functions into the window context
try {
  const script = new window.Function(combined + '\nreturn { rememberScanPanelHome, restoreScanPanelHome, attachScanPanelTo, clearTargetedScanState };');
  const helpers = script.call(window);
  window.rememberScanPanelHome = helpers.rememberScanPanelHome.bind(window);
  window.restoreScanPanelHome = helpers.restoreScanPanelHome.bind(window);
  window.attachScanPanelTo = helpers.attachScanPanelTo.bind(window);
  window.clearTargetedScanState = helpers.clearTargetedScanState.bind(window);
} catch (e) {
  console.error('Failed to evaluate helper functions:', e);
  process.exit(3);
}

// Simulate a selected file by setting a custom property on the input
const scanFiles = document.getElementById('scanFiles');
scanFiles.filesSelected = true;

// Run tests
try {
  window.rememberScanPanelHome();
  const section = document.getElementById('scanEvidenceSection');
  const host1 = document.getElementById('host1');
  const host2 = document.getElementById('host2');

  // Attach to host1
  window.attachScanPanelTo(host1);

  const anchors1 = document.querySelectorAll('#scanEvidenceSectionInlineAnchor');
  console.log('Anchors after first attach:', anchors1.length);
  if (anchors1.length !== 1) throw new Error('Expected 1 anchor after first attach');
  if (section.parentNode.id !== 'scanAreaParent') throw new Error('Section should remain in original parent');
  if (!scanFiles.filesSelected) throw new Error('filesSelected lost after first attach');

  // Attach to host2 (should remove previous anchor and create new)
  window.attachScanPanelTo(host2);
  const anchors2 = document.querySelectorAll('#scanEvidenceSectionInlineAnchor');
  console.log('Anchors after second attach:', anchors2.length);
  if (anchors2.length !== 1) throw new Error('Expected 1 anchor after second attach');
  if (anchors2[0].parentNode !== host2) throw new Error('Anchor should be under host2');
  if (section.parentNode.id !== 'scanAreaParent') throw new Error('Section should still remain in original parent after second attach');
  if (!scanFiles.filesSelected) throw new Error('filesSelected lost after second attach');

  console.log('PASS: attachScanPanelTo anchor behavior and file-selection preservation verified');
  process.exit(0);
} catch (e) {
  console.error('TEST FAILED:', e.message || e);
  process.exit(4);
}
