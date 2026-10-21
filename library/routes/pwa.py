"""Install + offline support: the web app manifest and the service worker.

Both are served from the app root (not /static/) so that behind the dashboard
proxy they live at /library/manifest.webmanifest and /library/sw.js, and the
service worker's scope covers the whole /library/ mount.
"""

import os

from flask import Blueprint, current_app, jsonify, request, send_from_directory, url_for

pwa_blueprint = Blueprint("pwa", __name__)


@pwa_blueprint.route("/manifest.webmanifest")
def manifest():
    root = request.script_root + "/"
    icon = lambda name: url_for("static", filename=f"icons/{name}")  # noqa: E731
    response = jsonify({
        "name": "Library",
        "short_name": "Library",
        "description": "Your ebooks, catalogued and readable anywhere.",
        "start_url": root,
        "scope": root,
        "display": "standalone",
        "background_color": "#f6f4ef",
        "theme_color": "#f6f4ef",
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": icon("icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    })
    response.mimetype = "application/manifest+json"
    return response


@pwa_blueprint.route("/sw.js")
def service_worker():
    response = send_from_directory(
        os.path.join(current_app.static_folder, "js"), "sw.js",
        mimetype="application/javascript",
    )
    # Browsers must always re-check the worker so updates roll out promptly.
    response.headers["Cache-Control"] = "no-cache"
    return response
