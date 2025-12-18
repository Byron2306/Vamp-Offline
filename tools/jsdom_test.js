const { JSDOM } = require('jsdom');
const fetch = require('node-fetch');

async function run() {
  try {
    const url = 'http://127.0.0.1:5000/';
    console.log('Fetching', url);
    const res = await fetch(url);
    const html = await res.text();

    const virtualConsole = new (require('jsdom')).VirtualConsole();
    virtualConsole.on('error', (err) => {
      console.error('VIRTUAL-CONSOLE-ERROR:', err);
    });
    virtualConsole.on('log', (msg) => console.log('VIRTUAL-CONSOLE-LOG:', msg));
    virtualConsole.on('warn', (msg) => console.warn('VIRTUAL-CONSOLE-WARN:', msg));
    virtualConsole.on('info', (msg) => console.info('VIRTUAL-CONSOLE-INFO:', msg));

    const dom = new JSDOM(html, {
      url,
      runScripts: 'dangerously',
      resources: 'usable',
      virtualConsole,
      pretendToBeVisual: true
    });

    // Attach global error handlers to capture runtime errors
    dom.window.onerror = function(message, source, lineno, colno, error) {
      console.error('WINDOW.ERROR:', message, 'at', source + ':' + lineno + ':' + colno, error);
    };
    dom.window.addEventListener('error', (ev) => {
      console.error('RESOURCE/JS ERROR:', ev.message || ev.error || ev);
    });

    // Wait for load or timeout
    await new Promise((resolve) => {
      const t = setTimeout(() => resolve(), 3000);
      dom.window.addEventListener('load', () => {
        clearTimeout(t);
        resolve();
      });
    });

    console.log('DOM loaded. Checking tabs...');
    const doc = dom.window.document;
    const tabs = doc.querySelectorAll('.tab');
    console.log('Found tabs count:', tabs.length);
    if (tabs.length === 0) {
      console.error('No tabs found in DOM');
      return;
    }

    // Find first non-active tab and click it
    let clicked = false;
    for (let i = 0; i < tabs.length; i++) {
      const t = tabs[i];
      if (!t.classList.contains('active')) {
        console.log('Clicking tab:', t.textContent.trim());
        t.click();
        clicked = true;
        break;
      }
    }

    if (!clicked) {
      console.log('All tabs already active?');
    }

    // Check which panel is active
    const activePanel = doc.querySelector('.panel.active');
    console.log('Active panel id:', activePanel ? activePanel.id : 'none');

    // Print any console captured messages from app.js initialization
    console.log('Test complete');
  } catch (e) {
    console.error('Test failed:', e);
    process.exit(2);
  }
}

run();
