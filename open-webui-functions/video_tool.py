"""
title: Video
author: Ralph Benitez
version: 1.0.0
description: Make a short narrated video of a website and hand back the link, so an assistant can produce one instead of describing how.
requirements: httpx
"""
# This tool holds no secret, deliberately, for the same reason schedules_tool
# does not: every route it calls is user scoped by auth.current_user, which
# reads X-User-Email and nothing else. So this sends the caller's own email and
# has no field in which a credential could sit.
#
# That argument holds only while every call lands under /api/video-jobs. See
# _job_path: a job id chosen by a model becomes part of a URL, and httpx
# resolves dot segments before sending, so an unchecked id is a way to call a
# different endpoint of the tasks service as this person.
import os
import uuid

import httpx
from pydantic import BaseModel, Field

BASE_PATH = "/api/video-jobs"


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        #: Capture drives a headless browser over several pages of a live
        #: site, and the service caps that at 90 seconds of its own. This has
        #: to outlast it or the tool reports a failure for work that finished.
        timeout_seconds: int = Field(default=120)

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------- plumbing

    def _email(self, __user__: dict) -> str:
        """Who is asking, from Open WebUI rather than from a parameter.

        Never a method argument: a model that could name the user could make
        videos as somebody else. Never raises either, because __user__ comes
        from another process's plumbing and is not always the dict it is
        annotated as.
        """
        user = __user__ if isinstance(__user__, dict) else {}
        return str(user.get("email") or "").strip()

    def _job_path(self, job_id, suffix: str = "") -> str:
        """The path for one video, or "" when the id is not an id.

        Job ids are UUIDs and the service parses every one of them, so a
        value that is not a UUID was never valid. Rebuilt from the parsed
        value rather than echoed, so only the canonical form reaches a URL and
        "../connections/github" cannot leave /api/video-jobs carrying this
        person's own email.
        """
        try:
            parsed = uuid.UUID(str(job_id))
        except Exception:                                   # noqa: BLE001
            return ""
        return BASE_PATH + "/" + str(parsed) + suffix

    async def _call(self, method: str, path: str, email: str,
                    json_body: dict = None):
        """One request as this person. Returns (ok, data) or (False, sentence).

        Never raises, and never includes the exception text: an httpx error
        carries the request URL, and this project has leaked a token that way
        once.
        """
        url = self.valves.tasks_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(
                    timeout=self.valves.timeout_seconds) as client:
                response = await client.request(
                    method, url,
                    headers={"X-User-Email": email},
                    json=json_body)
                # Not `>= 400`: a redirect is not success, and reading one as
                # success would report a video that was never made.
                if not response.is_success:
                    return False, self._refusal(response)
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach the video service just now."

    def _refusal(self, response) -> str:
        """What the server said, when it said something a person can act on.

        Every refusal here is a fact somebody can do something about: video
        switched off, a site this platform will not reach, the daily limit,
        a capture that timed out. Collapsing those into one shrug is the
        difference between explaining a limit and looking broken.

        Only below 500 and only a string `detail`: a 500 body is where an
        unhandled exception surfaces, and neither it nor the request URL
        belongs in a reply.
        """
        if response.status_code < 500:
            try:
                body = response.json()
            except ValueError:
                body = {}
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        if response.status_code == 503:
            return "Video generation is switched off on this platform."
        if response.status_code == 504:
            return "That site took too long to capture. It may be slow or very large."
        if response.status_code == 502:
            return "That site could not be captured."
        return "The video service could not do that just now."

    # ---------------------------------------------------------------- doing

    async def make_video(self, url: str, title: str = "",
                         description: str = "", __user__: dict = {}) -> str:
        """
        Make a short narrated video of a website and start it rendering.

        Give the address of a page that is publicly reachable. The platform
        opens the site itself and captures the pages, so the person does not
        have to upload or screenshot anything.

        `description` is optional. Left empty, the video is scripted from what
        the pages actually show, which is usually better than a guess.

        Rendering takes minutes. Tell them it is rendering and use
        video_status when they ask again; do not describe what is in the
        video, because you have not seen it.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell who is asking, so I did not start a video."
        address = (url or "").strip()
        if not address:
            return "I need the address of the site to film."

        ok, draft = await self._call(
            "POST", BASE_PATH + "/draft", email,
            {"title": (title or "").strip() or "Video",
             "prompt": (description or "").strip()})
        if not ok:
            return draft

        job_id = str((draft or {}).get("id") or "")
        path = self._job_path(job_id)
        if not path:
            return "The video service answered with something I could not use."

        ok, _ = await self._call(
            "POST", self._job_path(job_id, "/capture-from-url"), email,
            {"url": address})
        if not ok:
            # The draft is left behind on purpose: it costs nothing, it is
            # inert until something queues it, and deleting it here would
            # throw away a capture that may have half succeeded.
            return _

        ok, queued = await self._call(
            "POST", self._job_path(job_id, "/queue"), email)
        if not ok:
            return queued

        ahead = (queued or {}).get("queue_position")
        said = ("Filming " + address + " now, and it is rendering. This takes "
                "a few minutes.")
        if isinstance(ahead, int) and ahead > 0:
            said += " There are %d ahead of it." % ahead
        return said + "\nAsk me for the video and I will check on it. Its id is " + job_id

    async def video_status(self, job_id: str, __user__: dict = {}) -> str:
        """
        Say how a video is getting on, and give the link once it is done.

        Use the id from make_video, or the one from list_my_videos.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell who is asking."
        path = self._job_path(job_id)
        if not path:
            return "That is not a video id."

        ok, job = await self._call("GET", path, email)
        if not ok:
            return job

        status = str((job or {}).get("status") or "")
        title = str((job or {}).get("title") or "The video")
        if (job or {}).get("output_available") and (job or {}).get("share_url"):
            return title + " is ready.\nWatch it here: " + str(job["share_url"])
        if status == "done":
            # Rendered, but the share link needs a setting this platform may
            # not have. Saying "ready" with nowhere to go is worse than this.
            return title + " has finished rendering. It is on the Video page."
        if status == "failed":
            why = str((job or {}).get("error") or "").strip()
            return title + " failed." + (" " + why if why else "")
        ahead = (job or {}).get("queue_position")
        if status == "queued" and isinstance(ahead, int) and ahead > 0:
            return title + " is waiting, with %d ahead of it." % ahead
        return title + " is " + (status or "still working") + "."

    async def list_my_videos(self, __user__: dict = {}) -> str:
        """
        List this person's videos, newest first, with what each one is doing.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell who is asking."
        ok, data = await self._call("GET", BASE_PATH, email)
        if not ok:
            return data
        videos = (data or {}).get("videos") or []
        if not videos:
            return "There are no videos yet."
        lines = []
        for video in videos[:10]:
            if not isinstance(video, dict):
                continue
            lines.append("%s: %s (id %s)" % (
                str(video.get("title") or "Untitled"),
                str(video.get("status") or "unknown"),
                str(video.get("id") or "")))
        return "\n".join(lines) if lines else "There are no videos yet."
