/*
 * Behaviour tests for the keyboard navigation on "لیست اطلاعات فروش".
 *
 * Usage: node all_nozzles_keyboard.js <rendered-page.html> <expected-row-count>
 * Needs the `jsdom` npm package (resolved via NODE_PATH). Prints one JSON
 * object {check name: true | false}; run by test_all_nozzles_report.py,
 * which skips itself when node/jsdom are not installed. The REAL rendered
 * page (its real inline scripts) is driven with real KeyboardEvents;
 * layout/scrolling is modelled by _dom.js.
 */
const { VIEWPORT, ROW_H, TABLE_TOP, load, key } = require('./_dom');

const ROWS = '#all-nozzles-table tbody tr';
const selectedRows = (p) => Array.from(p.doc.querySelectorAll(ROWS + '.row-selected'));
const selectedIndex = (p) => {
  const r = selectedRows(p);
  return r.length === 1 ? Array.prototype.indexOf.call(r[0].parentNode.children, r[0]) : r.length === 0 ? -1 : -99;
};
const hintVisible = (p) => !p.doc.getElementById('table-mode-hint').hidden;
const inViewport = (p) => {
  const row = p.doc.querySelectorAll(ROWS)[selectedIndex(p)];
  if (!row) return false;
  const r = row.getBoundingClientRect();
  return r.top >= 0 && r.bottom <= VIEWPORT;
};

const out = {};
const check = (name, ok) => { out[name] = !!ok; };

