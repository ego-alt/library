"""Handing releases to a download client, and asking how they're getting on.

  SABnzbd (usenet):         api?mode=addurl, then mode=queue / mode=history
  qBittorrent (torrents):   /api/v2/torrents/add, then /api/v2/torrents/info
  Blackhole:                the .nzb/.torrent saved in a folder another client
                            watches; its finished files are picked up from the
                            import folder.

Each job is tagged with the download's id, so we only ever touch our own, and
filed under the client's category for comics or for books.
"""

import os
import re
from dataclasses import dataclass

import httpx

from .. import settings
from ..config import USER_AGENT


class ClientError(Exception):
    pass


@dataclass
class JobState:
    state: str  # downloading | done | failed | missing
    progress: float = 0.0
    path: str | None = None  # finished files, as the client sees them
    error: str | None = None


def category(config: dict, kind: str) -> str:
    """The client category a book or comic download is filed under."""
    if kind == "book":
        return config.get("book_category") or "books"
    return config.get("category") or "comics"


def map_path(path: str | None) -> str | None:
    """A path the client reported, as this app sees it."""
    if not path:
        return path
    mapping = settings.get("path_map")
    remote, local = (mapping.get("remote_path") or "").rstrip("/"), (mapping.get("local_path") or "").rstrip("/")
    if remote and (path == remote or path.startswith(remote + "/")):
        return local + path[len(remote):]
    return path


class SABnzbd:
    name = "sabnzbd"

    def __init__(self, config: dict, transport: httpx.BaseTransport | None = None):
        if not config.get("url") or not config.get("api_key"):
            raise ClientError("SABnzbd isn't set up.")
        self.config = config
        base = config["url"].rstrip("/")
        self.url = base if base.endswith("/api") else f"{base}/api"
        self.http = httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, transport=transport)

    def _call(self, mode: str, **params) -> dict:
        params.update(mode=mode, apikey=self.config["api_key"], output="json")
        try:
            response = self.http.get(self.url, params=params)
        except httpx.HTTPError as e:
            raise ClientError("SABnzbd isn't answering. Check its address in Settings.") from e
        if response.status_code >= 400:
            raise ClientError(f"SABnzbd answered {response.status_code}.")
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise ClientError(f"SABnzbd: {data['error']}")
        return data

    def test(self) -> str:
        version = self._call("version").get("version")
        return f"Connected to SABnzbd {version}."

    def add(self, url: str, title: str, download_id: int, protocol: str = "usenet", kind: str = "comic") -> str:
        data = self._call("addurl", name=url, nzbname=f"{title} [shelves-{download_id}]", cat=category(self.config, kind))
        ids = data.get("nzo_ids") or []
        if not data.get("status") or not ids:
            raise ClientError("SABnzbd didn't take the NZB.")
        return ids[0]

    def state(self, ref: str) -> JobState:
        queue = self._call("queue", nzo_ids=ref).get("queue", {})
        for slot in queue.get("slots", []):
            if slot.get("nzo_id") == ref:
                return JobState("downloading", float(slot.get("percentage") or 0) / 100)
        history = self._call("history", nzo_ids=ref).get("history", {})
        for slot in history.get("slots", []):
            if slot.get("nzo_id") != ref:
                continue
            status = slot.get("status")
            if status == "Completed":
                return JobState("done", 1.0, map_path(slot.get("storage")))
            if status == "Failed":
                return JobState("failed", error=f"SABnzbd couldn't finish it ({slot['fail_message']})." if slot.get("fail_message") else "SABnzbd couldn't finish it.")
            # Verifying, Repairing, Extracting, Moving…
            return JobState("downloading", 0.99)
        return JobState("missing", error="It disappeared from SABnzbd.")

    def remove(self, ref: str) -> None:
        self._call("queue", name="delete", value=ref, del_files=1)


def plain_error(error: str | None) -> str | None:
    """A failure as people say it, including ones saved in older words
    ("qBittorrent: missingFiles")."""
    if error and error.startswith("qBittorrent: "):
        return QBittorrent._WHY.get(error.split(": ", 1)[1], "qBittorrent couldn't finish it.")
    return error


