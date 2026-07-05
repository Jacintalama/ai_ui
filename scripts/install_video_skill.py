"""Install/update the remotion-best-practices skill from its canonical file.

The video pipeline (video_plan.fetch_skill_best_practices) reads the Open WebUI
``skill`` table row with id ``remotion-best-practices`` and injects its content
into the animated/remotion plan prompt and the AI codegen craft. This script
pushes the repo's canonical copy (mcp-servers/tasks/skills/
remotion-best-practices.md) into that row so the file in git and the live
skill stay in step.

Run inside the tasks container (DATABASE_URL is set there):
    docker cp mcp-servers/tasks/skills/remotion-best-practices.md tasks:/tmp/rbp.md
    docker cp scripts/install_video_skill.py tasks:/tmp/install_video_skill.py
    docker exec tasks python3 /tmp/install_video_skill.py /tmp/rbp.md
"""
import asyncio
import os
import sys
import time

import asyncpg

SKILL_ID = "remotion-best-practices"
SKILL_NAME = "Remotion Best Practices"
DESCRIPTION = (
    "Craft and style guide injected into every AI-authored video: Apple-grade "
    "look, required cursor click-through, page transitions, motion, audio and "
    "pacing rules. Edit to change how videos look and feel."
)


async def main(path: str) -> None:
    content = open(path, encoding="utf-8").read().strip()
    if len(content) < 500:
        raise SystemExit(f"refusing to install suspiciously short skill ({len(content)} chars)")
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        now = int(time.time())
        row = await conn.fetchrow("SELECT user_id FROM skill WHERE id = $1", SKILL_ID)
        if row:
            await conn.execute(
                "UPDATE skill SET content = $2, description = $3, is_active = TRUE, "
                "updated_at = $4 WHERE id = $1",
                SKILL_ID, content, DESCRIPTION, now,
            )
            print(f"updated skill {SKILL_ID!r} ({len(content)} chars)")
        else:
            admin = await conn.fetchrow(
                "SELECT id FROM public.\"user\" WHERE role = 'admin' ORDER BY created_at LIMIT 1"
            )
            if not admin:
                raise SystemExit("no admin user found to own the skill row")
            await conn.execute(
                "INSERT INTO skill (id, user_id, name, description, content, is_active, "
                "created_at, updated_at) VALUES ($1, $2, $3, $4, $5, TRUE, $6, $6)",
                SKILL_ID, admin["id"], SKILL_NAME, DESCRIPTION, content, now,
            )
            print(f"created skill {SKILL_ID!r} ({len(content)} chars)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else
                     "mcp-servers/tasks/skills/remotion-best-practices.md"))
