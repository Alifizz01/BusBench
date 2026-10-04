"""BusBench Studio - a native window around the local REST API.

The API server runs in the background of this process (or an already
running one is reused); the window is only a client of it.
"""
import json
import threading
import urllib.request

from busbench.server import PORT


def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as r:
            return json.load(r).get("ok", False)
    except OSError:
        return False


class _Bridge:
    """The one thing the window does outside the API: native Save dialogs."""

    def save_file(self, name: str, text: str):
        import webview
        path = webview.windows[0].create_file_dialog(webview.SAVE_DIALOG, save_filename=name)
        if not path:
            return None
        path = path if isinstance(path, str) else path[0]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path


def main(port: int = PORT) -> None:
    import webview
    if not _alive(port):
        from busbench.server import make_server
        threading.Thread(target=make_server(port).serve_forever, daemon=True).start()
    webview.create_window("BusBench Studio", f"http://127.0.0.1:{port}/", width=1480, height=920,
                          min_size=(1100, 700), background_color="#EDF0F4", js_api=_Bridge())
    webview.start()


if __name__ == "__main__":
    main()
