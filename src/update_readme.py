import json
import os
import datetime

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
README     = os.path.join(BASE_DIR, "README.md")

HEADER = """# Minecraft Marketplace Pack Monitor

Auto-updated by GitHub Actions. Tracks Minecraft Marketplace mash-up packs via the
PlayFab `Catalog/GetPublishedItem` endpoint.

**Last updated:** `{ts}`

## Tracked Packs

| Pack | Version | Files | Last Change | Changelog |
|------|---------|-------|-------------|-----------|
"""

FOOTER = """

## Change Files

Each `data/changes/{pack-name}-{version}.json` file contains:

```json
{
  "pack": "LittleBigPlanet™ Mash-up",
  "version": "1.0.75",
  "added": ["textures/foo.png"],
  "removed": [],
  "engine": "1.21.0"
}