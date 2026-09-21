// Improvement-3: whenever a report/workbook download link is clicked, show a
// "Download in progress" overlay and automatically dismiss it once the file
// has actually finished downloading (rather than just once the browser has
// kicked off a normal navigation-triggered download, whose completion can't
// be observed).
document.addEventListener("DOMContentLoaded", function () {
  var overlay = document.getElementById("downloadProgressOverlay");
  var overlayText = document.getElementById("downloadProgressText");
  if (!overlay) return;

  function showOverlay(label) {
    overlayText.textContent = label || "Download in progress\u2026";
    overlay.classList.remove("d-none");
  }
  function hideOverlay() {
    overlay.classList.add("d-none");
  }

  function filenameFromResponse(resp, fallback) {
    var disposition = resp.headers.get("Content-Disposition") || "";
    var match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    if (match && match[1]) {
      try { return decodeURIComponent(match[1]); } catch (e) { return match[1]; }
    }
    return fallback;
  }

  document.querySelectorAll("a.js-download-file").forEach(function (link) {
    link.addEventListener("click", function (evt) {
      evt.preventDefault();
      var url = link.getAttribute("href");
      var fallbackName = link.getAttribute("data-filename") || "download";
      var label = link.getAttribute("data-loading-label") || "Download in progress\u2026";

      showOverlay(label);

      fetch(url, { credentials: "same-origin" })
        .then(function (resp) {
          if (!resp.ok) throw new Error("Download failed (" + resp.status + ")");
          var filename = filenameFromResponse(resp, fallbackName);
          return resp.blob().then(function (blob) { return { blob: blob, filename: filename }; });
        })
        .then(function (result) {
          var objectUrl = URL.createObjectURL(result.blob);
          var tempLink = document.createElement("a");
          tempLink.href = objectUrl;
          tempLink.download = result.filename;
          document.body.appendChild(tempLink);
          tempLink.click();
          document.body.removeChild(tempLink);
          setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 1000);
        })
        .catch(function (err) {
          alert(err.message || "The download could not be completed.");
        })
        .finally(function () {
          hideOverlay();
        });
    });
  });
});
