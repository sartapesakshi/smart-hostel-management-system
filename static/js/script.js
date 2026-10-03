/* =====================================================================
   Smart Hostel Management System - JavaScript
   Plain JavaScript (no framework). Every feature is optional: the server
   re-validates everything, so the app still works if a script fails.
   Sections: 1 layout  2 notifications  3 confirm dialog  4 password toggle
             5 form validation  6 form helpers  7 attendance  8 charts
   ===================================================================== */
(function () {
  "use strict";

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  /* ---------- 1. layout: mobile sidebar, date label, print ---------- */
  var menuToggle = $("#menu-toggle");
  if (menuToggle) {
    menuToggle.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
    $("#sidebar-backdrop").addEventListener("click", function () { document.body.classList.remove("nav-open"); });
  }
  var todayLabel = $("#today-label");
  if (todayLabel) {
    todayLabel.textContent = new Date().toLocaleDateString("en-IN",
      { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }
  $all("[data-print]").forEach(function (button) {
    button.addEventListener("click", function () { window.print(); });
  });

  /* ---------- 2. notifications (toasts) ---------- */
  function dismissToast(toast) {
    toast.classList.add("leaving");
    setTimeout(function () { toast.remove(); }, 260);
  }
  $all(".toast").forEach(function (toast) {
    $(".toast-close", toast).addEventListener("click", function () { dismissToast(toast); });
    // success/info messages vanish by themselves; errors stay until closed
    if (toast.classList.contains("toast-success") || toast.classList.contains("toast-info")) {
      setTimeout(function () { dismissToast(toast); }, 5000);
    }
  });

  /* ---------- 3. confirmation dialog for dangerous actions ---------- */
  var modal = $("#confirm-modal");
  var pendingForm = null;
  function closeModal() { modal.hidden = true; pendingForm = null; }
  if (modal) {
    $all("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        pendingForm = form;
        $("#confirm-message").textContent = form.getAttribute("data-confirm");
        modal.hidden = false;
        $("#confirm-cancel").focus();
      });
    });
    $("#confirm-cancel").addEventListener("click", closeModal);
    $("#confirm-ok").addEventListener("click", function () {
      var form = pendingForm;
      closeModal();
      if (form) { form.submit(); }          // submit() skips the listener above
    });
    modal.addEventListener("click", function (event) { if (event.target === modal) { closeModal(); } });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !modal.hidden) { closeModal(); } });
  }

  /* ---------- 4. show / hide password ---------- */
  var EYE = '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  $all(".toggle-password").forEach(function (button) {
    button.addEventListener("click", function () {
      var input = document.getElementById(button.getAttribute("data-target"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.innerHTML = show ? EYE_OFF : EYE;
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  /* ---------- 5. client-side form validation ---------- */
  var PHONE = /^(\+91|91|0)?[\s-]?[6-9][0-9]{9}$/;

  function setError(field, message) {
    var wrapper = field.closest(".field");
    if (!wrapper) { return; }
    var box = $(".field-error", wrapper);
    if (!message) {
      wrapper.classList.remove("has-error");
      if (box && box.getAttribute("data-js")) { box.remove(); }
      return;
    }
    wrapper.classList.add("has-error");
    if (!box) {
      box = document.createElement("p");
      box.className = "field-error";
      box.setAttribute("data-js", "1");
      wrapper.appendChild(box);
    }
    box.textContent = message;
  }

  function problemWith(field) {
    if (field.disabled || field.type === "hidden" || field.type === "checkbox" || field.type === "radio" ||
        field.readOnly || field.offsetParent === null) { return ""; }
    var value = field.value.trim();
    if (field.required && !value) { return "This field is required."; }
    if (!value) { return ""; }
    if (field.getAttribute("data-pattern") === "phone" && !PHONE.test(value.replace(/\s+/g, " "))) {
      return "Enter a valid 10-digit mobile number.";
    }
    if (field.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value)) { return "Enter a valid email address."; }
    if (field.type === "number") {
      var number = parseFloat(value);
      if (isNaN(number)) { return "Enter a number."; }
      if (field.min !== "" && number < parseFloat(field.min)) { return "Must be at least " + field.min + "."; }
      if (field.max !== "" && number > parseFloat(field.max)) { return "Must be at most " + field.max + "."; }
    }
    if (field.type === "date" && field.max && value > field.max) { return "Date cannot be in the future."; }
    if (field.minLength > 0 && value.length < field.minLength) { return "Enter at least " + field.minLength + " characters."; }
    return "";
  }

  $all("form[data-validate]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var firstBad = null;
      $all("input, select, textarea", form).forEach(function (field) {
        var message = problemWith(field);
        // password confirmation (setup page and change-password form)
        var pair = { confirm: "password", confirm_password: "new_password" }[field.name];
        if (!message && pair && field.value && field.value !== (form.elements[pair] || {}).value) {
          message = "Passwords do not match.";
        }
        setError(field, message);
        if (message && !firstBad) { firstBad = field; }
      });
      if (firstBad) {
        event.preventDefault();
        firstBad.focus();
      }
    });
    form.addEventListener("input", function (event) { setError(event.target, ""); });
  });

  /* ---------- 6. helpers for specific forms ---------- */
  // date of birth -> age preview
  $all("[data-age-target]").forEach(function (input) {
    var target = document.getElementById(input.getAttribute("data-age-target"));
    function update() {
      if (!input.value) { target.value = ""; return; }
      var born = new Date(input.value), now = new Date();
      var age = now.getFullYear() - born.getFullYear();
      var m = now.getMonth() - born.getMonth();
      if (m < 0 || (m === 0 && now.getDate() < born.getDate())) { age--; }
      target.value = (age >= 0 && age < 120) ? age + " years" : "";
    }
    input.addEventListener("input", update);
    update();
  });

  // room type -> suggested capacity
  $all("[data-capacity-target]").forEach(function (select) {
    var capacity = document.getElementById(select.getAttribute("data-capacity-target"));
    var beds = { Single: 1, Double: 2, Triple: 3 };
    select.addEventListener("change", function () {
      if (beds[select.value]) { capacity.value = beds[select.value]; }
      else if (select.value === "Dormitory" && Number(capacity.value) < 4) { capacity.value = 4; }
    });
  });

  // student form: a student who is not Active cannot be given a room
  $all("[data-status-source]").forEach(function (roomSelect) {
    var status = document.getElementById(roomSelect.getAttribute("data-status-source"));
    function update() {
      var active = status.value === "Active";
      roomSelect.disabled = !active;
      if (!active) { roomSelect.value = ""; }
    }
    status.addEventListener("change", update);
    update();
  });

  // fee form: show payment fields only when "already paid" is ticked
  var payNow = document.getElementById("pay_now");
  var payFields = document.getElementById("pay-now-fields");
  if (payNow && payFields) {
    var togglePay = function () { payFields.hidden = !payNow.checked; updateRef(); };
    payNow.addEventListener("change", togglePay);
    togglePay();
  }
  // reference number is required for every method except cash
  var methodSelect = $("[data-ref-toggle]");
  function updateRef() {
    if (!methodSelect) { return; }
    var ref = document.getElementById(methodSelect.getAttribute("data-ref-toggle"));
    ref.required = methodSelect.value !== "Cash";
  }
  if (methodSelect) { methodSelect.addEventListener("change", updateRef); updateRef(); }

  /* ---------- 7. attendance sheet ---------- */
  $all("[data-mark-all]").forEach(function (button) {
    button.addEventListener("click", function () {
      var value = button.getAttribute("data-mark-all");
      $all('#attendance-form tbody tr').forEach(function (row) {
        if (row.style.display === "none") { return; }      // only the students currently shown
        var radio = $('input[value="' + value + '"]', row);
        if (radio) { radio.checked = true; }
      });
    });
  });
  // live search while typing (the server-side search still works on Enter)
  $all("[data-live-filter]").forEach(function (input) {
    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      $all(input.getAttribute("data-live-filter") + " tbody tr").forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().indexOf(needle) === -1 ? "none" : "";
      });
    });
  });

  /* ---------- 8. dashboard charts (Chart.js) ---------- */
  var COLORS = ["#1f5f8b", "#c99a45", "#2c7a58", "#b03a2a", "#6c5ba7", "#2a9d9a", "#8a6d3b", "#4d5d6c"];

  function note(canvasId, text) {
    var box = document.getElementById(canvasId).parentNode;
    box.innerHTML = '<div class="chart-note">' + text + "</div>";
  }
  function total(list) { return list.reduce(function (a, b) { return a + b; }, 0); }

  window.initDashboardCharts = function () {
    var holder = document.getElementById("chart-data");
    if (!holder) { return; }
    var data = JSON.parse(holder.textContent);
    var ids = ["chart-occupancy", "chart-fees", "chart-courses", "chart-attendance"];
    if (!window.Chart) {
      ids.forEach(function (id) {
        note(id, "Charts could not be loaded. Connect to the internet once, or place chart.umd.min.js in static/js (see README).");
      });
      return;
    }
    Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
    Chart.defaults.color = "#566676";
    var common = { responsive: true, maintainAspectRatio: false };
    var axis = { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#edf1f4" } };

    if (total(data.occupancy.occupied) + total(data.occupancy.available) === 0) {
      note("chart-occupancy", "No rooms added yet.");
    } else {
      new Chart(document.getElementById("chart-occupancy"), {
        type: "bar",
        data: { labels: data.occupancy.labels, datasets: [
          { label: "Occupied beds", data: data.occupancy.occupied, backgroundColor: COLORS[0], borderRadius: 4 },
          { label: "Available beds", data: data.occupancy.available, backgroundColor: "#a9c7dc", borderRadius: 4 }] },
        options: Object.assign({}, common, { scales: { x: { stacked: true, grid: { display: false } }, y: Object.assign({ stacked: true }, axis) } })
      });
    }

    if (total(data.fees.values) === 0) {
      note("chart-fees", "No payments recorded in the last 6 months.");
    } else {
      new Chart(document.getElementById("chart-fees"), {
        type: "bar",
        data: { labels: data.fees.labels, datasets: [{ label: "Collected (Rs)", data: data.fees.values, backgroundColor: COLORS[1], borderRadius: 4 }] },
        options: Object.assign({}, common, {
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return " Rs " + Number(c.parsed.y).toLocaleString("en-IN"); } } } },
          scales: { x: { grid: { display: false } }, y: axis } })
      });
    }

    if (data.courses.values.length === 0) {
      note("chart-courses", "No active students yet.");
    } else {
      new Chart(document.getElementById("chart-courses"), {
        type: "doughnut",
        data: { labels: data.courses.labels, datasets: [{ data: data.courses.values, backgroundColor: COLORS, borderWidth: 2, borderColor: "#fff" }] },
        options: Object.assign({}, common, { cutout: "62%", plugins: { legend: { position: "right" } } })
      });
    }

    if (total(data.attendance.present) + total(data.attendance.absent) === 0) {
      note("chart-attendance", "No attendance marked in the last 7 days.");
    } else {
      new Chart(document.getElementById("chart-attendance"), {
        type: "bar",
        data: { labels: data.attendance.labels, datasets: [
          { label: "Present", data: data.attendance.present, backgroundColor: COLORS[2], borderRadius: 4 },
          { label: "Absent", data: data.attendance.absent, backgroundColor: COLORS[3], borderRadius: 4 }] },
        options: Object.assign({}, common, { scales: { x: { stacked: true, grid: { display: false } }, y: Object.assign({ stacked: true }, axis) } })
      });
    }
  };
})();
