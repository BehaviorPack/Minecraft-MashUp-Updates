import requests
import json
import time
import os
import zipfile
import io
import datetime

from pf import LoginWithCustomId, GetEntityToken, PLAYFAB_SESSION

# ── Config ────────────────────────────────────────────────────────────────────

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # optional

PLAYFAB_CATALOG_URL = f"https://{os.getenv('TITLE_ID','20ca2').lower()}.playfabapi.com/Catalog/GetPublishedItem"

ASSET_HEADERS = {
    "Connection": "keep-alive",
    "User-Agent": "libhttpclient/1.0.0.0",
}

UUIDS = [
    "523e1367-4547-409d-9f71-d11bdf93c382",
    "ef8b11e0-7b10-41ac-81f4-2a4b02d25727",
    "157e815f-46ce-41c2-baa1-e702b9d15648",
    "1a4a7be1-b4c4-4f19-8924-99eff553b029",
    "805c7b50-8bf5-42b1-9b09-01818023f5af",
    "4d7590d6-8f7f-4f53-989a-2df76b6b015b",
    "d858a668-0db7-4440-aa9c-cf1aab5e7553",
    "fb104838-8501-4325-866a-afb0ce5fc605",
    "a55390b7-33e6-45f9-8032-9037f464b27a",
    "42df0f5d-7433-4253-91cf-766e83298afd",
    "32a36bc7-a6f0-4375-9d6a-7c7fac83c46e",
    "1814821e-1786-44a0-99f5-a950222fb6b3",
    "959fd880-2357-4353-a8bd-286ae90efb7f",
    "5a56435d-689c-46aa-a685-073750bff4d4",
    "a9725e69-66b2-4002-805a-c26867fe467b",
    "32c1ef67-3cb2-4094-bd0d-92eb55b5ad75",
    "713a0d2f-29ff-4d5f-a2f6-aee8bdac0583",
    "395deae8-dbe5-41da-b6cd-11657ba639c0",
    "09e4d8b4-e02f-4c8b-a982-aefc3e393cde",
    "aedadd28-b7bb-46b4-a367-f31e203a7c77",
    "15412212-f877-4ae5-aaf4-1416803ad5bb",
    "167a11c3-759b-4eaa-b898-5d85dbbd7f5c",
    "4e3f765b-4893-486f-908e-09ebd55719d2",
    "bb984328-6fa2-4774-aa1d-237709c02ffc",
    "d03b426e-91aa-4761-b19e-cad5dfd3258b",
    "352c2fdd-1261-4135-9b5c-5a4ed7a640f9",
    "1767460d-9f27-4fd6-8d06-af9a3daa61b0",
    "eeda8413-2ffb-48e4-b622-5a21bc494482",
]

DELAY_SECONDS = 3

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(BASE_DIR, "data")
SAVE_DIR     = os.path.join(DATA_DIR, "responses")
PACKS_DIR    = os.path.join(DATA_DIR, "packs")
CHANGES_DIR  = os.path.join(DATA_DIR, "changes")
STATE_PATH   = os.path.join(DATA_DIR, "state.json")

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    keepchars = (" ", ".", "_", "-", "'", "™", "®")
    return "".join(c for c in name if c.isalnum() or c in keepchars).rstrip()


def fetch_item(uuid: str) -> dict | None:
    payload = {"ItemId": uuid, "ETag": ""}
    headers = {
        "Accept": "*/*",
        "accept-language": "en-US",
        "cache-control": "public",
        "content-type": "application/json",
    }
    try:
        r = PLAYFAB_SESSION.post(PLAYFAB_CATALOG_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"  [ERROR] Request failed for {uuid}: {exc}")
        return None


def extract_item(response: dict) -> dict | None:
    try:
        return response["data"]["Item"]
    except (KeyError, TypeError):
        return None


def get_primary_zip_url(item: dict) -> str | None:
    for content in item.get("Contents", []):
        if content.get("Type") == "resourcebinary":
            return content.get("Url")
    return None


def collect_existing_files(pack_dir: str) -> set:
    existing = set()
    if not os.path.exists(pack_dir):
        return existing
    for root, _, files in os.walk(pack_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), pack_dir).replace("\\", "/")
            existing.add(rel)
    return existing


