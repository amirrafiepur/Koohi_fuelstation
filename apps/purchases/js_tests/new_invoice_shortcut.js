/*
 * Behaviour tests for the "+" shortcut on "فاکتورهای خرید".
 *
 * Usage: node new_invoice_shortcut.js <list.html> <entry-form.html> <other-section.html> <list-without-tanks.html>
 * Needs the `jsdom` npm package (NODE_PATH). Prints {check name: true|false}.
 * Run by test_new_invoice_shortcut.py (skipped when node/jsdom are missing).
 *
 * The REAL rendered pages and their real inline scripts are loaded and
 * driven with real KeyboardEvents. The shortcut activates the first
 * "+ فاکتور جدید" link via link.click(); here every click on such a link
 * is recorded and cancelled (jsdom cannot navigate), so each recorded
 * click is exactly one form being opened.
 */
const { load, key } = require('../../reports/js_tests/_dom');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = {};
const check = (name, ok) => { out[name] = !!ok; };

function track(p) {
  p.clicks = [];
  p.doc.addEventListener('click', (ev) => {
    const a = ev.target.closest && ev.target.closest('a');
    if (a) { p.clicks.push(a.href); ev.preventDefault(); }       // record + stop jsdom's navigation
  }, true);
  p.reset = () => p.window.dispatchEvent(new p.window.Event('pageshow'));   // as after Back / cache restore
}
const press = (p, k, target, extra) => key(p, k, target, extra);

