// On the hosted copy: who is signed in, with links to sign out and (for admins) to manage users.
// The local `explore` has no sign-in service, so /auth/me is missing there and nothing is shown.
async function account() {
  const el = document.getElementById("account");
  if (!el) return;
  let me = null;
  try {
    const res = await fetch("auth/me", { cache: "no-store" });
    if (res.ok && (res.headers.get("Content-Type") || "").includes("json")) me = await res.json();
  } catch { /* local: no service */ }
  if (!me) return;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  el.innerHTML = `${esc(me.name)}` +
    (me.role === "admin" ? ` · <a href="auth/admin">manage users</a>` : "") +
    ` · <a href="auth/logout">sign out</a>`;
  el.hidden = false;
}
account();