def load_file_snapshot(pack_dir: str) -> set:
    snapshot_path = pack_dir.rstrip("/\\") + ".files.json"
    if not os.path.exists(snapshot_path):
        return set()
    with open(snapshot_path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_file_snapshot(pack_dir: str, files: list) -> None:
    snapshot_path = pack_dir.rstrip("/\\") + ".files.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(sorted(files), f, indent=2)


def read_manifest_engine(pack_dir: str) -> str | None:
    for root, _, files in os.walk(pack_dir):
        if "manifest.json" in files:
            try:
                with open(os.path.join(root, "manifest.json"), "r", encoding="utf-8") as f:
                    data = json.load(f)
                header = data.get("header", {})
                v = header.get("min_engine_version") or header.get("base_game_version")
                if v:
                    return ".".join(str(x) for x in v)
            except Exception:
                pass
    return None


def download_and_extract(primary_url: str, pack_dir: str) -> list:
    from urllib.parse import urlparse
    host = urlparse(primary_url).netloc
    headers = {**ASSET_HEADERS, "Host": host}

    print(f"  [DOWNLOAD] Fetching primary.zip from {host}...")
    try:
        r = requests.get(primary_url, headers=headers, timeout=120)
        r.raise_for_status()
    except Exception as exc:
        print(f"  [ERROR] Failed to download primary.zip: {exc}")
        return []

    os.makedirs(pack_dir, exist_ok=True)
    extracted_files = []

    with zipfile.ZipFile(io.BytesIO(r.content)) as primary_zip:
        ppack_names = sorted(n for n in primary_zip.namelist() if n.endswith(".zip"))
        print(f"  [EXTRACT] Found inner zips: {ppack_names}")

        for ppack_name in ppack_names:
            ppack_data = primary_zip.read(ppack_name)
            with zipfile.ZipFile(io.BytesIO(ppack_data)) as ppack_zip:
                for member in ppack_zip.namelist():
                    if member.endswith("/"):
                        continue
                    dest_path = os.path.join(pack_dir, member.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with ppack_zip.open(member) as src, open(dest_path, "wb") as dst:
                        dst.write(src.read())
                    extracted_files.append(member)

    print(f"  [EXTRACT] Extracted {len(extracted_files)} files to {pack_dir}/")
    return extracted_files


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get_pack_version(item: dict) -> str:
    """Extract version string from packIdentity."""
    dp = item.get("DisplayProperties", {})
    pack_ids = dp.get("packIdentity", [])
    if pack_ids:
        return pack_ids[0].get("version", "unknown")
    return "unknown"


def write_change_file(pack_name: str, version: str, changes: dict) -> str:
    """
    Write {pack-name}-{ver}.json containing added/removed/modified files.
    Returns the relative path to the file for README linking.
    """
    os.makedirs(CHANGES_DIR, exist_ok=True)
    fname = f"{pack_name}-{version}.json"
    path = os.path.join(CHANGES_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(changes, f, indent=2, sort_keys=True)
    return f"data/changes/{fname}"


def compute_diff(old_files: set, new_files: set) -> dict:
    return {
        "added":   sorted(new_files - old_files),
        "removed": sorted(old_files - new_files),
    }


def iso_to_discord_ts(iso: str) -> str:
    try:
        import re
        normalized = re.sub(
            r"\.(\d+)",
            lambda m: "." + m.group(1).ljust(6, "0")[:6],
            iso.replace("Z", "+00:00"),
        )
        dt   = datetime.datetime.fromisoformat(normalized)
        unix = int(dt.timestamp())
        return f"<t:{unix}:R>"
    except Exception:
        return iso


def send_webhook(embed: dict, new_files: list = None) -> None:
    if not WEBHOOK_URL:
        return
    payload = {"content": None, "embeds": [embed], "attachments": []}
    if new_files:
        sorted_files = sorted(new_files)
        header = f"### New Files Found ({len(sorted_files)}):\n"
        body = ""
        for f in sorted_files:
            line = f"- {f}\n"
            if len(header) + len(body) + len(line) > 1900:
                remaining = len(sorted_files) - body.count("\n")
                body += f"*... and {remaining} more*"
                break
            body += line
        payload["content"] = header + body
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print(f"  [WEBHOOK] status {r.status_code}")
    except Exception as exc:
        print(f"  [WEBHOOK] Failed: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    os.makedirs(PACKS_DIR, exist_ok=True)
    os.makedirs(CHANGES_DIR, exist_ok=True)

    print("Authenticating with PlayFab...")
    login = LoginWithCustomId()
    playfab_id = login.get("PlayFabId", "unknown")
    print(f"Logged in as PlayFabId: {playfab_id}")

    entity = GetEntityToken(playfab_id, "master_player_account")
    print(f"Token expires: {entity.get('TokenExpiration', '')}\n")

    state = load_state()
    summary = []  # for README table

    for i, uuid in enumerate(UUIDS):
        print(f"[{i+1}/{len(UUIDS)}] Checking UUID: {uuid}")

        response = fetch_item(uuid)
        if response is None:
            print("  Skipping (request failed).")
            continue

        item = extract_item(response)
        if item is None:
            print("  No item found in response.")
            continue

        title       = item.get("Title", {}).get("NEUTRAL", uuid)
        safe_name   = safe_filename(title)
        json_path   = os.path.join(SAVE_DIR, safe_name + ".json")
        pack_dir    = os.path.join(PACKS_DIR, safe_name)
        primary_url = get_primary_zip_url(item)
        version     = get_pack_version(item)
        etag        = item.get("ETag", "")

        prev = state.get(uuid, {})
        prev_etag    = prev.get("etag")
        prev_version = prev.get("version")

        is_new     = not prev
        is_changed = (prev_etag != etag) or (prev_version != version)

        change_rel_path = None
        new_files = []

        if is_new or is_changed:
            if is_new:
                print(f"  New item '{title}' — saving.")
            else:
                print(f"  Change detected in '{title}' ({prev_version} -> {version}).")

            # Save raw response
            os.makedirs(SAVE_DIR, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=4, ensure_ascii=False)

            before = load_file_snapshot(pack_dir)
            all_extracted = []
            if primary_url:
                all_extracted = download_and_extract(primary_url, pack_dir)
                new_files = [f for f in all_extracted if f not in before]
                save_file_snapshot(pack_dir, all_extracted)

            # Build changes JSON
            added   = sorted(new_files)
            removed = []
            if before and all_extracted:
                removed = sorted(before - set(all_extracted))

            changes = {
                "pack":         title,
                "uuid":         uuid,
                "version":      version,
                "previous_version": prev_version,
                "etag":         etag,
                "detected_at":  datetime.datetime.utcnow().isoformat() + "Z",
                "added":        added,
                "removed":      removed,
                "total_files":  len(all_extracted),
                "engine":       read_manifest_engine(pack_dir),
            }

            change_rel_path = write_change_file(safe_name, version, changes)

            embed = {
                "title": title,
                "description": item.get("Description", {}).get("NEUTRAL", "")[:400],
                "color": 7418248,
                "fields": [
                    {"name": "Version", "value": f"`{version}`", "inline": True},
                    {"name": "Engine",  "value": f"`{changes['engine'] or 'N/A'}`", "inline": True},
                    {"name": "Added",   "value": f"`{len(added)}`", "inline": True},
                    {"name": "Removed", "value": f"`{len(removed)}`", "inline": True},
                ],
            }
            send_webhook(embed, new_files or None)
        else:
            print(f"  No changes for '{title}'.")
            change_rel_path = prev.get("change_file")

        # Update state entry
        state[uuid] = {
            "title":        title,
            "safe_name":    safe_name,
            "version":      version,
            "etag":         etag,
            "last_checked": datetime.datetime.utcnow().isoformat() + "Z",
            "change_file":  change_rel_path,
            "pack_dir":     f"data/packs/{safe_name}",
        }

        summary.append(state[uuid])

        if i < len(UUIDS) - 1:
            time.sleep(DELAY_SECONDS)

    save_state(state)

    # Also emit a summary JSON for the README builder
    with open(os.path.join(DATA_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print("\nDone.")


if __name__ == "__main__":
    main()