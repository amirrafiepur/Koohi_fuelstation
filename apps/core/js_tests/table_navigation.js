/*
 * Behaviour tests for the global table keyboard navigation
 * (templates/partials/_table_row_navigation.html), run against any page.
 *
 * Usage: node table_navigation.js <spec.json>
 *   spec: { file: "<rendered page>", groups: [rows-per-unit, ...],
 *           arrowsOutside: "normal" | "nozzle", inputInTable: "<css selector>"? }
 *   `groups` is computed independently (in Python) from the page's HTML:
 *   one entry per navigable unit, the number of <tr> in it (1, or more where a
 *   rowspan ties rows together). Placeholder rows are not units.
 * Needs the `jsdom` npm package (NODE_PATH). Prints {check name: true|false}.
 *
 * The REAL rendered page and its real scripts are driven with real
 * KeyboardEvents; layout/scrolling is modelled by ../../reports/js_tests/_dom.js.
 */
const fs = require('fs');
const { VIEWPORT, load, key } = require('../../reports/js_tests/_dom');

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
const check = (name, ok) => { out[name] = !!ok; };

try {
  const p = load(spec.file);
  const doc = p.doc;
  const allRows = Array.from(doc.querySelectorAll('main table:not([data-row-nav="off"]) > tbody > tr'));
  const isPlaceholder = (tr) => tr.cells.length === 1 && tr.cells[0].colSpan > 1;
  const realRows = allRows.filter((tr) => !isPlaceholder(tr));

  if (spec.groups.length === 0) {                     // a page with no data rows
    check('empty: the page has no navigable rows', realRows.length === 0);
    check('empty: Enter is left alone (not consumed) and nothing is highlighted',
      !key(p, 'Enter') && !allRows.some((tr) => tr.classList.contains('row-selected')));
    check('empty: arrows are left alone', !key(p, 'ArrowDown') && !key(p, 'ArrowUp'));
    check('empty: no hint appears', !doc.getElementById('table-nav-hint') || doc.getElementById('table-nav-hint').hidden);
    process.stdout.write(JSON.stringify(out));
    process.exit(0);
  }

  // The units the page SHOULD have, from the spec: consecutive runs of rows.
  const expectedUnits = [];
  let at = 0;
  spec.groups.forEach((size) => { expectedUnits.push(realRows.slice(at, at + size)); at += size; });
  const units = expectedUnits.length;
  check('fixture: the page has navigable rows', units >= 1);
  check('fixture: the units account for every non-placeholder body row', at === realRows.length);

  const selected = () => allRows.filter((tr) => tr.classList.contains('row-selected'));
  const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));
  const selectedUnit = () => expectedUnits.findIndex((u) => sameSet(selected(), u));
  const hintShown = () => ['table-nav-hint', 'table-mode-hint'].some((id) => {
    const el = doc.getElementById(id); return el && !el.hidden;
  });
  const unitVisible = (u) => u.every((tr) => { const r = tr.getBoundingClientRect(); return r.top >= 0 && r.bottom <= VIEWPORT; });
  const nozzleSelect = doc.getElementById('nozzle-select');

  // ---- default state
  check('default: nothing is highlighted and no hint is shown', selected().length === 0 && !hintShown());
  if (spec.arrowsOutside === 'normal') {
    check('default: ArrowUp/ArrowDown keep their normal browser behaviour (not consumed)',
      !key(p, 'ArrowUp') && !key(p, 'ArrowDown') && selected().length === 0);
  }

  // ---- Enter activates, highlighting the FIRST row in blue
  let prevented = key(p, 'Enter');
  check('enter: highlights the first row (all its rows when a rowspan ties several)', selectedUnit() === 0);
  check('enter: Enter was consumed', prevented);
  check('enter: a mode hint is shown', hintShown());
  check('enter: the highlighted rows expose aria-selected', selected().every((tr) => tr.getAttribute('aria-selected') === 'true'));
  check('enter: placeholder rows are never selected', selected().every((tr) => !isPlaceholder(tr)));
  if (nozzleSelect) { /* nozzle pages: the select must not have moved */ }
  const nozzleBefore = nozzleSelect ? nozzleSelect.value : null;

  // ---- walk down through every unit
  let down = true, vis = true;
  const y0 = p.window.__scrollY;
  for (let i = 1; i < units; i++) {
    key(p, 'ArrowDown');
    if (selectedUnit() !== i) down = false;
    if (!unitVisible(expectedUnits[i])) vis = false;
  }
  check('walk down: each ArrowDown moves to exactly the next row/unit (' + units + ' in total)', down);
  check('scroll: the selected row/unit is fully inside the viewport after every step down', vis);
  if (units * 30 + 200 > VIEWPORT) check('scroll: the page actually scrolled to follow the selection', p.window.__scrollY > y0);
  check('scroll: scrolling was requested with block "nearest"',
    p.window.__scrollCalls.length === 0 || p.window.__scrollCalls.every((c) => c.opts && c.opts.block === 'nearest'));
  prevented = key(p, 'ArrowDown');
  check('walk down: cannot move past the last row, and the key is still consumed', selectedUnit() === units - 1 && prevented);

  // ---- walk back up
  let up = true; vis = true;
  const yBottom = p.window.__scrollY;
  for (let i = units - 2; i >= 0; i--) {
    key(p, 'ArrowUp');
    if (selectedUnit() !== i) up = false;
    if (!unitVisible(expectedUnits[i])) vis = false;
  }
  check('walk up: each ArrowUp moves to exactly the previous row/unit', up);
  check('scroll: the selected row/unit stays fully inside the viewport on every step up', vis);
  if (units * 30 + 200 > VIEWPORT) check('scroll: the page scrolled back up', p.window.__scrollY < yBottom);
  prevented = key(p, 'ArrowUp');
  check('walk up: cannot move above the first row, and the key is still consumed', selectedUnit() === 0 && prevented);
  check('modes: arrows in table navigation never touch the nozzle selector', !nozzleSelect || nozzleSelect.value === nozzleBefore);

  // ---- Enter again exits
  key(p, 'ArrowDown');
  prevented = key(p, 'Enter');
  check('exit: second Enter removes every blue highlight', selected().length === 0);
  check('exit: the hint is hidden and Enter was consumed', !hintShown() && prevented);
  if (spec.arrowsOutside === 'normal') {
    check('exit: arrows are back to their normal browser behaviour', !key(p, 'ArrowUp') && !key(p, 'ArrowDown') && selected().length === 0);
  }
  key(p, 'Enter');
  check('re-enter: starts again at the first row', selectedUnit() === 0);
  key(p, 'Enter');

  // ---- no interference with controls / modifiers / other keys
  const controls = [];
  const mk = (tag, set) => { const el = doc.createElement(tag); if (set) set(el); doc.body.appendChild(el); return el; };
  controls.push(['input', mk('input')], ['select', mk('select')], ['textarea', mk('textarea')],
    ['button', mk('button')], ['link', mk('a', (a) => { a.href = '#x'; })],
    ['editable', mk('div', (d) => Object.defineProperty(d, 'isContentEditable', { value: true }))]);
  if (spec.inputInTable) {
    const real = doc.querySelector(spec.inputInTable);
    check('fixture: the page has an input inside a table', !!real);
    if (real) controls.push(['input inside a table row', real]);
  }
  let untouched = true;
  controls.forEach(([name, el]) => ['Enter', 'ArrowUp', 'ArrowDown'].forEach((k) => {
    if (key(p, k, el) || selected().length !== 0) { untouched = false; out['ignored in ' + name + ' (' + k + ')'] = false; }
  }));
  check('controls: Enter/Arrow keys are ignored in inputs, selects, textareas, buttons, links, editables (and in-table inputs)', untouched);

  let modsOk = true;
  [{ ctrlKey: true }, { altKey: true }, { metaKey: true }].forEach((m) => ['Enter', 'ArrowUp', 'ArrowDown'].forEach((k) => {
    if (key(p, k, null, m) || selected().length) modsOk = false;
  }));
  check('modifiers: Ctrl/Alt/Meta + Enter/Arrow are ignored', modsOk);

  const otherPrevented = ['Escape', 'Tab', 'ArrowLeft', 'ArrowRight', ' ', 'a', 'Backspace', 'F2'].map((k) => key(p, k)).some(Boolean);
  check('other keys: untouched (never consumed, no mode change)', !otherPrevented && selected().length === 0);

  key(p, 'Enter');
  key(p, 'Enter', null, { repeat: true }); key(p, 'Enter', null, { repeat: true });
  check('repeat: auto-repeated Enter does not toggle the mode', selectedUnit() === 0);
  key(p, 'Enter');
  check('repeat: a real Enter still exits', selected().length === 0);

  // ---- Enter with focus inside a data-entry form is the form script's, not ours
  const form = doc.createElement('form'); form.setAttribute('data-enter-next', '');
  form.innerHTML = '<input name="a"><input name="b"><button type="submit">ok</button>';
  doc.body.appendChild(form);
  const a = form.querySelector('[name=a]'); a.focus();
  prevented = key(p, 'Enter', a);
  check('forms: Enter inside a data-entry form field moves to the next field and never starts table navigation',
    prevented && doc.activeElement === form.querySelector('[name=b]') && selected().length === 0);
} catch (err) {
  out['harness error: ' + err.message] = false;
}
process.stdout.write(JSON.stringify(out));
