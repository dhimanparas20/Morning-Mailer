(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var urlParams = new URLSearchParams(window.location.search);
    var error = urlParams.get("error");
    if (error) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  });
})();
