import json
import os
import datetime

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
README     = os.path.join(BASE_DIR, "README.md")

HEADER = (
    "# Minecraft Marketplace Pack Monitor\n\n"
    "Auto-updated by GitHub Actions. Tracks Minecraft Marketplace mash-up packs via the\n"
    "PlayFab `Catalog/GetPublishedItem` endpoint.\n\n"
    "**Last updated:** `{ts}`\n\n"
    "## Tracked Packs\n\n"
    "| Pack | Version | Files | Last Change | Changelog |\n"
    "|------|---------|-------|-------------|-----------|\n"
)

FOOTER = (
    "\n\n## Change Files\n\n"
    "Each `data/changes/{pack-name}-{version}.json` file contains:\n\n"
    "```json\n"
    "{\n"
    '  "pack": "LittleBigPlanet Mash-up",\n'
    '  "version": "1.0.75",\n'
    '  "added": ["textures/foo.png"],\n'
    '  "removed": [],\n'
    '  "engine": "1.21.0"\n'
    "}\n"
    "```\n\n"
    "## How it works\n\n"
    "1. GitHub Action runs every 6 hours\n"
    "2. Authenticates with PlayFab using repository secrets\n"
    "3. Fetches each tracked UUID from the catalog\n"
    "4. Compares ETag + version to last run\n"
    "5. If changed: downloads `primary.zip`, extracts, diffs file list\n"
    "6. Writes `data/changes/{pack}-{ver}.json` and updates this README\n"
    "7. Commits everything back to the repo\n"
)


def main():
    if not os.path.exists(STATE_PATH):
        print("No state.json — nothing to do.")
        return

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    rows = []
    for uuid, entry in sorted(state.items(), key=lambda kv: kv[1].get("title", "")):
        title       = entry.get("title", "?")
        version     = entry.get("version", "?")
        change_file = entry.get("change_file")

        file_count = 0
        last_change = "-"
        if change_file and os.path.exists(os.path.join(BASE_DIR, change_file)):
            with open(os.path.join(BASE_DIR, change_file), "r", encoding="utf-8") as cf:
                cdata = json.load(cf)
            file_count = cdata.get("total_files", 0)
            last_change = cdata.get("detected_at", "-")[:10]

        link = f"[`{os.path.basename(change_file)}`]({change_file})" if change_file else "-"

        rows.append(f"| {title} | `{version}` | {file_count} | {last_change} | {link} |")

    content = HEADER.format(ts=datetime.datetime.utcnow().isoformat() + "Z")
    content += "\n".join(rows) if rows else "| _none yet_ | | | | |"
    content += FOOTER

    with open(README, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"README updated with {len(rows)} packs.")


if __name__ == "__main__":
    main()