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

  function labelled(label, control) {
    var wrap = document.createElement("label");
    wrap.className = "field";
    wrap.appendChild(text("span", "field-label", label));
    wrap.appendChild(control);
    return wrap;
  }

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  // The title the server would make from the file name (catalog_sync.display_name):
  // "02-python_functions.mp4" -> "Python Functions".
  function titleFromName(name) {
    var stem = name.replace(/\.[^.]+$/, "");
    var numbered = /^(\d{1,3})[-_. ]+(.+)$/.exec(stem);
    if (numbered) stem = numbered[2];
    stem = stem.replace(/[-_]+/g, " ").trim().replace(/([A-Za-z])(?=\d)/g, "$1 ");
    return stem.split(/\s+/).filter(Boolean).map(function (word) {
      return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(" ").slice(0, 200);
  }

  var zone = document.querySelector(".dropzone[data-upload-url]");
  if (!zone) return;

  var input = zone.querySelector("[data-upload-input]");
  var list = document.querySelector("[data-upload-list]");
  var actions = document.querySelector("[data-upload-actions]");
  var publish = document.querySelector("[data-upload-publish]");
  var startButton = document.querySelector("[data-upload-start]");
  var clearButton = document.querySelector("[data-upload-clear]");
  var url = zone.getAttribute("data-upload-url");
  var maxBytes = parseInt(zone.getAttribute("data-max-bytes"), 10) || 0;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  var allowed = /\.(mp4|m4v|pdf|jpe?g|png|webp)$/i;
  // One job per file in the list. status: ready -> queued -> uploading -> done | failed
  // (failed files can be sent again); "rejected" files were refused here and are never sent.
  var jobs = [];
  var running = false;
  var added = 0;
  var leaving = false;
  var note = null;

  function waiting(job) {
    return job.status === "ready" || job.status === "failed";
  }

  function setState(job, message, cls) {
    job.state.textContent = message;
    job.state.className = (cls || "muted") + " small";
  }

  function lock(job, locked) {
    job.title.disabled = locked;
    job.description.disabled = locked;
    job.remove.hidden = locked;
  }

  function showNote(message, withReload) {
    if (note) note.remove();
    note = text("li", "muted small", message);
    if (withReload) {
      var reload = text("button", "btn btn-small", "Reload the list");
      reload.type = "button";
      reload.addEventListener("click", function () {
        leaving = true;
        window.location.reload();
      });
      note.appendChild(document.createTextNode(" "));
      note.appendChild(reload);
    }
    list.appendChild(note);
  }

  function refresh() {
    var count = jobs.filter(waiting).length;
    actions.hidden = jobs.length === 0;
    startButton.disabled = running || count === 0;
    clearButton.disabled = running;
    startButton.lastElementChild.textContent = running ? "Uploading…" : (count ? "Upload " + plural(count, "file") : "Upload");
  }

  function removeJob(job) {
    job.row.remove();
    jobs.splice(jobs.indexOf(job), 1);
    refresh();
  }

  function addJob(file) {
    var row = document.createElement("li");
    var head = document.createElement("div");
    head.className = "upload-head";
    head.appendChild(text("span", "upload-name", file.name + " · " + formatSize(file.size)));
    var state = text("span", "muted small", "");
    head.appendChild(state);
    var remove = text("button", "btn btn-small", "Remove");
    remove.type = "button";
    head.appendChild(remove);
    row.appendChild(head);

    var title = document.createElement("input");
    title.type = "text";
    title.maxLength = 200;
    title.value = title.placeholder = titleFromName(file.name);
    var description = document.createElement("textarea");
    description.rows = 2;
    description.maxLength = 2000;
    description.placeholder = "Optional: what students will find in it";
    var fields = document.createElement("div");
    fields.className = "upload-fields";
    fields.appendChild(labelled("Title", title));
    fields.appendChild(labelled("Description", description));

    var job = { file: file, row: row, state: state, remove: remove, title: title, description: description, bar: null };
    remove.addEventListener("click", function () { removeJob(job); });
    if (!allowed.test(file.name)) {
      job.status = "rejected";
      setState(job, "Not a supported file (MP4, PDF, JPG, PNG or WebP).", "fail");
    } else if (maxBytes && file.size > maxBytes) {
      job.status = "rejected";
      setState(job, "Larger than the upload limit (" + formatSize(maxBytes) + ").", "fail");
    } else {
      job.status = "ready";
      setState(job, "ready");
      row.appendChild(fields);
    }
    list.insertBefore(row, note);
    jobs.push(job);
  }

  function enqueue(files) {
    var before = jobs.length;
    for (var i = 0; i < files.length; i++) addJob(files[i]);
    refresh();
    var first = jobs.slice(before).filter(function (job) { return job.status === "ready"; })[0];
    if (first) first.title.focus();
  }

  function finished() {
    running = false;
    refresh();
    var left = jobs.filter(waiting).length;
    if (added && !left) {
      showNote("All files were added. Reloading the list…", false);
      leaving = true;
      window.setTimeout(function () { window.location.reload(); }, 1500);
    } else if (added) {
      showNote(plural(added, "file") + " added. Fix or remove the others and press Upload again, or reload to see the new items.", true);
    }
  }

  function next() {
    var job = jobs.filter(function (j) { return j.status === "queued"; })[0];
    if (!job) {
      finished();
      return;
    }
    job.status = "uploading";
    var params = "?filename=" + encodeURIComponent(job.file.name);
    var title = job.title.value.trim();
    var description = job.description.value.trim();
    if (title) params += "&title=" + encodeURIComponent(title);
    if (description) params += "&description=" + encodeURIComponent(description);
    if (job.publish) params += "&publish=true";
    if (!job.bar) {
      job.bar = document.createElement("progress");
      job.bar.max = 100;
      job.row.appendChild(job.bar);
    }
    job.bar.value = 0;
    setState(job, "uploading…");

    var xhr = new XMLHttpRequest();
    xhr.open("PUT", url + params);
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) {
        job.bar.value = Math.round((event.loaded / event.total) * 100);
        setState(job, formatSize(event.loaded) + " of " + formatSize(event.total));
      }
    };
    xhr.upload.onload = function () {
      setState(job, "checking the file…");
    };
    xhr.onload = function () {
      var body = {};
      try { body = JSON.parse(xhr.responseText); } catch (e) { body = {}; }
      if (xhr.status >= 200 && xhr.status < 300 && body.ok) {
        job.status = "done";
        added++;
        job.bar.remove();
        job.bar = null;
        if (body.title) job.title.value = body.title;
        var label = body.status === "published" ? "added and published" : "added as draft";
        var problems = body.problems && body.problems.length;
        if (problems) label += " — " + body.problems.join(" ");
        setState(job, label, problems ? "fail" : "ok");
      } else {
        // Upload errors are {"error": "..."}; other API errors {"error": {"message": "..."}}.
        var message = typeof body.error === "string" ? body.error : (body.error && body.error.message);
        if (xhr.status === 414) message = "The title or description is too long.";
        failed(job, message || ("Upload failed (HTTP " + xhr.status + ")."));
      }
      next();
    };
    xhr.onerror = function () {
      failed(job, "Upload failed: the connection to the server was lost.");
      next();
    };
    xhr.send(job.file);
  }

  function failed(job, message) {
    job.status = "failed";
    if (job.bar) {
      job.bar.remove();
      job.bar = null;
    }
    setState(job, message, "fail");
    lock(job, false);
  }

  function start() {
    if (running) return;
    var send = jobs.filter(waiting);
    if (!send.length) return;
    if (note) {
      note.remove();
      note = null;
    }
    var publishNow = !!(publish && publish.checked);
    send.forEach(function (job) {
      job.status = "queued";
      job.publish = publishNow;
      lock(job, true);
      setState(job, "waiting");
    });
    running = true;
    refresh();
    next();
  }

  startButton.addEventListener("click", start);
  clearButton.addEventListener("click", function () {
    if (running) return;
    jobs.slice().forEach(removeJob);
    if (note) {
      note.remove();
      note = null;
    }
  });
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
  // Typed titles and descriptions would be lost by leaving the page.
  window.addEventListener("beforeunload", function (event) {
    if (!leaving && (running || jobs.some(waiting))) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
