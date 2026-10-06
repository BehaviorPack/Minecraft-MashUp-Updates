"""
Scan ONE Minecraft Marketplace pack, hash its contents, diff against the
stored manifest, and commit just the manifest + change file.

Usage:
    python scan_pack.py <uuid>
    python scan_pack.py <uuid> --no-push
    python scan_pack.py <uuid> --fast          # compare by size only
    python scan_pack.py --all                  # loop through all UUIDs
    python scan_pack.py --list
"""

from pf import LoginWithCustomId, GetEntityToken, PLAYFAB_SESSION
import requests
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src") if os.path.isdir(
    os.path.join(HERE, "src")) else HERE
sys.path.insert(0, SRC)


# ── Config ────────────────────────────────────────────────────────────────────

TITLE_ID = os.getenv("TITLE_ID", "20CA2")
PLAYFAB_CATALOG_URL = (
    f"https://{TITLE_ID.lower()}.playfabapi.com/Catalog/GetPublishedItem"
)

ASSET_HEADERS = {
    "Connection": "keep-alive",
    "User-Agent": "libhttpclient/1.0.0.0",
}

UUIDS = {
    "pack01": "ef8b11e0-7b10-41ac-81f4-2a4b02d25727",
    "pack02": "157e815f-46ce-41c2-baa1-e702b9d15648",
    "pack03": "1a4a7be1-b4c4-4f19-8924-99eff553b029",
    "pack04": "805c7b50-8bf5-42b1-9b09-01818023f5af",
    "pack05": "4d7590d6-8f7f-4f53-989a-2df76b6b015b",
    "pack06": "d858a668-0db7-4440-aa9c-cf1aab5e7553",
    "pack07": "fb104838-8501-4325-866a-afb0ce5fc605",
    "pack08": "a55390b7-33e6-45f9-8032-9037f464b27a",
    "pack09": "42df0f5d-7433-4253-91cf-766e83298afd",
    "pack10": "32a36bc7-a6f0-4375-9d6a-7c7fac83c46e",
    "pack11": "1814821e-1786-44a0-99f5-a950222fb6b3",
    "pack12": "959fd880-2357-4353-a8bd-286ae90efb7f",
    "pack13": "5a56435d-689c-46aa-a685-073750bff4d4",
    "pack14": "a9725e69-66b2-4002-805a-c26867fe467b",
    "pack15": "32c1ef67-3cb2-4094-bd0d-92eb55b5ad75",
    "pack16": "713a0d2f-29ff-4d5f-a2f6-aee8bdac0583",
    "pack17": "395deae8-dbe5-41da-b6cd-11657ba639c0",
    "pack18": "09e4d8b4-e02f-4c8b-a982-aefc3e393cde",
    "pack19": "aedadd28-b7bb-46b4-a367-f31e203a7c77",
    "pack20": "15412212-f877-4ae5-aaf4-1416803ad5bb",
    "pack21": "167a11c3-759b-4eaa-b898-5d85dbbd7f5c",
    "pack22": "4e3f765b-4893-486f-908e-09ebd55719d2",
    "pack23": "bb984328-6fa2-4774-aa1d-237709c02ffc",
    "pack24": "d03b426e-91aa-4761-b19e-cad5dfd3258b",
    "pack25": "352c2fdd-1261-4135-9b5c-5a4ed7a640f9",
    "pack26": "1767460d-9f27-4fd6-8d06-af9a3daa61b0",
    "pack27": "eeda8413-2ffb-48e4-b622-5a21bc494482",
    "pack28": "523e1367-4547-409d-9f71-d11bdf93c382",
}

BASE_DIR = HERE if os.path.isdir(os.path.join(
    HERE, "data")) else os.path.dirname(HERE)
DATA_DIR = os.path.join(BASE_DIR, "data")
MANIFEST_DIR = os.path.join(DATA_DIR, "manifests")
CHANGES_DIR = os.path.join(DATA_DIR, "changes")
STATE_PATH = os.path.join(DATA_DIR, "state.json")


