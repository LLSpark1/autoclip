# AutoClip Studio

Drop in long videos (podcasts, streams, interviews) and get vertical clips for
TikTok, YouTube Shorts and Reels, with captions, a headline, and a post caption.

## Install

Download the installer from the **Releases** page:
- **Windows:** `AutoClip-Studio-Setup.exe`. If Windows shows "Windows protected your PC",
  click **More info → Run anyway**.
- **Mac (Apple Silicon):** `AutoClip-Studio-Mac.dmg`. Drag the app into Applications.
  The first time you open it, macOS may block it: go to **System Settings → Privacy &
  Security** and click **Open Anyway**.

## Use

1. Drop in one or more videos.
2. Click **Make my clips**.

Clips are saved in the **AutoClip Clips** folder in your home folder. The first run
downloads the speech model (about 500 MB), so it takes a little longer.

**Settings**
- **Split screen:** the speaker on top and a satisfying video (slime, parkour gameplay)
  underneath, which keeps viewers watching. Use footage you own or royalty-free footage.
- **Anthropic API key** (from console.anthropic.com): much better clip picks, headlines
  and captions. It costs a few cents per hour of video.

Only clip videos you own or have permission to use.

## Run from source (developers)

```bash
pip install -r requirements.txt
python app.py
```
