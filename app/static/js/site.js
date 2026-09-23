// Click-to-load video (§8): no request to YouTube/Vimeo until the visitor asks for it.
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".video-play");
  if (!btn) return;
  var box = btn.closest(".video");
  var iframe = document.createElement("iframe");
  iframe.src = box.dataset.embed;
  iframe.title = box.dataset.title || "Video";
  iframe.allow = "autoplay; fullscreen; picture-in-picture; encrypted-media";
  iframe.allowFullscreen = true;
  box.replaceChildren(iframe);
});
