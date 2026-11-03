/*
 * Shared client-side Gregorian <-> Jalali (Persian/Shamsi) conversion and
 * calendar widget.
 *
 * This is the ONLY place the conversion algorithm is implemented in
 * JavaScript -- every date picker in the app (the header's global date
 * selector, the working-date "choose date" screens, deposit/seal date
 * fields, and the report date-range pickers) loads this file and calls
 * JalaliCalendar.mount(...) instead of re-implementing calendar math.
 *
 * The conversion algorithm (Gregorian <-> Jalali via the 33-year leap
 * cycle) is the same standard algorithm used by jdatetime and the
 * jalaali-js/moment-jalaali libraries. It runs client-side only for
 * building the calendar UI; the value actually submitted to the server
 * is always the Gregorian ISO date (yyyy-mm-dd), so the Django/Python
 * side (apps/core/jalali.py, using jdatetime) remains the single source
 * of truth for any conversion that matters for business logic.
 */
(function (global) {
  "use strict";

  var breaks = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
    1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178
  ];

  // Integer division truncated toward zero (NOT Math.floor -- the
  // reference jalaali-js algorithm below depends on truncating
  // division; some intermediate values here go negative, and floor
  // division gives a different, wrong result for those).
  function div(a, b) { return ~~(a / b); }
  function mod(a, b) { return a - div(a, b) * b; }

  function jalCal(jy) {
    var bl = breaks.length, gy = jy + 621, leapJ = -14, jp = breaks[0],
        jm, jump, leap, n, i;
    if (jy < jp || jy >= breaks[bl - 1]) {
      throw new Error("Invalid Jalali year " + jy);
    }
    for (i = 1; i < bl; i += 1) {
      jm = breaks[i];
      jump = jm - jp;
      if (jy < jm) { break; }
      leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4);
      jp = jm;
    }
    n = jy - jp;
    leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
    if (mod(jump, 33) === 4 && jump - n === 4) { leapJ += 1; }
    var leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
    var march = 20 + leapJ - leapG;
    if (jump - n < 6) { n = n - jump + div(jump, 33) * 33; }
    leap = mod(mod(n + 1, 33) - 1, 4);
    if (leap === -1) { leap = 4; }
    return { leap: leap, gy: gy, march: march };
  }

  function g2d(gy, gm, gd) {
    var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4)
      + div(153 * mod(gm + 9, 12) + 2, 5)
      + gd - 34840408;
    d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
    return d;
  }

  function d2g(jdn) {
    var j, i, gd, gm, gy;
    j = 4 * jdn + 139361631;
    j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
    i = div(mod(j, 1461), 4) * 5 + 308;
    gd = div(mod(i, 153), 5) + 1;
    gm = mod(div(i, 153), 12) + 1;
    gy = div(j, 1461) - 100100 + div(8 - gm, 6);
    return { gy: gy, gm: gm, gd: gd };
  }

  function j2d(jy, jm, jd) {
    var r = jalCal(jy);
    return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
  }

  function d2j(jdn) {
    var gy = d2g(jdn).gy, jy = gy - 621, r, jdn1f, k, jm, jd;
    r = jalCal(jy);
    jdn1f = g2d(gy, 3, r.march);
    k = jdn - jdn1f;
    if (k >= 0) {
      if (k <= 185) {
        jm = 1 + div(k, 31);
        jd = mod(k, 31) + 1;
        return { jy: jy, jm: jm, jd: jd };
      }
      k -= 186;
    } else {
      jy -= 1;
      k += 179;
      r = jalCal(jy);
      // leap === 0 means jy is a leap (366-day) Jalali year -- see jalCal's
      // return-value convention above.
      if (r.leap === 0) { k += 1; }
    }
    jm = 7 + div(k, 30);
    jd = mod(k, 30) + 1;
    return { jy: jy, jm: jm, jd: jd };
  }

  function toJalali(gy, gm, gd) {
    var j = d2j(g2d(gy, gm, gd));
    return [j.jy, j.jm, j.jd];
  }

  function toGregorian(jy, jm, jd) {
    var g = d2g(j2d(jy, jm, jd));
    return [g.gy, g.gm, g.gd];
  }

  function jalaliMonthLength(jy, jm) {
    if (jm <= 6) { return 31; }
    if (jm <= 11) { return 30; }
    // leap === 0 means jy is a leap (366-day) Jalali year, giving Esfand 30 days.
    return jalCal(jy).leap === 0 ? 30 : 29;
  }

  function pad2(n) { return n < 10 ? "0" + n : "" + n; }

  function isoFromGregorian(gy, gm, gd) {
    return gy + "-" + pad2(gm) + "-" + pad2(gd);
  }

  function jalaliStrFromParts(jy, jm, jd) {
    return jy + "/" + pad2(jm) + "/" + pad2(jd);
  }

  var MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
  ];

  // Gregorian JS Date.getDay(): 0=Sunday..6=Saturday. The app's week
  // header is Saturday-first (ش ی د س چ پ ج), matching the Jalali week.
  function weekdayOfJalali(jy, jm, jd) {
    var g = toGregorian(jy, jm, jd);
    var jsDate = new Date(g[0], g[1] - 1, g[2]);
    return (jsDate.getDay() + 1) % 7;
  }

  /*
   * Mounts a Jalali calendar picker onto a "display + hidden panel"
   * DOM structure. `opts`:
   *   toggle, panel, title, daysEl, prevBtn, nextBtn  -- required elements
   *   initialIso  -- "yyyy-mm-dd" Gregorian starting value
   *   onSelect(isoString)  -- called with the Gregorian ISO date chosen
   */
  function mount(opts) {
    var parts = opts.initialIso.split("-").map(Number);
    var g = toJalali(parts[0], parts[1], parts[2]);
    var selectedY = g[0], selectedM = g[1], selectedD = g[2];
    var viewY = selectedY, viewM = selectedM;

    function render() {
      opts.title.textContent = MONTH_NAMES[viewM - 1] + " " + viewY;
      opts.daysEl.innerHTML = "";

      var leadingBlanks = weekdayOfJalali(viewY, viewM, 1);
      var daysInMonth = jalaliMonthLength(viewY, viewM);

      for (var i = 0; i < leadingBlanks; i += 1) {
        opts.daysEl.appendChild(document.createElement("span"));
      }

      for (var d = 1; d <= daysInMonth; d += 1) {
        (function (day) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = day;
          btn.className = "global-date__day";
          if (day === selectedD && viewM === selectedM && viewY === selectedY) {
            btn.classList.add("is-selected");
          }
          btn.addEventListener("click", function () {
            selectedY = viewY;
            selectedM = viewM;
            selectedD = day;
            var gSel = toGregorian(selectedY, selectedM, selectedD);
            var iso = isoFromGregorian(gSel[0], gSel[1], gSel[2]);
            opts.onSelect(iso, jalaliStrFromParts(selectedY, selectedM, selectedD));
          });
          opts.daysEl.appendChild(btn);
        })(d);
      }
    }

    opts.prevBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      viewM -= 1;
      if (viewM < 1) { viewM = 12; viewY -= 1; }
      render();
    });

    opts.nextBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      viewM += 1;
      if (viewM > 12) { viewM = 1; viewY += 1; }
      render();
    });

    render();

    return {
      resetToSelected: function () { viewY = selectedY; viewM = selectedM; render(); },
      render: render
    };
  }

  /*
   * Parses a "YYYY/MM/DD" Jalali string typed by the user into a Gregorian
   * ISO date (yyyy-mm-dd). Returns null if the text isn't a valid Jalali
   * date, so callers can leave navigation alone rather than sending a
   * bad value to the server.
   */
  function parseJalaliToIso(text) {
    var parts = (text || "").trim().split("/").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) { return null; }
    try {
      var g = toGregorian(parts[0], parts[1], parts[2]);
      return isoFromGregorian(g[0], g[1], g[2]);
    } catch (e) {
      return null;
    }
  }

  /*
   * Wires up every element matching selector (default ".jalali-date-input")
   * as a plain text field that displays/accepts Jalali dates. On change,
   * reads data-nav-template (containing the literal placeholder "__ISO__"),
   * substitutes the Gregorian ISO date the user picked, and navigates
   * there -- used by the report date-range filters, which drive their
   * results purely from the URL's query string rather than a form POST.
   */
  function bindNavInputs(selector) {
    var inputs = document.querySelectorAll(selector || ".jalali-date-input");
    for (var i = 0; i < inputs.length; i += 1) {
      (function (input) {
        input.addEventListener("change", function () {
          var iso = parseJalaliToIso(input.value);
          if (!iso) { return; }
          var template = input.getAttribute("data-nav-template");
          if (!template) { return; }
          window.location = template.replace("__ISO__", iso);
        });
      })(inputs[i]);
    }
  }

  global.JalaliCalendar = {
    toJalali: toJalali,
    toGregorian: toGregorian,
    isoFromGregorian: isoFromGregorian,
    jalaliStrFromParts: jalaliStrFromParts,
    parseJalaliToIso: parseJalaliToIso,
    bindNavInputs: bindNavInputs,
    MONTH_NAMES: MONTH_NAMES,
    mount: mount
  };
})(window);
