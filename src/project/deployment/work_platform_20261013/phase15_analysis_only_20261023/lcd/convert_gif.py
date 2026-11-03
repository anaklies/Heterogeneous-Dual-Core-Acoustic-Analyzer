"""Offline GIF compositing -> bounded, big-endian RGB565 LCD package."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from PIL import Image, ImageOps

WIDTH, HEIGHT, MAX_FRAMES = 320, 172, 120
MAGIC = b'S6LCD01\0'


def rgb565(image):
    data = bytearray()
    raw = image.convert('RGB').tobytes()
    for offset in range(0, len(raw), 3):
        r, g, b = raw[offset:offset+3]
        word = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        data.extend((word >> 8, word & 255))
    return bytes(data)


def convert(source, output):
    source, output = Path(source), Path(output)
    frames, delays, hashes = [], [], []
    with Image.open(source) as image:
        size = image.size
        if max(size) > 2048 or not 1 <= image.n_frames <= MAX_FRAMES:
            raise ValueError('Unsupported GIF size or frame count')
        for index in range(image.n_frames):
            image.seek(index)  # Pillow applies transparency and disposal to each logical frame.
            delay = max(20, min(60000, int(image.info.get('duration', 100))))
            scaled = ImageOps.contain(image.convert('RGBA'), (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 255))
            canvas.alpha_composite(scaled, ((WIDTH-scaled.width)//2, (HEIGHT-scaled.height)//2))
            frame = rgb565(canvas)
            frames.append(frame)
            delays.append(delay)
            hashes.append(hashlib.sha256(frame).hexdigest())
            if index == 0:
                canvas.convert('RGB').save(output.with_suffix('.png'))
    payload = struct.pack('<8sHHI', MAGIC, WIDTH, HEIGHT, len(frames))
    payload += b''.join(struct.pack('<I', delay) + frame for delay, frame in zip(delays, frames))
    output.write_bytes(payload)
    report = dict(source_name=source.name, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  source_size=size, frames=len(frames), width=WIDTH, height=HEIGHT,
                  format='RGB565 big-endian, row-major, black aspect-fit', frame_bytes=WIDTH*HEIGHT*2,
                  delays_ms=delays, cycle_ms=sum(delays), frame_sha256=hashes,
                  package_bytes=len(payload), package_sha256=hashlib.sha256(payload).hexdigest(),
                  physical_board_test=False)
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(convert(args.source, args.output), ensure_ascii=True))
