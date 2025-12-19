const fs = require('fs');

// Read app.js and extract functions
const appJs = fs.readFileSync('./app.js', 'utf8');
function extract(fnName) {
  const re = new RegExp(`function ${fnName}\\s*\\([\\s\\S]*?\\)\\s*\\{`);
  const start = appJs.search(re);
  if (start === -1) return null;
  let i = start;
  while (i < appJs.length && appJs[i] !== '{') i++;
  let depth = 0; let end = i;
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
  if (!code) { console.error('Missing', n); process.exit(2); }
  combined += code + '\n\n';
}

// Minimal DOM implementation
class Element {
  constructor(tagName, id) {
    this.tagName = tagName || 'div';
    this.id = id || null;
    this.children = [];
    this.parentNode = null;
    this.nextSibling = null;
    this.style = {};
    this.innerHTML = '';
    this.textContent = '';
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    this.children.push(child);
    child.parentNode = this;
    // update nextSibling for previous child
    if (this.children.length >= 2) {
      const prev = this.children[this.children.length-2];
      prev.nextSibling = child;
    }
    child.nextSibling = null;
  }
  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx >= 0) {
      this.children.splice(idx,1);
      child.parentNode = null;
      // update nextSibling of previous
      if (idx > 0) {
        const prev = this.children[idx-1];
        prev.nextSibling = this.children[idx] || null;
      }
    }
  }
  querySelector(sel) {
    if (!sel) return null;
    if (sel.startsWith('#')) {
      const id = sel.slice(1);
      return document.getElementById(id);
    }
    if (sel === 'button') {
      // return a simple button element
      return new Element('button', null);
    }
    return null;
  }
  querySelectorAll(sel) {
    if (sel.startsWith('#')) {
      const id = sel.slice(1);
      const el = document.getElementById(id);
      return el ? [el] : [];
    }
    return [];
  }
  addEventListener(evt, fn) {
    this._listeners[evt] = this._listeners[evt] || [];
    this._listeners[evt].push(fn);
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  scrollIntoView() { /* noop */ }
}

const document = {
  _byId: {},
  createElement(tag) { return new Element(tag, null); },
  getElementById(id) { return this._byId[id] || null; },
  querySelectorAll(sel) {
    if (sel === '#scanEvidenceSectionInlineAnchor') {
      const el = this.getElementById('scanEvidenceSectionInlineAnchor');
      return el ? [el] : [];
    }
    return [];
  }
};

// Helper to register element by id when created
function createEl(tag, id) {
  const el = new Element(tag, id);
  if (id) document._byId[id] = el;
  return el;
}

// Build initial tree
const scanAreaParent = createEl('div','scanAreaParent');
const section = createEl('section','scanEvidenceSection');
section.style.display = 'none';
const scanFiles = createEl('input','scanFiles');
scanFiles.type = 'file';
scanFiles.filesSelected = true; // simulate selection
section.appendChild(scanFiles);
const targetLabel = createEl('label','scanTargetTaskLabel');
targetLabel.style.display = 'none';
section.appendChild(targetLabel);
scanAreaParent.appendChild(section);
const host1 = createEl('div','host1');
const host2 = createEl('div','host2');

// Expose globals expected by functions
global.document = document;
global.$ = function(id){ return document.getElementById(id); };
// register top-level elements
document._byId['scanAreaParent'] = scanAreaParent;
document._byId['scanEvidenceSection'] = section;
document._byId['scanFiles'] = scanFiles;
document._byId['scanTargetTaskLabel'] = targetLabel;
document._byId['host1'] = host1;
document._byId['host2'] = host2;
// Implement simplified versions of the helpers (matching app.js behavior)
let scanPanelHome = null;
function rememberScanPanelHome() {
  if (scanPanelHome) return;
  const sectionEl = document.getElementById('scanEvidenceSection');
  if (!sectionEl || !sectionEl.parentNode) return;
  scanPanelHome = { parent: sectionEl.parentNode, nextSibling: sectionEl.nextSibling };
}

function restoreScanPanelHome({ hide = true } = {}) {
  const sectionEl = document.getElementById('scanEvidenceSection');
  if (!sectionEl || !scanPanelHome?.parent) return;
  const { parent, nextSibling } = scanPanelHome;
  if (nextSibling && nextSibling.parentNode === parent) {
    parent.appendChild(sectionEl); // ensure append to end then insert before nextSibling
    parent.removeChild(sectionEl);
    parent.appendChild(sectionEl);
  } else {
    parent.appendChild(sectionEl);
  }
  if (hide) sectionEl.style.display = 'none';
}

function attachScanPanelTo(hostEl) {
  const sectionEl = document.getElementById('scanEvidenceSection');
  if (!sectionEl || !hostEl) return;
  rememberScanPanelHome();

  // Remove any existing inline anchors
  try { document.querySelectorAll('#scanEvidenceSectionInlineAnchor').forEach(a => a.remove()); } catch (e) {}

  // If section already visible, scroll and return
  if (sectionEl.style.display === 'block') { sectionEl.scrollIntoView(); return; }

  // Create anchor
  const anchor = createEl('div','scanEvidenceSectionInlineAnchor');
  anchor.style.cssText = 'margin-bottom:8px;';
  const btn = createEl('button', null);
  btn.addEventListener('click', () => { sectionEl.style.display = 'block'; sectionEl.scrollIntoView(); const targetLabel = document.getElementById('scanTargetTaskLabel'); if (targetLabel && targetLabel.style.display === 'none') targetLabel.style.display = 'block'; });
  anchor.appendChild(btn);
  hostEl.appendChild(anchor);
}

function clearTargetedScanState() {
  const targetInput = document.getElementById('scanTargetTaskId');
  if (targetInput) targetInput.value = '';
  const targetLabel = document.getElementById('scanTargetTaskLabel');
  if (targetLabel) targetLabel.style.display = 'none';
}

global.rememberScanPanelHome = rememberScanPanelHome;
global.restoreScanPanelHome = restoreScanPanelHome;
global.attachScanPanelTo = attachScanPanelTo;
global.clearTargetedScanState = clearTargetedScanState;

// Now run the scenario
try {
  global.rememberScanPanelHome();
  global.attachScanPanelTo(host1);
  const anchors1 = document.querySelectorAll('#scanEvidenceSectionInlineAnchor');
  console.log('Anchors after first attach:', anchors1.length);
  if (anchors1.length !== 1) throw new Error('Expected 1 anchor after first attach');
  if (section.parentNode !== scanAreaParent) throw new Error('Section should remain in original parent');
  if (!scanFiles.filesSelected) throw new Error('filesSelected lost after first attach');

  global.attachScanPanelTo(host2);
  const anchors2 = document.querySelectorAll('#scanEvidenceSectionInlineAnchor');
  console.log('Anchors after second attach:', anchors2.length);
  if (anchors2.length !== 1) throw new Error('Expected 1 anchor after second attach');
  // Ensure the anchor parent is host2
  const anchor = anchors2[0];
  if (anchor.parentNode !== host2) throw new Error('Anchor should be under host2');
  if (section.parentNode !== scanAreaParent) throw new Error('Section should still remain in original parent after second attach');
  if (!scanFiles.filesSelected) throw new Error('filesSelected lost after second attach');

  console.log('PASS');
  process.exit(0);
} catch (e) {
  console.error('TEST FAILED:', e.message || e);
  process.exit(4);
}
