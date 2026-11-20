"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, roman
from .media import NO_WINDOW, run

W, H = config.OUT_W, config.OUT_H

RESOLUTIONS = {
    "1080p": {"w": 1080, "h": 1920, "bitrate": "6M", "crf": "21", "label": "1080p Full HD"},
    "4k": {"w": 2160, "h": 3840, "bitrate": "22M", "crf": "18", "label": "4K Ultra HD"},
    "720p": {"w": 720, "h": 1280, "bitrate": "3.5M", "crf": "23", "label": "720p HD"}
}

# ASS colours are &HBBGGRR. `size` is the ASS font size (line height); _Font turns it into real pixels.
STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "00F0FF",
               "strong": "FFFFFF", "outline": 7, "pop": 112, "upper": True, "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "base": "FFFFFF", "active": "3C3CFF",
             "strong": "00D7FF", "outline": 7, "pop": 114, "upper": True, "per": 2},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "base": "FFFFFF", "active": "6BD7FF",
              "strong": "FFFFFF", "outline": 5, "pop": 106, "upper": False, "per": 4},
    "neon": {"label": "Neon Glow", "font": "Archivo Black", "size": 128, "base": "FFFFFF", "active": "00F0FF",
             "strong": "FF4DDA", "outline": 3, "pop": 116, "upper": True, "per": 2},
    "boxed": {"label": "Bold Box", "font": "Archivo Black", "size": 112, "base": "FFFFFF", "active": "111111",
              "strong": "FFFFFF", "outline": 3, "pop": 108, "upper": True, "per": 3},
    "cinema": {"label": "Cinematic", "font": "Poppins ExtraBold", "size": 86, "base": "FFFFFF", "active": "FFC86B",
               "strong": "FFC86B", "outline": 3, "pop": 100, "upper": False, "per": 5},
    "hormozi": {"label": "Hormozi Gold", "font": "Archivo Black", "size": 136, "base": "FFFFFF", "active": "00E5FF",
                "strong": "00F0FF", "outline": 9, "pop": 124, "upper": True, "per": 2},
    "beast": {"label": "Beast Green", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "66FF00",
              "strong": "00FFFF", "outline": 8, "pop": 120, "upper": True, "per": 2},
    "cyber": {"label": "Cyberpunk", "font": "Archivo Black", "size": 130, "base": "FFFFFF", "active": "FFAA00",
              "strong": "FF00CC", "outline": 8, "pop": 120, "upper": True, "per": 2},
    "karaoke": {"label": "Karaoke Coral", "font": "Poppins ExtraBold", "size": 126, "base": "E0E0E0", "active": "3355FF",
                "strong": "00FFFF", "outline": 7, "pop": 115, "upper": False, "per": 3},
    "minimal": {"label": "Minimalist", "font": "Poppins ExtraBold", "size": 94, "base": "DCDCDC", "active": "FFFFFF",
                "strong": "FFFFFF", "outline": 4, "pop": 105, "upper": False, "per": 4},
}
HOOK = {"font": "Poppins ExtraBold", "size": 96, "ink": "14100E", "box": "FFFFFF", "pad_x": 36, "pad_y": 22, "radius": 26,
        "max_w": 900}
FONT_FILES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Anton": "Anton-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
CAP_MAX_W = 960   # captions never run wider than this, whatever is said

EMOJI_WORDS = {
    "money": "💰", "cash": "💵", "rich": "🤑", "fire": "🔥", "lit": "🔥", "dead": "💀",
    "kill": "💀", "shot": "🎯", "win": "🏆", "winner": "🏆", "clutch": "🔥", "crazy": "🤯",
    "insane": "🤯", "shock": "⚡", "love": "❤️", "danger": "⚠️", "warn": "⚠️", "warning": "⚠️",
    "stop": "🛑", "rocket": "🚀", "moon": "🚀", "goat": "🐐", "king": "👑", "run": "🏃",
    "fast": "⚡", "game": "🎮", "secret": "🤫", "truth": "💡", "brain": "🧠", "idea": "💡"
}


class _Font:
    """Measures text exactly as the renderer will draw it, so every word can be placed by hand: the highlighted
    word can grow without pushing its neighbours, and the heading box fits its text."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        self.cap = struct.unpack(">h", d[o + 88: o + 90])[0] or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this ASS size."""
        try:
            from PIL import ImageFont
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