(async () => {
  try {
    // ------------------------------------------------------------ the purchases list
    const p = load(process.argv[2]);
    track(p);
    // jsdom fires its own `pageshow` shortly after load; let it happen now so it
    // cannot re-arm the shortcut in the middle of a later check.
    await sleep(200);
    const doc = p.doc;
    const links = Array.from(doc.querySelectorAll('a[data-new-invoice-link]'));
    const firstHref = links[0] && links[0].href;
    check('fixture: two new-invoice links (Regular, Super) on the page', links.length === 2);
    check('fixture: the first link is the first product\'s new-entry form', /\/purchases\/[\d-]+\/tank\/\d+\/new\/$/.test(firstHref || ''));
    check('hint: the first button carries a keyboard-shortcut tooltip', (links[0].title || '').includes('+'));

    // ---- main keyboard: Shift + "=" (US layout) reports key "+"
    let prevented = press(p, '+', null, { shiftKey: true, code: 'Equal' });
    check('plus: Shift+= (US layout) opens the first form', p.clicks.length === 1 && p.clicks[0] === firstHref);
    check('plus: the key press was consumed', prevented);
    check('plus: the second product\'s form is never the one opened', !p.clicks.includes(links[1].href));

    // ---- no duplicates
    press(p, '+', null, { shiftKey: true });
    press(p, '+', null, { shiftKey: true });
    check('duplicates: quick extra presses open nothing more', p.clicks.length === 1);
    p.reset();
    p.clicks.length = 0;
    press(p, '+', null, { shiftKey: true, repeat: true });
    check('duplicates: auto-repeat (held key) opens nothing', p.clicks.length === 0);
    p.reset(); p.clicks.length = 0;

    // ---- other layouts / numeric keypad
    press(p, '+', null, { code: 'NumpadAdd' });
    check('plus: numeric-keypad + opens the form', p.clicks.length === 1 && p.clicks[0] === firstHref);
    p.reset(); p.clicks.length = 0;
    press(p, '+', null, { code: 'BracketRight' });          // layouts with a direct, unshifted "+" key
    check('plus: a direct "+" key (no Shift) opens the form', p.clicks.length === 1);
    p.reset(); p.clicks.length = 0;

    // ---- keys that are NOT plus
    // (Enter is deliberately absent: on a page with tables it now toggles table navigation.)
    const notPlusPrevented = ['=', '-', '*', '1', '0', 'Add', 'Escape', 'Tab', ' ', 'a', 'F2',
      'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Backspace', 'Delete'].map((k) => press(p, k)).some(Boolean);
    check('other keys: never prevented and never open a form', !notPlusPrevented && p.clicks.length === 0);
    press(p, '=', null, { shiftKey: true, code: 'Equal' });
    check('other keys: "=" with Shift (a layout where that is not plus) does nothing', p.clicks.length === 0);

    // ---- must not interfere with typing / controls / shortcuts
    const dateInputs = Array.from(doc.querySelectorAll('input'));
    const select = doc.createElement('select'); doc.body.appendChild(select);
    const textarea = doc.createElement('textarea'); doc.body.appendChild(textarea);
    const editable = doc.createElement('div'); Object.defineProperty(editable, 'isContentEditable', { value: true });
    doc.body.appendChild(editable);
    check('fixture: the list has date inputs', dateInputs.length >= 2);
    let untouched = true;
    [[dateInputs[0], 'date input'], [dateInputs[1], 'date input 2'], [select, 'select'], [textarea, 'textarea'], [editable, 'editable']]
      .forEach(([el, name]) => {
        const before = p.clicks.length;
        if (press(p, '+', el, { shiftKey: true }) || p.clicks.length !== before) { untouched = false; out['ignored in ' + name] = false; }
      });
    check('typing: "+" typed in inputs, selects, textareas, editable elements is left alone', untouched);

    let modsOk = true;
    [{ ctrlKey: true }, { altKey: true }, { metaKey: true }, { ctrlKey: true, shiftKey: true }].forEach((m) => {
      const before = p.clicks.length;
      if (press(p, '+', null, m) || p.clicks.length !== before) modsOk = false;
    });
    check('modifiers: Ctrl/Alt/Meta + "+" (browser zoom etc.) is left alone', modsOk);

    // ---- works from a focused button / link (they have no native "+" behaviour)
    const btn = doc.createElement('button'); doc.body.appendChild(btn);
    press(p, '+', btn, { shiftKey: true });
    check('focus: works while a button has focus', p.clicks.length === 1);
    p.reset(); p.clicks.length = 0;
    press(p, '+', links[1], { shiftKey: true });
    check('focus: works while a link (even the Super one) has focus, still opens the first form',
      p.clicks.length === 1 && p.clicks[0] === firstHref);
    p.reset(); p.clicks.length = 0;

    // ---- coming back to the cached page (Back button) re-arms the shortcut
    press(p, '+', null, { shiftKey: true });
    check('re-arm: first press opened the form', p.clicks.length === 1);
    p.reset();
    press(p, '+', null, { shiftKey: true });
    check('re-arm: after returning to the page the shortcut works again', p.clicks.length === 2);

    // ---- safety timeout re-arms it as well
    p.clicks.length = 0;
    await sleep(1700);
    press(p, '+', null, { shiftKey: true });
    check('re-arm: still works after the safety timeout (navigation that never completed)', p.clicks.length === 1);

    // ---- table navigation (Enter) and "+" coexist
    p.reset(); p.clicks.length = 0;
    check('coexist: Enter toggles table navigation on this page (first row highlighted)',
      press(p, 'Enter') && doc.querySelectorAll('tr.row-selected').length >= 1);
    press(p, '+', null, { shiftKey: true });
    check('coexist: "+" still opens the new-invoice form while table navigation is active', p.clicks.length === 1);
    press(p, 'Enter');
    check('coexist: Enter again leaves table navigation', doc.querySelectorAll('tr.row-selected').length === 0);
    p.reset(); p.clicks.length = 0;

    // ---- the existing Escape shortcut (base.html) still works and "+" does not disturb it
    let backCalls = 0;
    Object.defineProperty(p.window.history, 'length', { value: 3, configurable: true });
    p.window.history.back = () => { backCalls++; };
    prevented = press(p, 'Escape');
    check('existing: Escape still goes back (site-wide shortcut intact)', backCalls === 1 && prevented);
    p.clicks.length = 0;
    press(p, 'Escape', dateInputs[0]);
    check('existing: Escape inside an input still does nothing', backCalls === 1);

    // ------------------------------------------------------------ the new-invoice form itself
    const f = load(process.argv[3]);
    track(f);
    check('form page: it is the purchase form', !!f.doc.getElementById('purchase-form'));
    check('form page: no second "new invoice" link or shortcut to duplicate it', f.doc.querySelectorAll('a[data-new-invoice-link]').length === 0);
    prevented = press(f, '+', null, { shiftKey: true });
    press(f, '+', null, { code: 'NumpadAdd' });
    check('form page: "+" with the form open opens nothing (no duplicate forms) and is not consumed',
      f.clicks.length === 0 && !prevented);
    const fields = Array.from(f.doc.querySelectorAll('#purchase-form input:not([type="hidden"])'));
    check('form page: "+" is a normal character in the form fields', !press(f, '+', fields[0], { shiftKey: true }));
    prevented = press(f, 'Enter', fields[0]);
    check('form page: the existing Enter-to-next-field shortcut still works', prevented && f.doc.activeElement === fields[1]);

    // ------------------------------------------------------------ another section
    const o = load(process.argv[4]);
    track(o);
    prevented = press(o, '+', null, { shiftKey: true });
    check('other section: "+" does nothing there and is not consumed', o.clicks.length === 0 && !prevented);

    // ------------------------------------------------------------ list with no tanks
    const e = load(process.argv[5]);
    track(e);
    prevented = press(e, '+', null, { shiftKey: true });
    check('no tanks: nothing to open, "+" is left alone', e.clicks.length === 0 && !prevented);
  } catch (err) {
    out['harness error: ' + err.message] = false;
  }
  process.stdout.write(JSON.stringify(out));
})();
