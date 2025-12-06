import { api } from '../core/api.js';

export function showMunin() {
    // Set the cookie
    api("/munin/", "GET", {}, () => {
        // Redirect to munin
        window.open("/admin/munin/index.html", "_blank");
    });
}
