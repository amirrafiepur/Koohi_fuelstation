/*
 * Shared jsdom helpers for the keyboard-navigation behaviour tests.
 *
 * jsdom has no layout engine, so layout is modelled: 600px viewport, rows
 * 30px tall, table body starting 200px down, and scrollIntoView({block:
 * 'nearest'}) implemented with the spec's semantics (scroll only as far as
 * needed, honouring the row's scroll-margin of 40px). Rows are the <tr>s of
 * any <tbody>.
 */
const fs = require('fs');
const { JSDOM } = require('jsdom');

const VIEWPORT = 600, ROW_H = 30, TABLE_TOP = 200, MARGIN = 40;

function load(file) {
  const html = fs.readFileSync(file, 'utf8');
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.JalaliCalendar = { bindNavInputs() {}, mount() {}, init() {} };   // unrelated calendar widget, stubbed
      window.__scrollY = 0;
      window.__scrollCalls = [];
      Object.defineProperty(window, 'innerHeight', { value: VIEWPORT });
      Object.defineProperty(window, 'scrollY', { get: () => window.__scrollY });
      const proto = window.Element.prototype;
      const rowIndex = (el) => Array.prototype.indexOf.call(window.document.querySelectorAll('tbody tr'), el);
      proto.getBoundingClientRect = function () {
        if (this.tagName === 'TR' && this.parentNode.tagName === 'TBODY') {
          const top = TABLE_TOP + rowIndex(this) * ROW_H - window.__scrollY;
          return { top, bottom: top + ROW_H, height: ROW_H, left: 0, right: 0, width: 0 };
        }
        return { top: 0, bottom: 0, height: 0, left: 0, right: 0, width: 0 };
      };
      proto.scrollIntoView = function (opts) {
        window.__scrollCalls.push({ index: this.tagName === 'TR' ? rowIndex(this) : -1, opts });
        if (this.tagName !== 'TR') return;
        const top = this.getBoundingClientRect().top;
        const bottom = top + ROW_H;
        if (top - MARGIN < 0) window.__scrollY += top - MARGIN;                    // scroll up
        else if (bottom + MARGIN > VIEWPORT) window.__scrollY += bottom + MARGIN - VIEWPORT; // scroll down
        if (window.__scrollY < 0) window.__scrollY = 0;
      };
    },
  });
  const { window } = dom;
  const select = window.document.getElementById('nozzle-select');
  const changes = [];
  if (select) {
    select.removeAttribute('onchange');        // jsdom cannot navigate; record instead
    select.addEventListener('change', () => changes.push(select.value));
  }
  return { window, doc: window.document, select, changes };
}

function key(page, k, target, extra) {
  const ev = new page.window.KeyboardEvent('keydown', Object.assign(
    { key: k, bubbles: true, cancelable: true }, extra || {}));
  (target || page.doc.body).dispatchEvent(ev);
  return ev.defaultPrevented;
}

module.exports = { VIEWPORT, ROW_H, TABLE_TOP, MARGIN, load, key };
