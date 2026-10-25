(function () {
  "use strict";

  var header = document.querySelector(".site-header");
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");

  function setNavOpen(open) {
    document.body.classList.toggle("nav-open", open);
    if (toggle) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      setNavOpen(!document.body.classList.contains("nav-open"));
    });

    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setNavOpen(false);
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setNavOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.matchMedia("(min-width: 720px)").matches) {
        setNavOpen(false);
      }
    });
  }

  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener("click", function (e) {
      var id = this.getAttribute("href");
      if (!id || id === "#") return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      var offset = header ? header.offsetHeight + 8 : 0;
      var top = target.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top: top, behavior: "smooth" });
      history.replaceState(null, "", id);
    });
  });

  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.getAttribute("data-copy");
      var el = id ? document.getElementById(id) : null;
      if (!el) return;
      var text = (el.textContent || "").trim();
      var label = btn.querySelector(".copy-label");

      function markCopied() {
        btn.classList.add("copied");
        btn.setAttribute("aria-label", "Copied");
        if (label) label.textContent = "Copied";
        window.setTimeout(function () {
          btn.classList.remove("copied");
          btn.setAttribute("aria-label", btn.getAttribute("data-aria") || "Copy");
          if (label) label.textContent = "Copy";
        }, 1800);
      }

      if (!btn.getAttribute("data-aria")) {
        btn.setAttribute("data-aria", btn.getAttribute("aria-label") || "Copy");
      }

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(markCopied).catch(fallback);
      } else {
        fallback();
      }

      function fallback() {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand("copy");
          markCopied();
        } catch (_err) {
          /* ignore */
        }
        document.body.removeChild(ta);
      }
    });
  });
})();
