#!/usr/bin/env python3
from scripts.build_site_data import build, POSTS_JSON, REPORTS_JSON, AUDIO_JSON

import asyncio


if __name__ == "__main__":
    asyncio.run(build())
    print("Wrote:", POSTS_JSON, REPORTS_JSON, AUDIO_JSON)
