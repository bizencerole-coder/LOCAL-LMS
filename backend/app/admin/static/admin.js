// Campus LMS staff dashboard: confirmation prompts and file uploads with progress.
// No inline scripts (the pages' Content-Security-Policy forbids them).
(function () {
  "use strict";

  // Forms with data-confirm ask before submitting (delete, archive, ...).
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var question = form.getAttribute && form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) {
      event.preventDefault();
    }
  });

  function formatSize(bytes) {
    var units = ["B", "KB", "MB", "GB"];
    var value = bytes;
    var unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit++;
    }
    return (unit ? value.toFixed(1) : value) + " " + units[unit];
  }

  function text(tag, cls, value) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    node.textContent = value;
    return node;
  }

  var zone = document.querySelector(".dropzone[data-upload-url]");
  if (!zone) return;

  var input = zone.querySelector("[data-upload-input]");
  var publish = zone.querySelector("[data-upload-publish]");
  var list = document.querySelector("[data-upload-list]");
  var url = zone.getAttribute("data-upload-url");
  var maxBytes = parseInt(zone.getAttribute("data-max-bytes"), 10) || 0;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  var allowed = /\.(mp4|m4v|pdf|jpe?g|png|webp)$/i;
  var queue = [];
  var busy = false;
  var finishedAny = false;

  function addRow(file) {
    var row = document.createElement("li");
    var name = text("span", "", file.name + " (" + formatSize(file.size) + ")");
    var state = text("span", "muted small", "waiting");
    var bar = document.createElement("progress");
    bar.max = 100;
    bar.value = 0;
    row.appendChild(name);
    row.appendChild(state);
    row.appendChild(bar);
    list.appendChild(row);
    return { row: row, state: state, bar: bar };
  }

  function fail(item, message) {
    item.state.textContent = message;
    item.state.className = "fail small";
    item.bar.remove();
  }

  function next() {
    if (busy) return;
    var job = queue.shift();
    if (!job) {
      if (finishedAny) {
        var done = text("li", "muted small", "All uploads finished. Reloading the list…");
        list.appendChild(done);
        window.setTimeout(function () { window.location.reload(); }, 1500);
      }
      return;
    }
    busy = true;
    var params = "?filename=" + encodeURIComponent(job.file.name) + (publish && publish.checked ? "&publish=true" : "");
    var xhr = new XMLHttpRequest();
    xhr.open("PUT", url + params);
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("Accept", "application/json");
    job.item.state.textContent = "uploading…";
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) {
        job.item.bar.value = Math.round((event.loaded / event.total) * 100);
        job.item.state.textContent = formatSize(event.loaded) + " of " + formatSize(event.total);
      }
    };
    xhr.upload.onload = function () {
      job.item.state.textContent = "checking the file…";
    };
    xhr.onload = function () {
      busy = false;
      var body = {};
      try { body = JSON.parse(xhr.responseText); } catch (e) { body = {}; }
      if (xhr.status >= 200 && xhr.status < 300 && body.ok) {
        finishedAny = true;
        job.item.bar.remove();
        var label = body.status === "published" ? "added and published" : "added as draft";
        if (body.problems && body.problems.length) label += " — " + body.problems.join(" ");
        job.item.state.textContent = label;
        job.item.state.className = (body.problems && body.problems.length ? "fail" : "ok") + " small";
      } else {
        // Upload errors are {"error": "..."}; other API errors {"error": {"message": "..."}}.
        var message = typeof body.error === "string" ? body.error : (body.error && body.error.message);
        fail(job.item, message || ("Upload failed (HTTP " + xhr.status + ")."));
      }
      next();
    };
    xhr.onerror = function () {
      busy = false;
      fail(job.item, "Upload failed: the connection to the server was lost.");
      next();
    };
    xhr.send(job.file);
  }

  function enqueue(files) {
    for (var i = 0; i < files.length; i++) {
      var file = files[i];
      var item = addRow(file);
      if (!allowed.test(file.name)) {
        fail(item, "Not a supported file (MP4, PDF, JPG, PNG or WebP).");
        continue;
      }
      if (maxBytes && file.size > maxBytes) {
        fail(item, "Larger than the upload limit (" + formatSize(maxBytes) + ").");
        continue;
      }
      queue.push({ file: file, item: item });
    }
    next();
  }

  input.addEventListener("change", function () {
    enqueue(input.files);
    input.value = "";
  });
  ["dragenter", "dragover"].forEach(function (type) {
    zone.addEventListener(type, function (event) {
      event.preventDefault();
      zone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    zone.addEventListener(type, function (event) {
      event.preventDefault();
      zone.classList.remove("dragging");
    });
  });
  zone.addEventListener("drop", function (event) {
    if (event.dataTransfer && event.dataTransfer.files) enqueue(event.dataTransfer.files);
  });
  window.addEventListener("beforeunload", function (event) {
    if (busy || queue.length) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
