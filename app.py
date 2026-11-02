#!/usr/bin/env python3
"""AutoClip Studio: drop in a long video, get ready-to-post vertical clips."""
import os
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import gradio as gr

import autoclip

APP_NAME = "AutoClip Studio"
OUTPUT_ROOT = Path.home() / "AutoClip Clips"

LENGTHS = {"Short (15-30s)": (15, 30), "Medium (30-60s)": (30, 60), "Long (60-90s)": (60, 90)}
FRAMING = {"Follow the speaker": "face", "Show full frame": "fit"}


def open_folder(path):
    if platform.system() == "Windows":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", str(path)])


def make(video, topic, count, length, framing, api_key):
    if not video:
        raise gr.Error("Drop a video in first.")
    api_key = (api_key or "").strip()
    autoclip.save_config({"api_key": api_key})

    out_dir = OUTPUT_ROOT / f"{autoclip.slugify(Path(video).stem, 30)}-{datetime.now():%Y%m%d-%H%M%S}"
    min_len, max_len = LENGTHS[length]
    lines, box = [], {}

    def work():
        try:
            box["clips"] = autoclip.make_clips(
                video, out_dir, n=int(count), min_len=min_len, max_len=max_len,
                crop=FRAMING[framing], topic=topic, api_key=api_key, log=lines.append)
        except Exception as e:
            box["error"] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        yield "\n".join(lines[-12:]) or "Starting...", gr.skip(), ""
        time.sleep(0.5)
    if "error" in box:
        yield "Something went wrong: " + box["error"], gr.skip(), ""
        return
    clips = [{"path": str(p), **c} for p, c in box["clips"]]
    yield lines[-1], clips, str(out_dir)


def build_ui():
    with gr.Blocks(title=APP_NAME) as demo:
        gr.Markdown(f"# 🎬 {APP_NAME}\nDrop in a long video. Get clips ready for TikTok, Shorts and Reels.")
        clips_state, folder = gr.State([]), gr.State("")

        with gr.Row(equal_height=False):
            with gr.Column(scale=2, min_width=300):
                video = gr.File(label="Your video", file_types=["video"], type="filepath", height=140)
                topic = gr.Textbox(label="What's it about? (optional)",
                                   placeholder="e.g. business podcast, gaming stream")
                with gr.Accordion("Settings", open=False):
                    count = gr.Slider(1, 10, value=5, step=1, label="How many clips")
                    length = gr.Radio(list(LENGTHS), value="Medium (30-60s)", label="Clip length")
                    framing = gr.Radio(list(FRAMING), value="Follow the speaker", label="Framing",
                                       info="Use 'Show full frame' for gameplay or two people")
                    api_key = gr.Textbox(label="Anthropic API key (for smarter clip picks)",
                                         type="password", placeholder="sk-ant-...",
                                         value=autoclip.load_config().get("api_key", ""),
                                         info="Optional. Get one at console.anthropic.com")
                go = gr.Button("Make my clips", variant="primary", size="lg")
                status = gr.Textbox(label="Status", lines=6, interactive=False, autoscroll=True)
                gr.Button("📂 Open clips folder").click(
                    lambda f: open_folder(f or OUTPUT_ROOT), folder, None)

            with gr.Column(scale=3, min_width=340):
                @gr.render(inputs=clips_state)
                def show(clips):
                    if not clips:
                        gr.Markdown("### Your clips will show up here")
                        return
                    for row in range(0, len(clips), 2):
                        with gr.Row():
                            for c in clips[row:row + 2]:
                                with gr.Column(min_width=240):
                                    gr.Video(c["path"], height=440, show_label=False, interactive=False)
                                    gr.Textbox(c["post_text"], label="Caption to post",
                                               buttons=["copy"], lines=2)

        go.click(make, [video, topic, count, length, framing, api_key], [status, clips_state, folder])
        gr.Markdown("<small>Only clip videos you own or have permission to use.</small>")
    return demo


if __name__ == "__main__":
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    build_ui().queue().launch(
        inbrowser=not os.environ.get("AUTOCLIP_NO_BROWSER"),
        server_name="127.0.0.1",
        allowed_paths=[str(OUTPUT_ROOT)],
        theme=gr.themes.Soft(primary_hue="violet"),
        footer_links=[],
    )
