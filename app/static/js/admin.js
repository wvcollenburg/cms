(function () {
  var csrf = document.querySelector('meta[name="csrf-token"]').content;
  var MAX = 2400;

  // Shrink photos in the browser before upload (§5): max 2400 px, JPEG. Handles iPhone HEIC too,
  // because the browser decodes it. Falls back to the original file if decoding fails.
  async function shrink(file) {
    try {
      var bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      var scale = Math.min(1, MAX / Math.max(bmp.width, bmp.height));
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      var blob = await new Promise(function (r) { canvas.toBlob(r, "image/jpeg", 0.86); });
      return blob || file;
    } catch (err) {
      return file;
    }
  }

  document.querySelectorAll(".upload").forEach(function (box) {
    var input = box.querySelector("input[type=file]");
    var status = box.querySelector(".upload-status");
    input.addEventListener("change", async function () {
      var files = Array.from(input.files);
      var failed = 0;
      status.classList.remove("error");
      for (var i = 0; i < files.length; i++) {
        status.textContent = files.length > 1
          ? box.dataset.msgProgress.replace("{n}", i + 1).replace("{total}", files.length)
          : box.dataset.msgBusy;
        var fd = new FormData();
        fd.append("file", await shrink(files[i]), (files[i].name || "foto").replace(/\.\w+$/, "") + ".jpg");
        fd.append("csrf_token", csrf);
        try {
          var resp = await fetch(box.dataset.uploadUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": csrf } });
          var data = await resp.json().catch(function () { return {}; });
          if (!resp.ok || !data.ok) { failed++; status.textContent = data.error || box.dataset.msgError; status.classList.add("error"); }
        } catch (err) {
          failed++; status.textContent = box.dataset.msgOffline; status.classList.add("error");
        }
      }
      if (failed === files.length) return;
      var form = box.closest("form") || document.getElementById("block-form");
      if (box.dataset.then === "submit" && form) {
        var stay = document.createElement("input");
        stay.type = "hidden"; stay.name = "then"; stay.value = "stay";
        form.appendChild(stay);
        form.submit();
      } else {
        location.reload();
      }
    });
  });

  // Drag to reorder parts of a page; saved straight away.
  document.querySelectorAll("[data-sortable]").forEach(function (list) {
    if (!window.Sortable || !list.querySelector("[data-id]")) return;
    Sortable.create(list, {
      handle: ".handle", animation: 150,
      onEnd: function () {
        var ids = Array.from(list.querySelectorAll("[data-id]")).map(function (li) { return +li.dataset.id; });
        fetch(list.dataset.orderUrl, {
          method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ ids: ids })
        });
      }
    });
  });

  // Reorder photos in a gallery form; saved with the form.
  document.querySelectorAll("[data-sortable-form]").forEach(function (list) {
    if (window.Sortable) Sortable.create(list, { animation: 150, filter: "input", preventOnFilter: false });
  });

  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  // No file attachments in rich text: photos go in a photo album instead.
  document.addEventListener("trix-file-accept", function (e) { e.preventDefault(); });
})();
