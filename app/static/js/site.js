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

// "More makers" strip: arrow buttons for mouse users (touch screens swipe it).
document.querySelectorAll(".strip-nav").forEach(function (nav) {
  var strip = document.getElementById(nav.dataset.strip);
  if (!strip) return;
  var buttons = nav.querySelectorAll(".strip-arrow");
  function update() {
    var max = strip.scrollWidth - strip.clientWidth - 2;
    buttons[0].disabled = strip.scrollLeft <= 2;
    buttons[1].disabled = strip.scrollLeft >= max;
    nav.hidden = max <= 0;  // everything fits: no arrows needed
  }
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var card = strip.querySelector(".maker-card");
      var step = card ? card.getBoundingClientRect().width + 16 : strip.clientWidth * 0.8;
      strip.scrollBy({ left: Number(btn.dataset.dir) * step, behavior: "smooth" });
    });
  });
  strip.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
  update();
});
