/*
 * Behaviour tests for the shared Enter-to-next-field script
 * (templates/partials/_enter_next_field.html).
 *
 * Usage: node enter_next_field.js <spec.json>
 *   spec: { file: "<rendered page>", fields: [names in expected order],
 *           required: [names], fill: {name: validValue}, optional: [names] }
 * Needs the `jsdom` npm package (NODE_PATH). Prints {check name: true|false}.
 * Run by test_enter_next_field.py (skipped when node/jsdom are missing).
 *
 * The REAL rendered page and its real scripts are driven with real
 * KeyboardEvents. "Submit" is observed through the form's submit event
 * (cancelled, since jsdom cannot navigate), so a recorded submit is
 * exactly one form submission, including which button submitted it.
 */
const fs = require('fs');
const { load, key } = require('../../reports/js_tests/_dom');

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
const check = (name, ok) => { out[name] = !!ok; };

try {
  const p = load(spec.file);
  const doc = p.doc;
  const forms = Array.from(doc.querySelectorAll('form[data-enter-next]'));
  check('page: exactly one data-entry form is marked', forms.length === 1);
  const form = forms[0];
  const byName = (n) => form.querySelector(`[name="${n}"]`);
  const names = spec.fields;
  const els = names.map(byName);
  check('page: every expected field exists in the form', els.every(Boolean));
  check('page: the shared script is present exactly once',
    (doc.documentElement.outerHTML.match(/Enter-to-next-field|NOT_FIELDS = /g) || []).length >= 1 &&
    doc.documentElement.outerHTML.split("var NOT_FIELDS").length === 2);

  const submits = [];
  const invalid = [];
  form.addEventListener('submit', (ev) => { submits.push(ev.submitter ? ev.submitter.textContent.trim() : null); ev.preventDefault(); });
  els.forEach((el) => el.addEventListener('invalid', () => invalid.push(el.name)));

  // Fill everything with valid values so the walk starts from a good form
  // (optional fields are tested empty separately).
  const fillAll = () => names.forEach((n) => {
    const el = byName(n);
    if (el.tagName === 'SELECT') {                       // a required select starts on its empty placeholder
      if (!el.value) { const o = Array.from(el.options).find((x) => x.value); if (o) el.value = o.value; }
      return;
    }
    el.value = (spec.fill || {})[n] !== undefined ? spec.fill[n] : (el.value || '1');
  });
  fillAll();

  // ---- Enter moves through every field in order
  let orderOk = true, preventedAll = true;
  for (let i = 0; i < names.length - 1; i++) {
    els[i].focus();
    const pd = key(p, 'Enter', els[i]);
    if (doc.activeElement !== els[i + 1]) { orderOk = false; out[`move ${names[i]} -> ${names[i + 1]}`] = false; }
    if (!pd) preventedAll = false;
  }
  check('walk: Enter moves focus field to field in form order (' + names.join(' > ') + ')', orderOk);
  check('walk: each Enter was consumed (no early native submit)', preventedAll);
  check('walk: nothing was submitted before the last field', submits.length === 0);

  // ---- last field submits, through the form's own submit button
  els[names.length - 1].focus();
  const pdLast = key(p, 'Enter', els[names.length - 1]);
  check('last field: Enter submits the form exactly once', submits.length === 1 && pdLast);
  const buttonText = form.querySelector('button[type="submit"], button:not([type])').textContent.trim();
  check('last field: submitted via the form\'s own submit button', submits[0] === buttonText);

  // ---- required-field validation still works at the last field
  const required = spec.required || [];
  if (required.length) {
    submits.length = 0; invalid.length = 0;
    const victim = byName(required[0]);
    const saved = victim.value;
    victim.value = '';
    els[names.length - 1].focus();
    key(p, 'Enter', els[names.length - 1]);
    check('validation: an empty required field blocks the submit', submits.length === 0);
    check('validation: the browser reports the empty required field as invalid', invalid.includes(required[0]));
    victim.value = saved;
    submits.length = 0;
    key(p, 'Enter', els[names.length - 1]);
    check('validation: submitting works again once the field is filled', submits.length === 1);
  }

  // ---- optional fields may stay empty
  const optional = spec.optional || [];
  if (optional.length) {
    let optOk = true;
    optional.forEach((n) => {
      const el = byName(n); const saved = el.value; el.value = '';
      const i = names.indexOf(n);
      if (i < names.length - 1) {
        el.focus(); key(p, 'Enter', el);
        if (doc.activeElement !== els[i + 1]) optOk = false;
      }
      el.value = saved;
    });
    check('optional: Enter passes straight over empty optional fields', optOk);
    submits.length = 0;
    const last = els[names.length - 1];
    if (optional.includes(names[names.length - 1])) {
      const saved = last.value; last.value = '';
      last.focus(); key(p, 'Enter', last);
      check('optional: an empty optional LAST field still submits', submits.length === 1);
      last.value = saved;
    }
  }

  // ---- keys that must be left alone
  submits.length = 0;
  els[0].focus();
  let modsOk = true;
  [{ shiftKey: true }, { ctrlKey: true }, { altKey: true }, { metaKey: true }].forEach((m) => {
    if (key(p, 'Enter', els[0], m) || doc.activeElement !== els[0]) modsOk = false;
  });
  check('modifiers: Shift/Ctrl/Alt/Meta + Enter are left alone', modsOk && submits.length === 0);

  const pdRepeat = key(p, 'Enter', els[0], { repeat: true });
  check('repeat: a held Enter neither skips fields nor submits', doc.activeElement === els[0] && submits.length === 0 && pdRepeat);
  els[names.length - 1].focus();
  key(p, 'Enter', els[names.length - 1], { repeat: true });
  check('repeat: a held Enter on the last field cannot submit repeatedly', submits.length === 0);

  const pdBody = key(p, 'Enter', doc.body);
  check('outside: Enter with focus on the page (not a form field) is untouched', !pdBody && submits.length === 0);
  const button = form.querySelector('button[type="submit"], button:not([type])');
  check('buttons: Enter on the submit button itself keeps its normal behaviour', !key(p, 'Enter', button));
  const link = form.querySelector('a');
  if (link) check('links: Enter on a link inside the form keeps its normal behaviour', !key(p, 'Enter', link));

  const other = ['ArrowDown', 'ArrowUp', 'Tab', 'Escape', ' ', 'a', '5', '+'].map((k) => key(p, k, els[0])).some(Boolean);
  check('other keys: never consumed', !other);

  // ---- a form's own pre-existing shortcut (the nozzle form's F2 = save) keeps working
  if (spec.f2) {
    submits.length = 0;
    els[0].focus();
    const pdF2 = key(p, 'F2', els[0]);
    check('existing shortcut: F2 still saves the form (once) and is unaffected', pdF2 && submits.length === 1);
    submits.length = 0;
  }

  // ---- a second, unmarked form on the page is never touched
  const stray = doc.createElement('form');
  stray.innerHTML = '<input name="a"><input name="b"><button type="submit">go</button>';
  doc.body.appendChild(stray);
  check('unmarked forms: Enter in an ordinary form is not intercepted', !key(p, 'Enter', stray.querySelector('input')));
} catch (err) {
  out['harness error: ' + err.message] = false;
}
process.stdout.write(JSON.stringify(out));
