from __future__ import annotations

import os
import sys
import threading
import webbrowser

import uvicorn


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    host = os.getenv("ATLAS_HOST", "127.0.0.1")
    port = int(os.getenv("ATLAS_PORT", "8000"))
    url = f"http://{host}:{port}"

    print("\n  论点地图 · Argument Atlas")
    print(f"  {url}")
    print("  按 Ctrl+C 停止\n")

    if os.getenv("ATLAS_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