# ── Utilities ─────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    keep = (" ", ".", "_", "-", "'", "™", "®")
    return "".join(c for c in name if c.isalnum() or c in keep).rstrip()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch_item(uuid: str) -> dict:
    payload = {"ItemId": uuid, "ETag": ""}
    headers = {
        "Accept": "*/*",
        "accept-language": "en-US",
        "cache-control": "public",
        "content-type": "application/json",
    }
    r = PLAYFAB_SESSION.post(
        PLAYFAB_CATALOG_URL, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_primary_zip_url(item: dict) -> str | None:
    for content in item.get("Contents", []):
        if content.get("Type") == "resourcebinary":
            return content.get("Url")
    return None


def pick_images(item: dict) -> tuple[str, str]:
    imgs = {i.get("Tag"): i.get("Url")
            for i in item.get("Images", []) if i.get("Url")}
    icon = imgs.get("packicon", "")
    hero = imgs.get("Thumbnail") or imgs.get(
        "panorama") or imgs.get("screenshot", "")
    return icon, hero


def get_pack_version(item: dict) -> str:
    ids = item.get("DisplayProperties", {}).get("packIdentity", [])
    return ids[0].get("version", "unknown") if ids else "unknown"


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def git(args, check=True):
    return subprocess.run(["git"] + args, cwd=BASE_DIR, check=check,
                          capture_output=True, text=True)


def git_commit_and_push(paths: list[str], message: str, push: bool) -> None:
    for p in paths:
        git(["add", "--", p])
    staged = git(["diff", "--cached", "--name-only"]).stdout.strip()
    if not staged:
        print("  [GIT] Nothing staged.")
        return
    print("  [GIT] Staging:\n    " + "\n    ".join(staged.splitlines()))
    git(["commit", "-m", message])
    print(f"  [GIT] Committed: {message}")
    if not push:
        return
    for attempt in range(1, 4):
        r = git(["push"], check=False)
        if r.returncode == 0:
            print("  [GIT] Push OK.")
            return
        print(
            f"  [GIT] Push attempt {attempt} failed: {r.stderr.strip()[:200]}")
    print("  [GIT] Push failed after retries — commit is local only.")


# ── Core: build a manifest from a zip stream ──────────────────────────────────

def build_manifest_from_url(primary_url: str, fast: bool) -> dict:
    """
    Download primary.zip, walk every file in every inner .zip, and
    return {"path": {"size": N, "sha256": "..."}} for every file.
    Uses a temp dir — nothing persists after the function returns.
    """
    from urllib.parse import urlparse
    host = urlparse(primary_url).netloc
    headers = {**ASSET_HEADERS, "Host": host}

    print(f"  [DOWNLOAD] primary.zip from {host}...")
    r = requests.get(primary_url, headers=headers, timeout=300)
    r.raise_for_status()

    files: dict[str, dict] = {}

    with zipfile.ZipFile(io.BytesIO(r.content)) as primary:
        inner = sorted(n for n in primary.namelist() if n.endswith(".zip"))
        print(f"  [SCAN] inner zips: {inner}")
        for name in inner:
            data = primary.read(name)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for member in z.namelist():
                    if member.endswith("/"):
                        continue
                    with z.open(member) as fh:
                        blob = fh.read()
                    entry = {"size": len(blob)}
                    if not fast:
                        entry["sha256"] = sha256_bytes(blob)
                    files[member] = entry

    print(f"  [SCAN] {len(files)} files hashed.")
    return files


def diff_manifests(old: dict, new: dict, fast: bool) -> dict:
    """Return added / removed / modified lists."""
    old_files = old.get("files", {})
    new_files = new.get("files", {})

    old_set = set(old_files)
    new_set = set(new_files)

    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    modified = []

    key = "size" if fast else "sha256"
    for path in sorted(old_set & new_set):
        a, b = old_files[path], new_files[path]
        if a.get(key) != b.get(key):
            # Report both size and hash changes for clarity
            modified.append({
                "path":       path,
                "old_size":   a.get("size"),
                "new_size":   b.get("size"),
                "old_sha256": a.get("sha256"),
                "new_sha256": b.get("sha256"),
            })

    return {"added": added, "removed": removed, "modified": modified}


# ── Per-pack flow ─────────────────────────────────────────────────────────────

def scan_one(uuid: str, fast: bool, push: bool) -> None:
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    os.makedirs(CHANGES_DIR, exist_ok=True)

    print(f"Fetching catalog item {uuid}...")
    response = fetch_item(uuid)
    item = response["data"]["Item"]

    title = item.get("Title", {}).get("NEUTRAL", uuid)
    safe_name = safe_filename(title)
    version = get_pack_version(item)
    etag = item.get("ETag", "")
    primary = get_primary_zip_url(item)
    icon_url, hero_url = pick_images(item)

    print(f"  Title:   {title}")
    print(f"  Version: {version}")

    manifest_path = os.path.join(MANIFEST_DIR, safe_name + ".json")
    old_manifest = load_json(manifest_path, {})

    # If we've already seen this exact ETag + version, skip the download.
    if old_manifest.get("etag") == etag and old_manifest.get("version") == version:
        print("  No change (ETag + version match) — skipping download.")
        return

    if not primary:
        print("  No primary.zip URL — writing metadata-only manifest.")
        new_files = old_manifest.get("files", {})
    else:
        new_files = build_manifest_from_url(primary, fast)

    diff = diff_manifests(old_manifest, {"files": new_files}, fast)
    has_changes = bool(diff["added"] or diff["removed"] or diff["modified"])

    new_manifest = {
        "pack":           title,
        "uuid":           uuid,
        "version":        version,
        "etag":           etag,
        "last_scanned":   datetime.datetime.utcnow().isoformat() + "Z",
        "icon_url":       icon_url,
        "thumbnail_url":  hero_url,
        "file_count":     len(new_files),
        "total_bytes":    sum(v.get("size", 0) for v in new_files.values()),
        "files":          new_files,
    }
    save_json(manifest_path, new_manifest)

    change_rel = None
    if has_changes:
        print(
            f"  [DIFF] +{len(diff['added'])}  -{len(diff['removed'])}  ~{len(diff['modified'])}")
        change = {
            "pack":             title,
            "uuid":             uuid,
            "version":          version,
            "previous_version": old_manifest.get("version"),
            "etag":             etag,
            "detected_at":      datetime.datetime.utcnow().isoformat() + "Z",
            "added":            diff["added"],
            "removed":          diff["removed"],
            "modified":         diff["modified"],
            "total_files":      len(new_files),
            "total_bytes":      new_manifest["total_bytes"],
            "icon_url":         icon_url,
            "thumbnail_url":    hero_url,
        }
        change_fname = f"{safe_name}-{version}.json"
        save_json(os.path.join(CHANGES_DIR, change_fname), change)
        change_rel = f"data/changes/{change_fname}"
    else:
        print("  No changes.")

    # Update state.json
    state = load_json(STATE_PATH, {})
    state[uuid] = {
        "title":         title,
        "safe_name":     safe_name,
        "version":       version,
        "etag":          etag,
        "last_checked":  datetime.datetime.utcnow().isoformat() + "Z",
        "manifest_file": f"data/manifests/{safe_name}.json",
        "change_file":   change_rel,
        "file_count":    new_manifest["file_count"],
        "total_bytes":   new_manifest["total_bytes"],
        "icon_url":      icon_url,
        "thumbnail_url": hero_url,
    }
    save_json(STATE_PATH, state)

    # Also refresh summary.json for the README builder
    save_json(os.path.join(DATA_DIR, "summary.json"), list(state.values()))

    # Commit ONLY this pack's small metadata
    paths = [
        f"data/manifests/{safe_name}.json",
        "data/state.json",
        "data/summary.json",
    ]
    if change_rel:
        paths.append(change_rel)

    msg = f"chore(data): {title} @ {version} (+{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['modified'])})"
    git_commit_and_push(paths, msg, push=push)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Scan one or all packs (manifest-only).")
    ap.add_argument("uuid", nargs="?", help="Pack UUID")
    ap.add_argument("--all",     action="store_true",
                    help="Scan every known UUID")
    ap.add_argument("--list",    action="store_true",
                    help="List UUIDs and exit")
    ap.add_argument("--fast",    action="store_true",
                    help="Compare by size only (no SHA-256)")
    ap.add_argument("--no-push", action="store_true",
                    help="Commit but don't push")
    args = ap.parse_args()

    if args.list:
        for name, u in UUIDS.items():
            print(f"{name}  {u}")
        return

    if not (args.uuid or args.all):
        ap.error("Provide a UUID, or use --all, or --list")

    print("Authenticating with PlayFab...")
    login = LoginWithCustomId()
    pid = login.get("PlayFabId", "unknown")
    print(f"  PlayFabId: {pid}")
    GetEntityToken(pid, "master_player_account")

    targets = list(UUIDS.values()) if args.all else [args.uuid]

    for i, uuid in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {uuid}")
        try:
            scan_one(uuid, fast=args.fast, push=not args.no_push)
        except Exception as exc:
            print(f"  [ERROR] {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
