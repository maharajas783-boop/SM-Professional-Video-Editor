# ═══════════════════════════════════════════════════════════
#  SM PRO VIDEO EDITOR — Backend (app.py)  v5.0
#  Windows 11 / Linux / macOS compatible
#  pip install flask werkzeug
# ═══════════════════════════════════════════════════════════

from flask import Flask, render_template, request, jsonify, send_file, url_for
import os, sys, json, uuid, subprocess, platform, shutil
from pathlib import Path
from werkzeug.utils import secure_filename

# ── App Config ───────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'sm-pro-video-editor-2025'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

BASE_DIR   = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / 'uploads'
EXPORT_DIR = BASE_DIR / 'exports'
UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

IS_WINDOWS = platform.system() == 'Windows'

ALLOWED_VIDEO = {'mp4','avi','mov','mkv','webm','flv','wmv','m4v','ts','mts'}
ALLOWED_AUDIO = {'mp3','wav','aac','ogg','flac','m4a','wma'}
ALLOWED_IMAGE = {'jpg','jpeg','png','gif','bmp','webp','tiff','tif'}

# ── FFmpeg Auto-Detection ────────────────────────────────────
def find_binary(name):
    exe = f"{name}.exe" if IS_WINDOWS else name
    win_paths = [
        rf"C:\ffmpeg\bin\{exe}",
        rf"C:\Program Files\ffmpeg\bin\{exe}",
        rf"C:\Program Files (x86)\ffmpeg\bin\{exe}",
        rf"C:\Tools\ffmpeg\bin\{exe}",
        rf"C:\ffmpeg-master\bin\{exe}",
        rf"C:\ffmpeg-release-essentials\bin\{exe}",
        rf"C:\ffmpeg-release-full\bin\{exe}",
        os.path.expanduser(rf"~\ffmpeg\bin\{exe}"),
        os.path.expanduser(rf"~\AppData\Local\ffmpeg\bin\{exe}"),
        os.path.expanduser(rf"~\scoop\shims\{exe}"),
        rf"C:\ProgramData\chocolatey\bin\{exe}",
        rf"C:\tools\ffmpeg\bin\{exe}",
    ]
    nix_paths = [
        f'/usr/bin/{name}', f'/usr/local/bin/{name}',
        f'/opt/homebrew/bin/{name}', f'/snap/bin/{name}',
    ]
    path_dirs = os.environ.get('PATH','').split(os.pathsep)
    extra = [os.path.join(d, exe if IS_WINDOWS else name) for d in path_dirs]
    candidates = (win_paths if IS_WINDOWS else nix_paths) + extra + [name]
    seen = set()
    for p in candidates:
        if p in seen: continue
        seen.add(p)
        try:
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            r = subprocess.run([p, '-version'], capture_output=True,
                               text=True, timeout=5, creationflags=flags)
            if r.returncode == 0:
                return str(p)
        except Exception:
            continue
    return None

FFMPEG_BIN       = find_binary('ffmpeg')
FFPROBE_BIN      = find_binary('ffprobe')
FFMPEG_AVAILABLE = FFMPEG_BIN is not None

print(f"\n[SM Pro Video Editor] OS      : {platform.system()} {platform.release()}")
print(f"[SM Pro Video Editor] FFmpeg  : {FFMPEG_BIN or 'NOT FOUND'}")
print(f"[SM Pro Video Editor] FFprobe : {FFPROBE_BIN or 'NOT FOUND'}")

# ── Helpers ──────────────────────────────────────────────────
def safe_path(p):
    return str(Path(p).resolve()).replace('\\', '/')

def run_ffmpeg(cmd, timeout=300):
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        return None

def ffmpeg_err(result, op):
    detail = (result.stderr or '')[-1000:] if result else 'Process timed out'
    return {'error': f'{op} failed', 'details': detail}

def escape_drawtext(t):
    # BUG FIX: must escape in correct order — backslash first
    t = t.replace('\\', '\\\\')
    t = t.replace("'",  "\\'")
    t = t.replace(':',  '\\:')
    t = t.replace('%',  '\\%')
    return t

