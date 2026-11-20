// What every benchmark page shares: posting JSON to the site, and the site's own telemetry, which carries
// nothing typed and must pass untouched while the character operates.
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return response.json();
}
function beacon(event) {
  navigator.sendBeacon("/api/beacon", JSON.stringify({ event, page: location.pathname, t: Date.now() }));
}
beacon("view");
document.addEventListener("click", () => beacon("click"), true);
