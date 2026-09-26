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

  // Suggest a web address from the page name until the webmaster types one themselves.
  var slugSource = document.querySelector("[data-slug-source]");
  var slugTarget = document.querySelector("[data-slug-target]");
  if (slugSource && slugTarget) {
    var touched = slugTarget.value !== "";
    slugTarget.addEventListener("input", function () { touched = true; });
    slugSource.addEventListener("input", function () {
      if (touched) return;
      slugTarget.value = slugSource.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
        .replace(/&/g, "-en-").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "");
    });
  }

  // Focal point: tap the photo; the dot, the hidden fields and the crop previews follow.
  var picker = document.querySelector(".focus-picker");
  if (picker) {
    var photo = picker.querySelector(".focus-photo");
    var dot = picker.querySelector(".focus-dot");
    var setFocus = function (x, y) {
      x = Math.round(Math.min(100, Math.max(0, x)));
      y = Math.round(Math.min(100, Math.max(0, y)));
      picker.elements.x.value = x;
      picker.elements.y.value = y;
      dot.style.left = x + "%";
      dot.style.top = y + "%";
      picker.querySelectorAll(".focus-preview img").forEach(function (img) {
        img.style.objectPosition = x + "% " + y + "%";
      });
    };
    photo.addEventListener("click", function (e) {
      var r = photo.querySelector("img").getBoundingClientRect();
      setFocus((e.clientX - r.left) / r.width * 100, (e.clientY - r.top) / r.height * 100);
    });
    picker.querySelector("[data-focus-reset]").addEventListener("click", function () { setFocus(50, 50); });
  }

  // No file attachments in rich text: photos go in a photo album instead.
  document.addEventListener("trix-file-accept", function (e) { e.preventDefault(); });
})();