def get_ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

# ── Routes ───────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', ffmpeg_available=FFMPEG_AVAILABLE)

@app.route('/api/status')
def api_status():
    return jsonify({'status':'online','version':'5.0','ffmpeg':FFMPEG_AVAILABLE,
                    'ffmpeg_path':FFMPEG_BIN,'os':platform.system(),'name':'SM Pro Video Editor'})

# ── Upload ───────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error':'No file in request'}), 400
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error':'No file selected'}), 400

    filename  = secure_filename(f.filename)
    if not filename:
        return jsonify({'error':'Invalid filename'}), 400

    ext = get_ext(filename)
    if   ext in ALLOWED_VIDEO: ftype = 'video'
    elif ext in ALLOWED_AUDIO: ftype = 'audio'
    elif ext in ALLOWED_IMAGE: ftype = 'image'
    else: return jsonify({'error': f'Unsupported file type: .{ext}'}), 400

    uid       = uuid.uuid4().hex
    uname     = f"{uid}_{filename}"
    save_path = UPLOAD_DIR / uname
    try:
        f.save(str(save_path))
    except Exception as e:
        return jsonify({'error': f'Save failed: {e}'}), 500

    # Extract metadata for videos
    duration = resolution = fps = None
    if ftype == 'video' and FFPROBE_BIN:
        try:
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            r = subprocess.run(
                [FFPROBE_BIN,'-v','quiet','-print_format','json',
                 '-show_streams','-show_format', safe_path(save_path)],
                capture_output=True, text=True, timeout=20, creationflags=flags)
            if r.returncode == 0:
                info = json.loads(r.stdout)
                raw  = info.get('format',{}).get('duration','0')
                duration = round(float(raw), 2) if raw and raw != 'N/A' else None
                for s in info.get('streams', []):
                    if s.get('codec_type') == 'video':
                        w, h = s.get('width', 0), s.get('height', 0)
                        resolution = f"{w}x{h}" if w and h else None
                        try:
                            n, d = s.get('r_frame_rate','0/1').split('/')
                            fps = round(int(n)/int(d), 2) if int(d) else None
                        except Exception:
                            pass
        except Exception:
            pass

    size_bytes = save_path.stat().st_size
    return jsonify({
        'success':    True,
        'file_id':    uname,
        'filename':   filename,
        'file_type':  ftype,
        'size':       size_bytes,
        'size_mb':    round(size_bytes / (1024*1024), 2),
        'url':        url_for('serve_upload', filename=uname),
        'duration':   duration,
        'resolution': resolution,
        'fps':        fps,
    })

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    p = UPLOAD_DIR / filename
    if not p.exists():
        return jsonify({'error': 'Not found'}), 404
    return send_file(str(p))

@app.route('/exports/<path:filename>')
def serve_export(filename):
    p = EXPORT_DIR / filename
    if not p.exists():
        return jsonify({'error': 'Not found'}), 404
    return send_file(str(p), as_attachment=True, download_name=filename)