CAPTION_LEAD = 0.0  # measured: word stamps are within 0.15 s of the voice, so no shift is needed
def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists():
            shutil.copyfile(f, config.FONTS_DIR / f.name)


LAYOUTS = {"blur": "Full frame + blurred fill", "zoom": "Zoomed in + blurred fill", "crop": "Fill the screen (centre crop)",
           "gameplay": "Gameplay fills the screen, facecam in the corner"}


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > 16
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def geometry(src_w, src_h, layout, out_w=W, out_h=H):
    """Where the video sits in the frame, and where hook and captions go."""
    scale_y = out_h / H
    if src_h >= src_w and layout != "crop":
        layout = "crop"  # already vertical or square: nothing to gain from a blurred fill
    if layout == "blur":
        fg_h = min(out_h, int(round(out_w * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = int(1000 * scale_y)
    else:
        fg_h = out_h
    top = (out_h - fg_h) // 2
    if layout in ("crop", "gameplay"):
        return layout, fg_h, int(300 * scale_y), int(1380 * scale_y)
    return layout, fg_h, max(int(230 * scale_y), top - int(190 * scale_y)), min(int(1640 * scale_y), top + fg_h + int(180 * scale_y))


def _hook_events(hook, dur, y, out_w=W):
    """The heading: dark text in a white rounded box that fits it, on one line or two balanced ones."""
    scale = out_w / W
    f, size = _Font.get(HOOK["font"]), int(HOOK["size"] * scale)
    max_w = int(HOOK["max_w"] * scale)
    pad_x = int(HOOK["pad_x"] * scale)
    pad_y = int(HOOK["pad_y"] * scale)
    radius = int(HOOK["radius"] * scale)
    words = hook.split()
    if not words:
        return []
    lines = [" ".join(words)]
    if f.width(lines[0], size) > max_w and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > max_w:
        size = max(int(40 * scale), int(size * max_w / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    bw, bh = widest + 2 * pad_x, line_h * len(lines) + 2 * pad_y
    x0, y0, r = (out_w - bw) / 2, y - bh / 2, min(radius, bh / 2)
    x1, y1 = x0 + bw, y0 + bh
    n = lambda v: f"{v:.0f}"                                                         # noqa: E731
    box = (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
           f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
           f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
           f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")
    span = f"{_ts(0)},{_ts(dur)}"
    ev = [f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{HOOK['box']}&\\p1}}{box}{{\\p0}}"]
    for i, line in enumerate(lines):
        cy = y - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({out_w // 2},{cy:.0f})\\fad(160,0)\\fs{size}}}{line}")
    return ev


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, auto_emoji=False, out_w=W, out_h=H, multi_speaker=False) -> str:
    st = STYLES.get(style_name, STYLES["bounce"])
    scale = out_w / W
    font_size = int(round(st["size"] * scale))
    outline = max(1, int(round(st["outline"] * scale)))
    shadow = int(round(2 * scale)) if style_name == "cinema" else 0
    hook_font_size = int(round(HOOK["size"] * scale))
    cap_max_w = int(round(CAP_MAX_W * scale))
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    back_style = 3 if style_name == "boxed" else 1
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{font_size},&H00{st['base']},&H00{st['base']},&H88000000,&HCC111111,0,0,0,0,100,100,0,0,{back_style},{outline},{shadow},5,0,0,0,1
Style: Hook,{HOOK['font']},{hook_font_size},&H00{HOOK['ink']},&H00{HOOK['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    ev = _hook_events(_clean(hook), dur, hook_y, out_w=out_w)
    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, st["per"])
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            k = _key(x["w"])
            if auto_emoji and k in EMOJI_WORDS:
                t = f"{t} {EMOJI_WORDS[k]}"
            texts.append(t.upper() if st["upper"] else t)
        if not all(roman.drawable(t) for t in texts):
            line = " ".join(texts)
            fs = max(int(44 * scale), min(int(font_size * 0.7), int(1500 * scale / max(1, len(line)) * 1.6)))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({out_w // 2},{cap_y:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = font_size
        gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * outline + 6) * size / font_size
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > cap_max_w:
            size = max(int(36 * scale), int(size * cap_max_w / total))
            gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * outline + 6) * size / font_size
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        cy = cap_y - f.cap_shift(size)
        x = (out_w - total) / 2
        for i, (w, t) in enumerate(zip(g, texts)):
            wd = f.width(t, size)
            p = max(104, min(st["pop"], 100 + int(2200 * scale / max(wd, 1))))
            pos = f"\\an5\\pos({x + wd / 2:.0f},{cy:.0f})\\fs{size}"
            x += wd + gap
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            spk = w.get("speaker", 1)
            if multi_speaker and spk == 2:
                base = "FFFF00"   # Cyan in ASS format (&HBBGGRR&)
                active = "00D7FF"  # Bright Gold punch
            else:
                base = st["strong"] if _key(w["w"]) in strong else st["base"]
                active = st["active"]
            if b - a >= 0.02:
                ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active}&\\fscx94\\fscy94"
                          f"\\t(0,70,\\fscx{p}\\fscy{p})\\t(70,170,\\fscx100\\fscy100)}}{t}")
            if g_end - b >= 0.02:
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base}&\\fscx{p - 5}\\fscy{p - 5}"
                          f"\\t(0,70,\\fscx100\\fscy100)}}{t}")
    return head + "\n".join(ev) + "\n"


PIP_W = 380            # how wide the facecam is in the 1080-wide frame
PIP_MARGIN = 26


def _filter(layout, fg_h, facecam=None, out_w=W, out_h=H):
    pip_w = int(round(PIP_W * out_w / W))
    pip_margin = int(round(PIP_MARGIN * out_w / W))
    if layout == "gameplay" and facecam:
        # The game fills the screen, and the webcam sits in the top corner of it, so a viewer sees
        # the play and the face at the same time.
        fx, fy, fw, fh = (int(v) for v in facecam)
        if fw > 8 and fh > 8:
            pip_h = max(2, int(round(pip_w * fh / fw)))
            return (f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
                    f"[base]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1[b];"
                    f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1[p];"
                    f"[b][p]overlay={out_w - pip_w - pip_margin}:{pip_margin}[v0];")
    if layout == "crop" or (layout == "gameplay" and not facecam):
        return f"[0:v]fps={config.OUT_FPS},scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1[v0];"
    blur_w, blur_h = max(2, int(round(270 * out_w / W / 2)) * 2), max(2, int(round(480 * out_h / H / 2)) * 2)
    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,crop={blur_w}:{blur_h},boxblur=6:2,"
            f"scale={out_w}:{out_h},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={out_w}:{fg_h}:force_original_aspect_ratio=increase,crop={out_w}:{fg_h}[fg];"
            f"[bg][fg]overlay=0:({out_h}-h)/2,setsar=1[v0];")


def _hook_y(layout, hook_y, facecam=None, out_w=W):
    """Where the heading goes. In the gameplay layout the webcam sits in the top corner, so a heading
    across the top would run under it: it goes just below the picture instead."""
    if layout == "gameplay" and facecam and len(facecam) == 4 and facecam[2] > 8:
        pip_w = int(round(PIP_W * out_w / W))
        pip_margin = int(round(PIP_MARGIN * out_w / W))
        return pip_margin + int(round(pip_w * facecam[3] / facecam[2])) + int(round(32 * out_w / W))
    return hook_y


_qsv_ok = None
_nvenc_ok = None
_vt_ok = None
_amf_ok = None
_mf_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int,
                preview_size=None) -> dict:
    """Writes <name>.mp4, <name>.jpg and <name>.ass into out_dir. Returns file names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = clip["start"], clip["end"]
    res_key = str(clip.get("resolution") or "1080p").lower()
    res_cfg = RESOLUTIONS.get(res_key, RESOLUTIONS["1080p"])
    out_w, out_h = res_cfg["w"], res_cfg["h"]
    bitrate, crf = res_cfg["bitrate"], res_cfg["crf"]
    layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, clip.get("layout", "blur"), out_w=out_w, out_h=out_h)
    face = clip.get("facecam")
    if layout == "gameplay" and not (face and len(face) == 4):
        layout = "crop"     # no webcam found: the game fills the screen, which is still the right shape
    hook_y = _hook_y(layout, hook_y, face, out_w=out_w)
    ass = build_ass(words if clip.get("captions", True) else [], start, end, clip.get("hook", ""), clip.get("style", "bounce"),
                    clip.get("highlight_words", []), hook_y, cap_y, auto_emoji=clip.get("auto_emoji", False),
                    out_w=out_w, out_h=out_h, multi_speaker=clip.get("multi_speaker", False))
    # The clip is made in a short work folder and moved into place afterwards. The caption step of ffmpeg cannot
    # open files whose full path is longer than 260 characters on Windows, which a data folder deep inside other
    # folders easily reaches. Inside the work folder every name is short and relative (a drive colon would also
    # break the filter syntax).
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        overlay = clip.get("overlay_path")
        if overlay and not Path(overlay).is_file():
            overlay = None
        return _render_in(work, src, out_dir, name, start, end, layout, fg_h, ass, face=face,
                          music_path=clip.get("music_path"), source_volume=clip.get("source_volume", 1.0),
                          music_volume=clip.get("music_volume", 0.25), preview_size=preview_size,
                          overlay_path=overlay, overlay_scale=clip.get("overlay_scale", 0.24),
                          overlay_x=clip.get("overlay_x", 0.78), overlay_y=clip.get("overlay_y", 0.82),
                          effect=clip.get("effect", "none"), animation=clip.get("animation", "none"),
                          ducking=clip.get("ducking", True), fade_in=clip.get("fade_in", 0.35),
                          fade_out=clip.get("fade_out", 0.45), out_w=out_w, out_h=out_h,
                          bitrate=bitrate, crf=crf, res_key=res_key,
                          enable_sfx=clip.get("sfx", False), words=words, hook=clip.get("hook", ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _render_in(work: Path, src: Path, out_dir: Path, name: str, start, end, layout, fg_h, ass: str, face=None,
               music_path=None, source_volume=1.0, music_volume=0.25, preview_size=None, overlay_path=None,
               overlay_scale=0.24, overlay_x=0.78, overlay_y=0.82, effect="none", animation="none",
               ducking=True, fade_in=0.35, fade_out=0.45, out_w=W, out_h=H, bitrate="6M", crf="21",
               res_key="1080p", enable_sfx=False, words=None, hook="") -> dict:
    global _qsv_ok, _nvenc_ok, _vt_ok, _amf_ok, _mf_ok
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(f, work / "f" / f.name)
    duration = end - start
    fc = _filter(layout, fg_h, face, out_w=out_w, out_h=out_h) + f"[v0]ass={name}.ass:fontsdir=f[vbase]"
    vmap = "[vbase]"
    if effect == "warm":
        fc += ";[vbase]eq=saturation=1.2:contrast=1.04:gamma=1.02[vfx]"
        vmap = "[vfx]"
    elif effect == "mono":
        fc += ";[vbase]hue=s=0,eq=contrast=1.08[vfx]"
        vmap = "[vfx]"
    elif effect == "vintage":
        fc += ";[vbase]hue=s=0.82,eq=contrast=1.1:brightness=0.025,colorbalance=rs=0.08:gs=0.02:bs=-0.04[vfx]"
        vmap = "[vfx]"
    elif effect == "vivid":
        fc += ";[vbase]eq=saturation=1.45:contrast=1.08[vfx]"
        vmap = "[vfx]"
    if overlay_path and Path(overlay_path).is_file():
        overlay_path = Path(overlay_path)
        shutil.copyfile(overlay_path, work / ("overlay" + overlay_path.suffix.lower()))
        ow, oh = max(2, int(out_w * max(.08, min(.5, float(overlay_scale))))), -1
        ox = f"(W-w)*{max(0.0, min(1.0, float(overlay_x))):.3f}"
        oy = f"(H-h)*{max(0.0, min(1.0, float(overlay_y))):.3f}"
        fc += f";[1:v]scale={ow}:{oh}:force_original_aspect_ratio=decrease[ov];{vmap}null[basev];[basev][ov]overlay={ox}:{oy}:shortest=1:eof_action=repeat[vout]"
        vmap = "[vout]"
    if animation == "pulse":
        fc += f";{vmap}zoompan=z='min(1.04\\,1.015+0.015*sin(2*PI*on/36))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={out_w}x{out_h}:fps={config.OUT_FPS}[vanim]"
        vmap = "[vanim]"
    if preview_size:
        pw, ph = (int(v) for v in preview_size)
        fc += f";{vmap}scale={pw}:{ph}[previewv]"
        vmap = "[previewv]"

    sfx_file = work / "sfx.wav"
    has_sfx = False
    if enable_sfx:
        try:
            from . import sfx
            events = sfx.plan_sfx_events(words if words else [], hook, duration)
            if events:
                has_sfx = sfx.generate_sfx_track(events, duration, sfx_file)
        except Exception:
            has_sfx = False

    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", str(src)]
    cur_inputs = 1
    if overlay_path and Path(overlay_path).is_file():
        base += ["-loop", "1", "-i", str(work / ("overlay" + Path(overlay_path).suffix.lower()))]
        cur_inputs += 1
    music_path = Path(music_path) if music_path else None
    if music_path and music_path.is_file():
        source_volume = max(0.0, min(2.0, float(source_volume)))
        music_volume = max(0.0, min(1.5, float(music_volume)))
        fin = max(0.0, min(5.0, float(fade_in if fade_in is not None else 0.35)))
        fout = max(0.0, min(5.0, float(fade_out if fade_out is not None else 0.45)))
        fout_st = max(0.0, duration - fout)
        music_idx = cur_inputs
        cur_inputs += 1
        base += ["-stream_loop", "-1", "-i", str(music_path)]
        a_target = "[amixpre]" if has_sfx else "[a]"
        norm_suffix = "" if has_sfx else ",alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11"
        if ducking:
            fc += (f";[0:a:0]volume={source_volume},asplit=2[sourcea][sc];"
                   f"[{music_idx}:a:0]volume={music_volume},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
                   f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fout_st:.3f}:d={fout:.3f}[musicraw];"
                   f"[musicraw][sc]sidechaincompress=threshold=0.08:ratio=4:attack=20:release=300[ducked];"
                   f"[sourcea][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0{norm_suffix}{a_target}")
        else:
            fc += (f";[0:a:0]volume={source_volume}[sourcea];"
                   f"[{music_idx}:a:0]volume={music_volume},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
                   f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fout_st:.3f}:d={fout:.3f}[music];"
                   f"[sourcea][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0{norm_suffix}{a_target}")
    else:
        a_target = "[amixpre]" if has_sfx else "[a]"
        norm_suffix = "" if has_sfx else ",loudnorm=I=-14:TP=-1.5:LRA=11"
        fc += f";[0:a:0]volume={max(0.0, min(2.0, float(source_volume)))}{norm_suffix}{a_target}"

    if has_sfx:
        sfx_idx = cur_inputs
        base += ["-i", str(sfx_file)]
        fc += f";[amixpre][{sfx_idx}:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    base += ["-filter_complex", fc, "-map", vmap, "-map", "[a]"]
    base += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-pix_fmt"]
    encoders = []
    if preview_size:
        encoders.append(("preview", ["yuv420p", "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast"]))
    else:
        if _nvenc_ok is not False:
            encoders.append(("nvenc", ["yuv420p", "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-b:v", bitrate]))
        if _vt_ok is not False and sys.platform == "darwin":
            encoders.append(("videotoolbox", ["yuv420p", "-c:v", "h264_videotoolbox", "-b:v", bitrate]))
        if _qsv_ok is not False:
            encoders.append(("qsv", ["nv12", "-c:v", "h264_qsv", "-global_quality", crf, "-preset", "fast"]))
        if _amf_ok is not False:
            encoders.append(("amf", ["yuv420p", "-c:v", "h264_amf", "-b:v", bitrate, "-quality", "speed"]))
        if _mf_ok is not False and sys.platform == "win32":
            encoders.append(("mf", ["yuv420p", "-c:v", "h264_mf", "-b:v", bitrate]))
    encoders.append(("x264", ["yuv420p", "-c:v", "libx264", "-crf", crf, "-preset", "veryfast"]))
    err = None
    for label, enc in encoders:
        p = subprocess.run(base + enc + [f"{name}.mp4"], cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0:
            if label == "nvenc":
                _nvenc_ok = True
            elif label == "videotoolbox":
                _vt_ok = True
            elif label == "qsv":
                _qsv_ok = True
            elif label == "amf":
                _amf_ok = True
            elif label == "mf":
                _mf_ok = True
            break
        err = p.stderr[-1200:]
        if label == "nvenc":
            _nvenc_ok = False
        elif label == "videotoolbox":
            _vt_ok = False
        elif label == "qsv":
            _qsv_ok = False
        elif label == "amf":
            _amf_ok = False
        elif label == "mf":
            _mf_ok = False
    else:
        raise RuntimeError(f"Render failed: {err}")
    cover_t = min(1.2, (end - start) / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-q:v", "3", f"{name}.jpg"], cwd=work)
    for ext in ("mp4", "jpg", "ass"):
        shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": layout, "resolution": res_key, "width": out_w, "height": out_h}
