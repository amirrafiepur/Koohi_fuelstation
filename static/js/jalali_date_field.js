/*
 * Attaches the shared Jalali calendar popup (see static/js/jalali.js) to
 * every plain text input carrying the .jalali-date-field class. This is
 * how JalaliDateWidget (apps/core/jalali.py) becomes a full date picker
 * in the browser: the field itself is an ordinary text input so the
 * form still works with no JS at all (the operator can just type
 * "1405/06/23"), and this script layers a click-to-pick calendar on top
 * of it, reusing the same .global-date__panel markup/CSS as the header's
 * global date control so no extra styling is needed anywhere.
 */
(function () {
  "use strict";

  function pad2(n) { return n < 10 ? "0" + n : "" + n; }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }

  function initField(input) {
    if (input.dataset.jalaliBound) { return; }
    input.dataset.jalaliBound = "1";

    var wrapper = document.createElement("div");
    wrapper.className = "global-date jalali-date-field__wrapper";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    var panel = document.createElement("div");
    panel.className = "global-date__panel";
    panel.hidden = true;
    panel.innerHTML =
      '<div class="global-date__panel-header">' +
      '<button type="button" class="global-date__nav" data-role="prev">&#8250;</button>' +
      '<span class="global-date__panel-title" data-role="title"></span>' +
      '<button type="button" class="global-date__nav" data-role="next">&#8249;</button>' +
      "</div>" +
      '<div class="global-date__weekdays">' +
      "<span>ش</span><span>ی</span><span>د</span><span>س</span><span>چ</span><span>پ</span><span>ج</span>" +
      "</div>" +
      '<div class="global-date__days" data-role="days"></div>';
    wrapper.appendChild(panel);

    var initialIso = JalaliCalendar.parseJalaliToIso(input.value) || todayIso();

    var calendar = JalaliCalendar.mount({
      toggle: input,
      panel: panel,
      title: panel.querySelector('[data-role="title"]'),
      daysEl: panel.querySelector('[data-role="days"]'),
      prevBtn: panel.querySelector('[data-role="prev"]'),
      nextBtn: panel.querySelector('[data-role="next"]'),
      initialIso: initialIso,
      onSelect: function (iso, jalaliStr) {
        input.value = jalaliStr;
        panel.hidden = true;
      }
    });

    input.addEventListener("focus", function () {
      var iso = JalaliCalendar.parseJalaliToIso(input.value);
      if (iso) {
        // Resync the calendar's internal selection to whatever the
        // operator typed before opening the popup.
        var wasHidden = panel.hidden;
        panel.hidden = false;
        calendar.resetToSelected();
        panel.hidden = wasHidden;
      }
      panel.hidden = false;
    });

    panel.addEventListener("click", function (e) { e.stopPropagation(); });

    document.addEventListener("click", function (e) {
      if (!wrapper.contains(e.target)) { panel.hidden = true; }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var inputs = document.querySelectorAll(".jalali-date-field");
    for (var i = 0; i < inputs.length; i += 1) {
      initField(inputs[i]);
    }
  });
})();