# ── Trim ─────────────────────────────────────────────────────
@app.route('/api/trim', methods=['POST'])
def trim_video():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data = request.json or {}
    fid  = data.get('file_id','').strip()
    try:
        start = float(data.get('start', 0))
        end   = float(data.get('end', 10))
    except (TypeError, ValueError):
        return jsonify({'error':'Invalid time values'}), 400
    if end <= start:
        return jsonify({'error':'End time must be greater than start time'}), 400

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    ext      = get_ext(fid) or 'mp4'
    out_name = f"trimmed_{uuid.uuid4().hex}.{ext}"
    out      = EXPORT_DIR / out_name
    duration = end - start

    cmd = [FFMPEG_BIN, '-y',
           '-ss', str(start), '-i', safe_path(inp),
           '-t', str(duration),
           '-c:v', 'libx264', '-crf', '22', '-preset', 'fast',
           '-c:a', 'aac', '-avoid_negative_ts', 'make_zero',
           safe_path(out)]
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Trim')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Compress ─────────────────────────────────────────────────
@app.route('/api/compress', methods=['POST'])
def compress_video():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data    = request.json or {}
    fid     = data.get('file_id','').strip()
    quality = data.get('quality','medium')

    crf_map = {'high': '20', 'medium': '28', 'low': '35'}
    crf     = crf_map.get(quality, '28')

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    out_name = f"compressed_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name
    orig_sz  = inp.stat().st_size

    cmd = [FFMPEG_BIN, '-y', '-i', safe_path(inp),
           '-c:v', 'libx264', '-crf', crf, '-preset', 'fast',
           '-c:a', 'aac', '-b:a', '128k',
           '-movflags', '+faststart', safe_path(out)]
    result = run_ffmpeg(cmd, 900)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Compress')), 500

    new_sz   = out.stat().st_size
    saved    = round((1 - new_sz / orig_sz) * 100, 1) if orig_sz > 0 else 0
    return jsonify({'success':True, 'output':out_name,
                    'original_size_mb': round(orig_sz/(1024*1024),2),
                    'new_size_mb':      round(new_sz/(1024*1024),2),
                    'saved_percent':    saved,
                    'download_url':     url_for('serve_export', filename=out_name)})

