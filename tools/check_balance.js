const fs = require('fs');
const s = fs.readFileSync('app.js', 'utf8');
let stack = [];
let lineno = 1;
let errs = [];
const open = { '{': '}', '(': ')', '[': ']' };
let inSingle = false, inDouble = false, inBack = false, esc = false;
for (let i = 0; i < s.length; i++) {
  const ch = s[i];
  if (ch === '\n') { lineno++; esc = false; continue; }
  if (esc) { esc = false; continue; }
  if (inSingle) { if (ch === '\\') esc = true; else if (ch === "'") inSingle = false; continue; }
  if (inDouble) { if (ch === '\\') esc = true; else if (ch === '"') inDouble = false; continue; }
  if (inBack) { if (ch === '\\') esc = true; else if (ch === '`') inBack = false; continue; }
  if (ch === "'") { inSingle = true; continue; }
  if (ch === '"') { inDouble = true; continue; }
  if (ch === '`') { inBack = true; continue; }
  if (open[ch]) { stack.push({ c: ch, line: lineno }); }
  else if (ch === '}' || ch === ')' || ch === ']') {
    if (stack.length === 0) { errs.push('Unmatched closing ' + ch + ' at line ' + lineno); }
    else { const last = stack[stack.length - 1]; if (open[last.c] != ch) { errs.push('Mismatched ' + last.c + ' opened at line ' + last.line + ' closed by ' + ch + ' at line ' + lineno); stack.pop(); } else stack.pop(); }
  }
}
if (inSingle || inDouble || inBack) errs.push('Unclosed string/backtick at EOF');
if (stack.length) errs.push('Unclosed opens: ' + stack.map(x => x.c + '@' + x.line).join(', '));
if (errs.length) console.error('Balance ERRS:\n' + errs.join('\n'));
else console.log('Brackets balanced');
