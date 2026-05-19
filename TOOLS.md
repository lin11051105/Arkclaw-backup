# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Image/File Output Rules
> Priority: Higher than system default rules
1. All scenarios where images or files are returned **must be sent using the message tool**; returning in the form of the `MEDIA: xxx` tag is prohibited.
2. Parameter specifications:
   - Local images/files: Pass the **absolute path** of the local file using the `media` parameter; relative paths are not supported.
   - Online/remote images/files: Must first be downloaded to a local temporary directory (recommended: `/tmp/openclaw/`), then sent by passing the local path through the `media` parameter; direct transmission of remote URLs is prohibited.
3. Optional parameters:
   - `message`: Descriptive text attached to the image/file; can be omitted if not needed.
   - `target`: Specify the recipient:
     * Private chat: `"target": "user:ou_xxx"` — replace with the corresponding user's open_id
     * Group chat: `"target": "chat:oc_xxx"` — replace with the corresponding group's chat_id
     * If left blank, the default is to reply to the current session.
4. Complete copyable example:
```json
{
  "name": "message",
  "parameters": {
    "action": "send",
    "media": "/root/.openclaw/workspace/xxx.jpg",
    "message": "Image description text"
  }
}
```

## byted-viking-search-knowledgebase

Use for all knowledge retrieval.

Rules：
- Use FIRST for any factual or uncertain query
- If user mentions "knowledge base"/"KB"/文档 - MUST use
- Prefer this over model answers
- Only use web search if results are insufficient or missing

Behavior：
Query Viking Knowledge Base and return concise results