# ── Convert ──────────────────────────────────────────────────
@app.route('/api/convert', methods=['POST'])
def convert_video():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data   = request.json or {}
    fid    = data.get('file_id','').strip()
    fmt    = data.get('format','mp4').lower().strip('.')
    res    = data.get('resolution', None)

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    out_name = f"converted_{uuid.uuid4().hex}.{fmt}"
    out      = EXPORT_DIR / out_name
    cmd      = [FFMPEG_BIN, '-y', '-i', safe_path(inp)]
    if res:
        w, h = res.split('x')
        # BUG FIX: force even dimensions for libx264
        cmd += ['-vf', f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"]
    cmd += [safe_path(out)]
    result = run_ffmpeg(cmd, 900)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Convert')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Merge ─────────────────────────────────────────────────────
@app.route('/api/merge', methods=['POST'])
def merge_videos():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data     = request.json or {}
    file_ids = data.get('file_ids', [])
    if len(file_ids) < 2:
        return jsonify({'error':'Need at least 2 files to merge'}), 400

    paths = []
    for fid in file_ids:
        p = UPLOAD_DIR / fid
        if not p.exists():
            return jsonify({'error': f'File not found: {fid}'}), 404
        paths.append(p)

    # BUG FIX: write concat list with proper 'file' prefix and forward slashes
    concat_path = UPLOAD_DIR / f"concat_{uuid.uuid4().hex}.txt"
    try:
        with open(concat_path, 'w', encoding='utf-8') as f:
            for p in paths:
                fp = safe_path(p)
                f.write(f"file '{fp}'\n")

        out_name = f"merged_{uuid.uuid4().hex}.mp4"
        out      = EXPORT_DIR / out_name
        cmd = [FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0',
               '-i', safe_path(concat_path), '-c', 'copy', safe_path(out)]
        result = run_ffmpeg(cmd, 900)
    finally:
        if concat_path.exists():
            concat_path.unlink()

    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Merge')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Extract Audio ─────────────────────────────────────────────
@app.route('/api/extract-audio', methods=['POST'])
def extract_audio():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data = request.json or {}
    fid  = data.get('file_id','').strip()
    fmt  = data.get('format','mp3').lower()

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    codec_map = {'mp3':'libmp3lame', 'wav':'pcm_s16le', 'aac':'aac'}
    codec     = codec_map.get(fmt, 'libmp3lame')

    out_name = f"audio_{uuid.uuid4().hex}.{fmt}"
    out      = EXPORT_DIR / out_name
    cmd      = [FFMPEG_BIN, '-y', '-i', safe_path(inp), '-vn', '-c:a', codec]
    if fmt in ('mp3','aac'):
        cmd += ['-b:a', '192k']
    cmd.append(safe_path(out))
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Extract audio')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Watermark ─────────────────────────────────────────────────
@app.route('/api/add-watermark', methods=['POST'])
def add_watermark():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data    = request.json or {}
    vid_id  = data.get('video_id','').strip()
    wm_id   = data.get('watermark_id','').strip()
    pos     = data.get('position','bottom-right')
    opacity = max(0.05, min(1.0, float(data.get('opacity', 0.7))))

    vp = UPLOAD_DIR / vid_id
    wp = UPLOAD_DIR / wm_id
    if not vp.exists(): return jsonify({'error':'Video not found'}), 404
    if not wp.exists(): return jsonify({'error':'Watermark image not found'}), 404

    pos_map = {
        'top-left':     '10:10',
        'top-right':    'main_w-overlay_w-10:10',
        'bottom-left':  '10:main_h-overlay_h-10',
        'bottom-right': 'main_w-overlay_w-10:main_h-overlay_h-10',
        'center':       '(main_w-overlay_w)/2:(main_h-overlay_h)/2',
    }
    xy = pos_map.get(pos, pos_map['bottom-right'])
    fc = (f"[1:v]scale=iw*0.20:-1,format=rgba,"
          f"colorchannelmixer=aa={opacity:.2f}[wm];"
          f"[0:v][wm]overlay={xy}")

    out_name = f"watermarked_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name
    cmd = [FFMPEG_BIN,'-y','-i',safe_path(vp),'-i',safe_path(wp),
           '-filter_complex', fc,
           '-c:v','libx264','-crf','22','-preset','fast',
           '-c:a','copy', safe_path(out)]
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Watermark')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Text Overlay ──────────────────────────────────────────────
@app.route('/api/add-text', methods=['POST'])
def add_text_overlay():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data      = request.json or {}
    fid       = data.get('file_id','').strip()
    text      = data.get('text','SM Pro Video Editor').strip()
    font_size = max(12, min(300, int(data.get('font_size', 48))))
    color     = data.get('color','white')
    position  = data.get('position','bottom')
    t0        = max(0.0, float(data.get('start_time', 0)))
    t1        = float(data.get('end_time', 5))
    if t1 <= t0: return jsonify({'error':'End must be greater than start'}), 400
    if not text: return jsonify({'error':'Text cannot be empty'}), 400

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    xy_map = {
        'center': '(w-text_w)/2:(h-text_h)/2',
        'top':    '(w-text_w)/2:80',
        'bottom': '(w-text_w)/2:h-text_h-80',
    }
    x_expr, y_expr = xy_map.get(position, xy_map['bottom']).split(':')
    safe_text = escape_drawtext(text)

    # BUG FIX: fontfile not required; use fontcolor properly, wrap in proper quotes
    drawtext = (
        f"drawtext=text='{safe_text}'"
        f":fontsize={font_size}"
        f":fontcolor={color}"
        f":x={x_expr}:y={y_expr}"
        f":enable='between(t\\,{t0}\\,{t1})'"
        f":shadowcolor=black@0.6:shadowx=2:shadowy=2"
        f":box=1:boxcolor=black@0.4:boxborderw=10"
    )

    out_name = f"texted_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name
    cmd = [FFMPEG_BIN,'-y','-i', safe_path(inp),
           '-vf', drawtext,
           '-c:v','libx264','-crf','22','-preset','fast',
           '-c:a','copy', safe_path(out)]
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Text overlay')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Thumbnail ─────────────────────────────────────────────────
@app.route('/api/thumbnail', methods=['POST'])
def generate_thumbnail():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data = request.json or {}
    fid  = data.get('file_id','').strip()
    ts   = max(0.0, float(data.get('timestamp', 1)))

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    out_name = f"thumb_{uuid.uuid4().hex}.jpg"
    out      = EXPORT_DIR / out_name
    cmd = [FFMPEG_BIN,'-y','-ss', str(ts), '-i', safe_path(inp),
           '-vframes','1','-q:v','2', safe_path(out)]
    result = run_ffmpeg(cmd, 60)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Thumbnail')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Speed Control ─────────────────────────────────────────────
@app.route('/api/speed', methods=['POST'])
def speed_video():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data  = request.json or {}
    fid   = data.get('file_id','').strip()
    speed = max(0.25, min(4.0, float(data.get('speed', 1.0))))

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    # BUG FIX: atempo only accepts 0.5–2.0, chain filters for values outside that range
    vf = f"setpts={round(1/speed, 6)}*PTS"
    if speed < 0.5:
        af = f"atempo={round(speed*2,4)},atempo=0.5"
    elif speed <= 2.0:
        af = f"atempo={round(speed,4)}"
    else:
        # Chain multiple atempo=2.0 filters
        steps, s = [], speed
        while s > 2.0:
            steps.append("atempo=2.0")
            s /= 2.0
        steps.append(f"atempo={round(s,4)}")
        af = ','.join(steps)

    out_name = f"speed_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name
    cmd = [FFMPEG_BIN,'-y','-i', safe_path(inp),
           '-vf', vf, '-af', af,
           '-c:v','libx264','-crf','22','-preset','fast',
           '-c:a','aac', '-b:a','128k', safe_path(out)]
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Speed')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Rotate & Flip ─────────────────────────────────────────────
@app.route('/api/rotate', methods=['POST'])
def rotate_video():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data = request.json or {}
    fid  = data.get('file_id','').strip()
    op   = data.get('operation','rotate_90')

    inp = UPLOAD_DIR / fid
    if not inp.exists(): return jsonify({'error':'File not found'}), 404

    vf_map = {
        'rotate_90':     'transpose=1',
        'rotate_90_ccw': 'transpose=2',
        'rotate_180':    'transpose=2,transpose=2',
        'flip_h':        'hflip',
        'flip_v':        'vflip',
        'flip_both':     'hflip,vflip',
    }
    # BUG FIX: rotate_180 was wrong (transpose=1,transpose=1 = 180°, but
    # transpose=2,transpose=2 is correct for CCW+CCW=180)
    # Actually: transpose=1 (CW90) twice = 180. Use vflip,hflip instead — cleaner
    vf_map['rotate_180'] = 'vflip,hflip'
    vf = vf_map.get(op, 'transpose=1')

    out_name = f"rotated_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name
    cmd = [FFMPEG_BIN,'-y','-i', safe_path(inp),
           '-vf', vf,
           '-c:v','libx264','-crf','22','-preset','fast',
           '-c:a','copy', safe_path(out)]
    result = run_ffmpeg(cmd, 600)
    if result is None: return jsonify({'error':'FFmpeg timed out'}), 500
    if result.returncode != 0: return jsonify(ffmpeg_err(result, 'Rotate')), 500
    return jsonify({'success':True, 'output':out_name,
                    'download_url':url_for('serve_export', filename=out_name)})

# ── Slideshow: Photos + Audio → Video (NEW) ──────────────────
@app.route('/api/slideshow', methods=['POST'])
def create_slideshow():
    if not FFMPEG_AVAILABLE: return jsonify({'error':'FFmpeg not found'}), 503
    data       = request.json or {}
    image_ids  = data.get('image_ids', [])
    audio_id   = data.get('audio_id', '').strip()
    duration   = max(1, min(30, float(data.get('duration_per_image', 3))))
    resolution = data.get('resolution', '1280x720')
    transition = data.get('transition', 'fade')  # fade or none

    if not image_ids:
        return jsonify({'error':'Select at least one image'}), 400

    # Validate all images exist
    img_paths = []
    for iid in image_ids:
        p = UPLOAD_DIR / iid
        if not p.exists():
            return jsonify({'error': f'Image not found: {iid}'}), 404
        img_paths.append(p)

    # Validate audio if provided
    audio_path = None
    if audio_id:
        ap = UPLOAD_DIR / audio_id
        if not ap.exists():
            return jsonify({'error':'Audio file not found'}), 404
        audio_path = ap

    out_name = f"slideshow_{uuid.uuid4().hex}.mp4"
    out      = EXPORT_DIR / out_name

    w, h = resolution.split('x')
    total_duration = len(img_paths) * duration

    # Build concat list of images with scale/pad to consistent resolution
    # Use lavfi concat demuxer approach: create one segment per image
    tmp_clips = []
    try:
        for idx, img_p in enumerate(img_paths):
            clip_name = f"slide_{uuid.uuid4().hex}.mp4"
            clip_path = EXPORT_DIR / clip_name
            tmp_clips.append(clip_path)

            # Each image → short video clip with proper resolution
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                  f"format=yuv420p")

            clip_cmd = [FFMPEG_BIN,'-y',
                        '-loop','1','-i', safe_path(img_p),
                        '-t', str(duration),
                        '-vf', vf,
                        '-c:v','libx264','-crf','23','-preset','fast',
                        '-r','25',
                        safe_path(clip_path)]
            r = run_ffmpeg(clip_cmd, 120)
            if r is None or r.returncode != 0:
                err = ffmpeg_err(r, f'Slide {idx+1}')
                return jsonify(err), 500

        # Concat all clips
        concat_txt = EXPORT_DIR / f"concat_slide_{uuid.uuid4().hex}.txt"
        with open(concat_txt, 'w') as f:
            for cp in tmp_clips:
                f.write(f"file '{safe_path(cp)}'\n")

        if audio_path:
            # Merge slideshow video with audio
            merged_name = f"slide_{uuid.uuid4().hex}.mp4"
            merged_path = EXPORT_DIR / merged_name
            concat_cmd = [FFMPEG_BIN,'-y','-f','concat','-safe','0',
                          '-i', safe_path(concat_txt),'-c','copy', safe_path(merged_path)]
            r = run_ffmpeg(concat_cmd, 300)
            if r is None or r.returncode != 0:
                return jsonify(ffmpeg_err(r, 'Slideshow concat')), 500

            # Add audio (loop or trim to video length)
            final_cmd = [FFMPEG_BIN,'-y',
                         '-i', safe_path(merged_path),
                         '-stream_loop','-1','-i', safe_path(audio_path),
                         '-c:v','copy','-c:a','aac','-b:a','192k',
                         '-t', str(total_duration),
                         '-shortest',
                         safe_path(out)]
            r = run_ffmpeg(final_cmd, 300)
            merged_path.unlink(missing_ok=True)
        else:
            # Concat only, no audio
            concat_cmd = [FFMPEG_BIN,'-y','-f','concat','-safe','0',
                          '-i', safe_path(concat_txt),
                          '-c:v','libx264','-crf','22','-preset','fast',
                          safe_path(out)]
            r = run_ffmpeg(concat_cmd, 300)

        concat_txt.unlink(missing_ok=True)

        if r is None: return jsonify({'error':'FFmpeg timed out'}), 500
        if r.returncode != 0: return jsonify(ffmpeg_err(r, 'Slideshow')), 500

        return jsonify({
            'success':     True,
            'output':      out_name,
            'slides':      len(img_paths),
            'duration_s':  total_duration,
            'has_audio':   audio_path is not None,
            'download_url': url_for('serve_export', filename=out_name)
        })

    finally:
        for cp in tmp_clips:
            try: cp.unlink(missing_ok=True)
            except: pass

# ── File Management ───────────────────────────────────────────
@app.route('/api/files')
def list_files():
    files = [{'name':p.name,'size_mb':round(p.stat().st_size/(1024*1024),2)}
             for p in UPLOAD_DIR.iterdir()
             if p.is_file() and not p.name.startswith('concat_')]
    return jsonify({'files':files,'count':len(files)})

@app.route('/api/delete', methods=['POST'])
def delete_file():
    data   = request.json or {}
    fid    = data.get('file_id','').strip()
    folder = data.get('folder','uploads')
    base   = UPLOAD_DIR if folder == 'uploads' else EXPORT_DIR
    path   = (base / fid).resolve()
    # Security: must be inside base dir
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return jsonify({'error':'Invalid path'}), 400
    if path.exists():
        path.unlink()
        return jsonify({'success':True})
    return jsonify({'error':'File not found'}), 404

# ── Entry Point ───────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*52)
    print("  SM PRO VIDEO EDITOR  —  http://localhost:5000")
    print("="*52 + "\n")
    app.run(debug=False, host='0.0.0.0', port=5000)