try {
  const p = load(process.argv[2]);
  const doc = p.doc;
  const rows = doc.querySelectorAll(ROWS).length;
  check('fixture: exactly the selected fuel\'s nozzle rows (' + process.argv[3] + ')', rows === Number(process.argv[3]));
  check('fixture: no nozzle selector on this page', !doc.getElementById('nozzle-select'));

  // ---- default state: normal keyboard behaviour, nothing highlighted
  check('default: no row highlighted and no hint', selectedRows(p).length === 0 && !hintVisible(p));
  check('default: ArrowUp/ArrowDown keep their normal browser behaviour (not prevented)',
    !key(p, 'ArrowUp') && !key(p, 'ArrowDown'));
  check('default: arrows did not highlight anything', selectedRows(p).length === 0);

  // ---- Enter activates table navigation
  let prevented = key(p, 'Enter');
  check('enter: highlights the FIRST row', selectedIndex(p) === 0 &&
    selectedRows(p)[0] === doc.querySelector(ROWS));
  check('enter: Enter itself was consumed', prevented);
  check('enter: mode hint is shown', hintVisible(p));
  check('enter: highlighted row exposes aria-selected', selectedRows(p)[0].getAttribute('aria-selected') === 'true');

  // ---- row navigation
  prevented = key(p, 'ArrowDown');
  check('mode: ArrowDown moves to the next row', selectedIndex(p) === 1 && prevented);
  key(p, 'ArrowDown'); key(p, 'ArrowDown');
  check('mode: three downs from row 0 -> row 3', selectedIndex(p) === 3 &&
    selectedRows(p)[0] === doc.querySelectorAll(ROWS)[3]);
  key(p, 'ArrowUp');
  check('mode: ArrowUp moves to the previous row', selectedIndex(p) === 2);
  check('mode: only one row is ever highlighted', selectedRows(p).length === 1);

  key(p, 'ArrowUp'); key(p, 'ArrowUp'); key(p, 'ArrowUp'); key(p, 'ArrowUp');
  check('mode: cannot move above the first row', selectedIndex(p) === 0);
  prevented = key(p, 'ArrowUp');
  check('mode: ArrowUp on the first row stays put and does not scroll the page natively', selectedIndex(p) === 0 && prevented);

  // ---- automatic scrolling over the whole table
  let allVisible = true;
  const y0 = p.window.__scrollY;
  for (let i = 1; i < rows; i++) {
    key(p, 'ArrowDown');
    if (selectedIndex(p) !== i || !inViewport(p)) allVisible = false;
  }
  check('scroll: selected row stays inside the viewport on every step down (all rows)', allVisible);
  const needsScroll = TABLE_TOP + rows * ROW_H > VIEWPORT;      // a short table (e.g. 6 Super nozzles) fits on screen
  if (needsScroll) check('scroll: the page really scrolled to follow the selection', p.window.__scrollY > y0);
  check('scroll: scrolling requested with block "nearest" on the selected row',
    p.window.__scrollCalls.length > 0 &&
    p.window.__scrollCalls.every((c) => c.opts && c.opts.block === 'nearest') &&
    p.window.__scrollCalls[p.window.__scrollCalls.length - 1].index === rows - 1);
  prevented = key(p, 'ArrowDown');
  check('mode: cannot move below the last row', selectedIndex(p) === rows - 1 && prevented);

  const yBottom = p.window.__scrollY;
  allVisible = true;
  for (let i = rows - 2; i >= 0; i--) {
    key(p, 'ArrowUp');
    if (selectedIndex(p) !== i || !inViewport(p)) allVisible = false;
  }
  check('scroll: selected row stays inside the viewport on every step up', allVisible);
  if (needsScroll) check('scroll: the page scrolled back up', p.window.__scrollY < yBottom);

  // ---- Enter again exits
  key(p, 'ArrowDown'); key(p, 'ArrowDown');
  prevented = key(p, 'Enter');
  check('exit: second Enter removes the blue highlight', selectedRows(p).length === 0);
  check('exit: hint hidden and Enter consumed', !hintVisible(p) && prevented);
  check('exit: arrows are back to normal browser behaviour', !key(p, 'ArrowUp') && !key(p, 'ArrowDown') &&
    selectedRows(p).length === 0);
  key(p, 'Enter');
  check('re-enter: starts again at the first row', selectedIndex(p) === 0);
  key(p, 'Enter');

  // ---- must not interfere with controls / modifiers / other keys
  const inputs = doc.querySelectorAll('input');
  const yearInput = inputs[0];
  const monthSelect = doc.querySelector('select');
  const button = doc.createElement('button'); doc.body.appendChild(button);
  const link = doc.createElement('a'); link.href = '#x'; doc.body.appendChild(link);
  const textarea = doc.createElement('textarea'); doc.body.appendChild(textarea);
  const editable = doc.createElement('div');
  Object.defineProperty(editable, 'isContentEditable', { value: true });
  doc.body.appendChild(editable);
  check('fixture: year input and month select exist', !!yearInput && !!monthSelect);
  let untouched = true;
  [[yearInput, 'year input'], [monthSelect, 'month select'], [button, 'button'], [link, 'link'],
   [textarea, 'textarea'], [editable, 'editable']].forEach(([el, name]) => {
    ['Enter', 'ArrowUp', 'ArrowDown'].forEach((k) => {
      if (key(p, k, el) || selectedRows(p).length !== 0) { untouched = false; out['ignored in ' + name + ' (' + k + ')'] = false; }
    });
  });
  check('controls: Enter/Arrow keys are ignored in inputs, selects, buttons, links, textareas, editables', untouched);

  let modsOk = true;
  [{ ctrlKey: true }, { altKey: true }, { metaKey: true }].forEach((m) => {
    ['Enter', 'ArrowUp', 'ArrowDown'].forEach((k) => {
      if (key(p, k, null, m) || selectedRows(p).length) modsOk = false;
    });
  });
  check('modifiers: Ctrl/Alt/Meta + Enter/Arrow are ignored', modsOk);

  const otherPrevented = ['Escape', 'Tab', 'ArrowLeft', 'ArrowRight', ' ', 'a', 'Backspace', 'F2']
    .map((k) => key(p, k)).some(Boolean);
  check('other keys: untouched (never prevented, no mode change)', !otherPrevented && selectedRows(p).length === 0);

  key(p, 'Enter');
  key(p, 'Enter', null, { repeat: true }); key(p, 'Enter', null, { repeat: true });
  check('repeat: auto-repeated Enter does not toggle the mode', selectedIndex(p) === 0);
  key(p, 'Enter', yearInput);
  check('controls: Enter inside the year input does not leave table mode', selectedIndex(p) === 0);
  key(p, 'Enter');
  check('repeat: a real Enter still exits', selectedRows(p).length === 0);
} catch (err) {
  out['harness error: ' + err.message] = false;
}

process.stdout.write(JSON.stringify(out));
