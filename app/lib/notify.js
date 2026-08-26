// Thin wrapper around the browser's Notification API.
//
// NOTE — scope: this only fires while the tab is open (it's the plain
// Notification API, not a service-worker Push subscription), so it
// covers "ping me while I'm on the page" but not "wake my phone while
// the browser is closed." True background push needs a service worker
// + VAPID keys + a subscription store on the backend — worth doing as
// a follow-up, kept out of this pass to avoid shipping untested crypto
// plumbing.

export function notificationsSupported() {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notificationPermission() {
  if (!notificationsSupported()) return "unsupported";
  return Notification.permission; // "default" | "granted" | "denied"
}

export async function requestNotificationPermission() {
  if (!notificationsSupported()) return "unsupported";
  if (Notification.permission === "granted" || Notification.permission === "denied") {
    return Notification.permission;
  }
  try {
    return await Notification.requestPermission();
  } catch {
    return "denied";
  }
}

export function notify(title, options) {
  if (!notificationsSupported() || Notification.permission !== "granted") return;
  try {
    new Notification(title, options);
  } catch {
    // Some browsers throw if called outside a user-gesture context in
    // certain states — never let a notification failure break the UI.
  }
}
