"""Browser end-to-end test of the web UI with the dummy video backend (run with: pytest -m e2e).

Needs: the `server` and `dev` extras, a Chromium/Chrome (UGOKU_E2E_CHROME=/path/to/chrome, or Playwright's own browser), the detector models
(`ugoku models fetch ctd bubble`) and the sample pages. Skipped when any of these is missing.
"""
import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
sync_api = pytest.importorskip("playwright.sync_api")


def _models_ok() -> bool:
    try:
        from ugoku.models import model_path

        model_path("ctd")
        model_path("bubble")
        return True
    except Exception:  # noqa: BLE001
        return False


def _sample_pages(n_per_work: int = 2) -> list[Path]:
    out = []
    for w in sorted((ROOT / "samples").glob("*/pages")):
        out += sorted(w.glob("*.png"))[:n_per_work]
    return out


pytest.importorskip("fastapi")
if not _models_ok() or not _sample_pages():
    pytest.skip("detector models or sample pages missing", allow_module_level=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, data: Path, port: int):
        self.data, self.port = data, port
        self.proc = None

    def start(self):
        code = "import sys; from ugoku.cli import main; sys.exit(main(sys.argv[1:]))"
        self.proc = subprocess.Popen([sys.executable, "-c", code, "serve", "--data", str(self.data), "--port", str(self.port), "--cpu-workers", "2"],
                                     stdout=subprocess.DEVNULL, stderr=open(self.data.parent / "server.log", "ab"))
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                urllib.request.urlopen(self.url + "/api/projects", timeout=2).read()
                return self
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("server did not start")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)  # by PID of our own child only
            self.proc.wait()

    def api(self, path):
        return json.loads(urllib.request.urlopen(self.url + path, timeout=10).read())


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "data", _free_port()).start()
    yield s
    s.kill()


@pytest.fixture
def browser():
    with sync_api.sync_playwright() as p:
        exe = os.environ.get("UGOKU_E2E_CHROME")
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


def _zip(pages: list[Path], dst: Path) -> Path:
    with zipfile.ZipFile(dst, "w") as z:
        for i, p in enumerate(pages):
            z.write(p, f"{i + 1:03d}.png")
    return dst


def _wait_done(server, pid, timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = server.api(f"/api/projects/{pid}")
        if s["state"] in ("done", "failed"):
            return s
        time.sleep(2)
    raise AssertionError("timeout")


def test_upload_progress_edit_player_exports(server, browser, tmp_path):
    pages = _sample_pages(1)
    z = _zip(pages, tmp_path / "pages.zip")
    pg = browser.new_page()
    pg.goto(server.url)
    pg.set_input_files("#file", str(z))
    pg.click("#go")
    pg.wait_for_selector("#upmsg.err")  # the rights box is required
    pg.check("#rights")
    pg.click("#go")
    pg.wait_for_url("**/#/project/*")
    pid = pg.url.split("/project/")[1].split("/")[0]
    pg.wait_for_selector("#open", timeout=420_000)  # progress is streamed over SSE; the player link shows when done
    s = server.api(f"/api/projects/{pid}")
    assert s["state"] == "done" and len(s["pages"]) == len(pages)
    # stage editing: change the action of the first animated panel and rebuild
    first = s["pages"][0]["page"]
    pg.goto(f"{server.url}/#/project/{pid}/page/{first}")
    pg.wait_for_selector("#save")
    ta = pg.query_selector("textarea")
    if ta:
        ta.fill("The character nods twice, slowly. Starts nearly still, moves, returns to the starting pose.")
    pg.click("#save")
    pg.wait_for_selector("#open", timeout=420_000)
    assert _wait_done(server, pid)["state"] == "done"
    # player: ready, seek, Range
    pg.goto(f"{server.url}/p/{pid}/out/page.html?p={first}&auto=0")
    pg.wait_for_function("window.__ready === true", polling=500, timeout=90_000)
    pg.evaluate("__at(2)")
    assert pg.evaluate("document.querySelectorAll('img').length") > 1
    vids = json.loads(urllib.request.urlopen(f"{server.url}/p/{pid}/out/data.json").read())["pages"][0]["panels"]
    clip = next(p["mp4"] for p in vids if p.get("mp4"))
    req = urllib.request.Request(f"{server.url}/p/{pid}/out/{clip}", headers={"Range": "bytes=0-99"})
    r = urllib.request.urlopen(req)
    assert r.status == 206 and len(r.read()) == 100
    # exports
    for path, magic in ((f"/api/projects/{pid}/export/gallery.zip", b"PK"), (f"/api/projects/{pid}/export/page/{first}.html", b"<!doctype"),
                        (f"/api/projects/{pid}/export/page/{first}.mp4", b"\x00\x00\x00")):
        data = urllib.request.urlopen(server.url + path).read()
        assert data[:len(magic)].lower() == magic.lower() and len(data) > 1000
    assert zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(f"{server.url}/api/projects/{pid}/export/clips.zip").read())).namelist()


def test_killed_server_resumes(server, tmp_path):
    z = _zip(_sample_pages(1), tmp_path / "p.zip")
    import http.client
    import uuid

    b = uuid.uuid4().hex
    body = (f'--{b}\r\nContent-Disposition: form-data; name="rights"\r\n\r\ntrue\r\n--{b}\r\nContent-Disposition: form-data; name="file"; filename="p.zip"\r\n'
            f'Content-Type: application/zip\r\n\r\n').encode() + z.read_bytes() + f"\r\n--{b}--\r\n".encode()
    c = http.client.HTTPConnection("127.0.0.1", server.port)
    c.request("POST", "/api/projects", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    pid = json.loads(c.getresponse().read())["id"]
    t0 = time.time()
    while time.time() - t0 < 120 and not any(j for j in [server.api(f"/api/projects/{pid}")["stages"]["prep"]] if j["running"] or j["done"]):
        time.sleep(0.3)
    server.kill()  # a worker dies mid-run
    server.start()
    assert _wait_done(server, pid, 600)["state"] == "done"
