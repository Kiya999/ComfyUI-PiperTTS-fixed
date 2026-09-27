# piper_fetch.py
# Download Piper voices and build a trimmed voices.json for ComfyUI-PiperTTS.
# Files are saved as {key}.onnx and {key}.onnx.json, the same flat layout the
# node uses. Each file is checked against the md5 in the official index and
# retried a few times if a transfer drops partway.

import argparse
import hashlib
import json
import os
import time
import urllib.request

# ------------------------------- CONFIG -------------------------------

# Folder to save the voice files in. Point this at
# <ComfyUI>/models/piper_tts so the node finds them; override with --dest.
DEST = "piper_tts"

# The node's bundled dropdown index. Only used in the copy instructions
# printed at the end - this script never writes to it.
NODE_VOICES_JSON = "voices.json"

INDEX_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
FILE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"  # same base the node uses

# Curated default. Any key that isn't in the index is skipped with a warning.
WANTED_KEYS = [
    # English, US / GB, medium
    "en_US-amy-medium",
    "en_US-lessac-medium",
    "en_US-ryan-medium",
    "en_US-libritts_r-medium",
    "en_US-hfc_female-medium",
    "en_US-joe-medium",
    # "en_GB-alan-medium",
    # "en_GB-jenny_dioco-medium",
    # "en_GB-northern_english_male-medium",
    # "en_GB-cori-medium",
    # Farsi, all five exist, all medium
    "fa_IR-amir-medium",
    "fa_IR-ganji-medium",
    "fa_IR-ganji_adabi-medium",
    "fa_IR-gyro-medium",
    "fa_IR-reza_ibrahim-medium",
]

# Set True to ignore WANTED_KEYS and take every voice whose language code is
# listed in TARGET_LANG_CODES.
GRAB_ALL_ENGLISH_AND_FARSI = False
# TARGET_LANG_CODES = ("en_US", "en_GB", "fa_IR")
TARGET_LANG_CODES = ("en_US", "fa_IR")

RETRIES, TIMEOUT = 6, 60
UA = {"User-Agent": "Mozilla/5.0 (piper-fetch)"}

# ----------------------------------------------------------------------

def http_get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT)

def load_index():
    print("Fetching official voice index ...")
    with http_get(INDEX_URL) as r:
        return json.loads(r.read().decode("utf-8"))

def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()

def download(url, dest, expect_md5=None):
    if os.path.exists(dest) and expect_md5 and md5_of(dest) == expect_md5:
        print(f"  ok (cached): {os.path.basename(dest)}")
        return True
    part = dest + ".part"
    for attempt in range(1, RETRIES + 1):
        try:
            with http_get(url) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            if expect_md5 and md5_of(part) != expect_md5:
                raise IOError("md5 mismatch")
            os.replace(part, dest)
            print(f"  done: {os.path.basename(dest)}")
            return True
        except Exception as e:
            print(f"  attempt {attempt}/{RETRIES} failed: {e}")
            if os.path.exists(part):
                os.remove(part)
            time.sleep(2 * attempt)
    print(f"  FAILED: {url}")
    return False

def main():
    ap = argparse.ArgumentParser(description="Download Piper voices for ComfyUI-PiperTTS.")
    ap.add_argument("--dest", default=DEST,
                    help="folder to save voice files in (default: %(default)s)")
    ap.add_argument("--node-voices", default=NODE_VOICES_JSON,
                    help="path to the node's voices.json (default: %(default)s)")
    ap.add_argument("--trimmed-out", default="",
                    help="where to write the trimmed index (default: <dest>/voices_trimmed.json)")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args()

    dest = args.dest
    trimmed_out = args.trimmed_out or os.path.join(dest, "voices_trimmed.json")

    os.makedirs(dest, exist_ok=True)
    index = load_index()
    print(f"Index contains {len(index)} voices.")

    if GRAB_ALL_ENGLISH_AND_FARSI:
        keys = [k for k, m in index.items() if m["language"]["code"] in TARGET_LANG_CODES]
    else:
        for k in WANTED_KEYS:
            if k not in index:
                print(f"WARNING: '{k}' not in index - skipped.")
        keys = [k for k in WANTED_KEYS if k in index]

    plan, total = [], 0
    for k in keys:
        for rel, meta in index[k]["files"].items():
            if rel.endswith(".onnx.json"):
                outname = f"{k}.onnx.json"
            elif rel.endswith(".onnx"):
                outname = f"{k}.onnx"
            else:
                continue
            plan.append((k, rel, meta, outname))
            total += meta.get("size_bytes", 0)

    print(f"\nSelected {len(keys)} voices / {len(plan)} files / ~{total/1e6:.0f} MB")
    if not args.yes:
        if input("Proceed with download? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return

    ok = 0
    for k, rel, meta, outname in plan:
        print(f"\n=== {k} ===")
        if download(f"{FILE_BASE}/{rel}", os.path.join(dest, outname), meta.get("md5_digest")):
            ok += 1

    print(f"\nDone: {ok}/{len(plan)} files in {dest}")

    # Write a matching dropdown index containing only the keys we fetched.
    trimmed = {k: index[k] for k in keys}
    with open(trimmed_out, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=1)
    print(f"\nWrote trimmed dropdown index:\n  {trimmed_out}")

    node_json = args.node_voices
    print("\nTo shorten the node dropdown:")
    print(f"  1. copy {node_json} -> {node_json}.bak")
    print(f"  2. copy {trimmed_out} -> {node_json}")
    print("  3. restart ComfyUI")

if __name__ == "__main__":
    main()
