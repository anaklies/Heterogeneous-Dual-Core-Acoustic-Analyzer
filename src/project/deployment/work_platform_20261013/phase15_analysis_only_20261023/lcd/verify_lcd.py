"""Local conversion checks, ARM cross-build and no-hardware QEMU asset tests."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from PIL import Image
from convert_gif import rgb565

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'deployment'))
from firmware_formats_20261012 import read_cpio, write_cpio

package = (HERE/'easter-egg.lcd').read_bytes()
meta = json.loads((HERE/'easter-egg.json').read_text(encoding='utf-8'))
magic, width, height, count = struct.unpack('<8sHHI', package[:16])
assert (magic, width, height, count) == (b'S6LCD01\0', 320, 172, 42)
assert len(package) == 16 + count*(110080+4)
assert rgb565(Image.new('RGB', (1, 1), 'red')) == b'\xf8\x00'
assert rgb565(Image.new('RGB', (1, 1), 'green')) == b'\x04\x00'  # CSS green = (0,128,0)
assert rgb565(Image.new('RGB', (1, 1), 'blue')) == b'\x00\x1f'
digest = hashlib.sha256()
for i in range(count):
    offset = 16+i*110084
    assert struct.unpack('<I', package[offset:offset+4])[0] == 100
    frame = package[offset+4:offset+110084]
    assert hashlib.sha256(frame).hexdigest() == meta['frame_sha256'][i]
    digest.update(frame)
assert meta['cycle_ms'] == 4200
assert len(set(meta['frame_sha256'])) > 1
command = json.loads((ROOT/'deployment/ps_arm_build_20261012/commands.json').read_text())[-1]
old = str(ROOT/'deployment/sixmic_lcd_gif_20261012.cpp')
command = [str(HERE/'sixmic_lcd_player.cpp') if x.replace('\\','/') == old.replace('\\','/') else x for x in command]
command[command.index('-o')+1] = str(HERE/'sixmic-lcd-player')
command.remove('-lQt5Gui')
(HERE/'build_command.json').write_text(json.dumps(command, indent=2))
build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(HERE/'arm_build.log').write_bytes(build.stdout)
assert build.returncode == 0, 'ARM compile failed: see arm_build.log'
elf = (HERE/'sixmic-lcd-player').read_bytes()
assert elf[:5] == b'\x7fELF\x01' and int.from_bytes(elf[18:20], 'little') == 40
entries = read_cpio(gzip.decompress((ROOT/'deployment/arm_runtime_20261012/runtime_base.cpio.gz').read_bytes()))
def add(name, data, mode=0o100644):
    entries[name] = {'fields':[0,mode,0,0,1,0,0,0,0,0,0,0,0], 'data':data}
add('usr/bin/sixmic-lcd-player', elf, 0o100755)
add('tmp/good.lcd', package)
add('tmp/truncated.lcd', package[:-1])
badsize = bytearray(package); struct.pack_into('<H', badsize, 8, 319)
add('tmp/badsize.lcd', bytes(badsize))
baddelay = bytearray(package); struct.pack_into('<I', baddelay, 16, 0)
add('tmp/baddelay.lcd', bytes(baddelay))
init = b'''#!/bin/sh
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /run/sixmic
. /etc/sixmic/runtime.env
/usr/bin/sixmic-lcd-player --test --asset /tmp/good.lcd
echo GOOD_EXIT=$?
for name in truncated badsize baddelay missing; do
    /usr/bin/sixmic-lcd-player --test --asset /tmp/$name.lcd
    echo ${name}_EXIT=$?
done
echo LCD_TEST_DONE
reboot -f
'''
add('init', init, 0o100755)
archive = HERE/'lcd_test.cpio.gz'
archive.write_bytes(gzip.compress(write_cpio(entries), mtime=0))
qemu = 'D:/2025.2/data/emulation/qemu_win/qemu/qemu-system-arm.exe'
run = subprocess.run([qemu,'-M','xilinx-zynq-a9','-m','1024','-display','none','-serial','stdio',
    '-kernel',str(ROOT/'deployment/vendor_image_20261012/kernel.bin'),
    '-dtb',str(ROOT/'deployment/arm_runtime_20261012/qemu_system.dtb'),
    '-initrd',str(archive),'-append','console=ttyPS0,115200 rdinit=/init','-no-reboot'],
    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=55)
(HERE/'qemu_lcd.log').write_bytes(run.stdout)
for marker in ['GOOD_EXIT=0','truncated_EXIT=2','badsize_EXIT=2','baddelay_EXIT=2','missing_EXIT=2',
               'LCD_TEST_DONE', 'frames=42 width=320 height=172 frame_bytes=110080 cycle_ms=4200',
               digest.hexdigest()]:
    assert marker.encode() in run.stdout, marker
result = dict(conversion_checks='PASS', arm_cross_compile='PASS', qemu_arm_loader='PASS',
              negative_loader_cases=4, frames=count, cycle_ms=4200, frame_bytes=110080,
              pixel_stream_sha256=digest.hexdigest(), physical_board_test=False,
              lcd_transport_test=False, vivado_run=False)
(HERE/'verification.json').write_text(json.dumps(result, indent=2))
archive.unlink()  # Large, reproducible test initrd; retain command, binary and full run log.
print(json.dumps(result))
