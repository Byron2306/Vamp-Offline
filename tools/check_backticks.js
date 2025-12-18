const fs = require('fs');
const s = fs.readFileSync('app.js','utf8');
const m = s.match(/`/g) || [];
console.log('backticks count', m.length);
const last = s.lastIndexOf('`');
console.log('last backtick pos', last);
console.log('tail:\n' + s.slice(Math.max(0, last - 200)));
