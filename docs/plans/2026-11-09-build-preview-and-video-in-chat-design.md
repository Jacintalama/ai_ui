# A finished build or video shows in the main chat (2026-11-09)

## The ask

Lukas, standup: "it should give the link or ideally the preview", and "the
video would be next, to just show the preview ... so it waits for it to be
finished or where it is working on it". Plus "small things to make it smooth
around the edges".

## What happens today (measured on production, 2026-11-09)

One real build from the main chat (task 72854246, about 40 seconds, $0.05):

1. The app built and its preview URL answers 200.
2. The chat ended with "kilometers-miles-converter-2c21 is built." and no
   panel and no link, for 3 minutes afterwards and after a reload.
3. The saved message holds `[aiui-artifact]: #app/<slug>`. The rendered page
   holds neither that nor a preview URL. The served script matches main.
4. After yes to `create_app`, the turn stopped again on `build_status`.
5. No video has been made in 14 days, so that path has never run for real.

## Causes

1. `aiuiWatchBuilds` looks for artifacts in `thread.innerHTML`. A declared
   artifact is a markdown link reference definition, which the parser
   consumes, so it can never be in the rendered page. It worked while replies
   carried a link; #127 and #129 removed the last one.
2. The panel drawn when the watcher sees the build finish is lost to the soft
   reload that follows (`aiuiCloseWith`), and nothing can redraw it. The same
   is true of the video player.
3. `aiuiWatchVideos` is only reached after `if (!fresh.length) return`, so a
   chat with a video and no build is never watched.
4. `build_status` and `video_status` have no verb the classifier knows, so
   they default to write and ask for approval.
5. The model is asked to copy the `[aiui-artifact]` line into its reply.
   Nothing checks that it did. The build in (1) was only watched because the
   accidental `build_status` question printed the task id. Removing that
   question without (5) would leave the chat blind.

## Decisions

1. **The page reads the saved message, not the rendered one.** One chat fetch
   when the thread has changed and settled, cached, and every panel redrawn
   from the cache on each scan so a discarded one comes back. Rendered-HTML
   scanning stays for messages from before markers existed.
2. **A panel sits in the reply that declared it**, not under whatever the last
   message is now, falling back to the last reply if that row cannot be found.
3. **The service guarantees the marker, not the model.** After a main chat
   turn, any `[aiui-artifact]` line from this turn's tool results that the
   answer lacks is added under it. Main chat only: Discord and Slack have no
   markdown that hides the line.
4. **The video watcher runs on every chat**, the video tool declares its id
   like a build does, and a finished video is redrawn from the saved message.
5. **`build_status` and `video_status` are pinned reads.**
6. **`create_app` and `make_video` ask in a sentence** built only from the
   call's own arguments, with the whole description.

## Testing

Unit tests for the marker guarantee and the classifier. The real section of
`integrations-ui.js` run under node for the saved scan, as
`test_chat_build_watcher.py` does. Then the branch script injected into the
real site in a real browser (no deploy needed): the existing test chat, which
shows no panel today, must show one. After merge: one real build, one real
video, and the video tool's row updated through Open WebUI's API.
