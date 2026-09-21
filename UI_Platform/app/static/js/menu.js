document.addEventListener("DOMContentLoaded", function () {
  var menu = document.getElementById("appMenu");
  if (!menu) return;
  // Menu shrinks and stays fixed once any module has been selected
  // (i.e. whenever we're not on the upload landing page).
  var onUploadPage = document.body.getAttribute("data-page") === "upload";
  if (!onUploadPage) {
    menu.classList.add("collapsed");
    menu.addEventListener("mouseenter", function () { menu.classList.remove("collapsed"); });
    menu.addEventListener("mouseleave", function () { menu.classList.add("collapsed"); });
  }
});