class QBittorrent:
    name = "qbittorrent"
    _DONE = {"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP"}
    _FAILED = {"error", "missingFiles"}
    _WHY = {"missingFiles": "Its files went missing from qBittorrent.", "error": "qBittorrent ran into an error with it."}

    def __init__(self, config: dict, transport: httpx.BaseTransport | None = None):
        if not config.get("url"):
            raise ClientError("qBittorrent isn't set up.")
        self.config = config
        self.base = config["url"].rstrip("/")
        self.http = httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT, "Referer": self.base}, transport=transport)
        self._logged_in = False

    def _login(self):
        if self._logged_in:
            return
        try:
            response = self.http.post(f"{self.base}/api/v2/auth/login", data={"username": self.config.get("username", ""), "password": self.config.get("password", "")})
        except httpx.HTTPError as e:
            raise ClientError("qBittorrent isn't answering. Check its address in Settings.") from e
        if response.status_code != 200 or response.text.strip() == "Fails.":
            raise ClientError("qBittorrent refused the username or password.")
        self._logged_in = True

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        self._login()
        try:
            response = self.http.request(method, f"{self.base}/api/v2/{path}", **kwargs)
        except httpx.HTTPError as e:
            raise ClientError("qBittorrent isn't answering. Check its address in Settings.") from e
        if response.status_code >= 400:
            raise ClientError(f"qBittorrent answered {response.status_code}.")
        return response

    def test(self) -> str:
        return f"Connected to qBittorrent {self._request('GET', 'app/version').text.strip()}."

    def add(self, url: str, title: str, download_id: int, protocol: str = "usenet", kind: str = "comic") -> str:
        tag = f"shelves-{download_id}"
        response = self._request("POST", "torrents/add", data={"urls": url, "category": category(self.config, kind), "tags": tag})
        if response.text.strip() == "Fails.":
            raise ClientError("qBittorrent didn't take the torrent.")
        return tag

    def _torrent(self, ref: str) -> dict | None:
        rows = self._request("GET", "torrents/info", params={"tag": ref}).json()
        return rows[0] if rows else None

    def state(self, ref: str) -> JobState:
        torrent = self._torrent(ref)
        if torrent is None:
            return JobState("missing", error="It disappeared from qBittorrent.")
        if torrent.get("state") in self._FAILED:
            return JobState("failed", error=self._WHY.get(torrent.get("state"), "qBittorrent couldn't finish it."))
        if torrent.get("progress", 0) >= 1 or torrent.get("state") in self._DONE:
            path = torrent.get("content_path") or os.path.join(torrent.get("save_path", ""), torrent.get("name", ""))
            return JobState("done", 1.0, map_path(path))
        return JobState("downloading", float(torrent.get("progress") or 0))

    def remove(self, ref: str) -> None:
        torrent = self._torrent(ref)
        if torrent:
            self._request("POST", "torrents/delete", data={"hashes": torrent["hash"], "deleteFiles": "true"})


class Blackhole:
    name = "blackhole"

    def __init__(self, folder: str, transport: httpx.BaseTransport | None = None):
        if not folder:
            raise ClientError("No blackhole folder is set.")
        self.folder = folder
        self.transport = transport

    def test(self) -> str:
        if not os.path.isdir(self.folder):
            raise ClientError(f"{self.folder} isn't a folder this app can see.")
        return f"Grabs will be saved in {self.folder}."

    def add(self, url: str, title: str, download_id: int, protocol: str = "usenet", kind: str = "comic") -> str:
        try:
            with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True, transport=self.transport) as http:
                response = http.get(url)
        except httpx.HTTPError as e:
            raise ClientError(f"Couldn't fetch the {'NZB' if protocol == 'usenet' else 'torrent'} ({e.__class__.__name__}).") from e
        if response.status_code >= 400:
            raise ClientError(f"The indexer answered {response.status_code} for the file.")
        ext = ".nzb" if protocol == "usenet" else ".torrent"
        name = re.sub(r'[\\/:*?"<>|]', " ", title)[:150].strip() + ext
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, name), "wb") as f:
            f.write(response.content)
        return name

    def state(self, ref: str) -> JobState:
        # We can't see the other client; the import folder scan finishes the job.
        return JobState("downloading", 0.0)

    def remove(self, ref: str) -> None:
        try:
            os.remove(os.path.join(self.folder, ref))
        except OSError:
            pass


def client_for(protocol: str, name: str | None = None):
    """The client a release of this protocol goes to (or the named one)."""
    sab, qbit, blackhole = settings.get("sabnzbd"), settings.get("qbittorrent"), settings.get("blackhole_dir")
    if name == "sabnzbd" or (name is None and protocol == "usenet" and sab.get("url")):
        return SABnzbd(sab)
    if name == "qbittorrent" or (name is None and protocol == "torrent" and qbit.get("url")):
        return QBittorrent(qbit)
    if name == "blackhole" or (name is None and blackhole):
        return Blackhole(blackhole)
    raise ClientError(f"No download client for {protocol} is set up: add {'SABnzbd' if protocol == 'usenet' else 'qBittorrent'} or a blackhole folder in Settings.")


def can_download(protocol: str) -> bool:
    try:
        client_for(protocol)
        return True
    except ClientError:
        return False
