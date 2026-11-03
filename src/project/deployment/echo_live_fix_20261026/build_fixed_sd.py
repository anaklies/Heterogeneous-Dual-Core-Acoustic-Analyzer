from pathlib import Path
import sys,gzip,hashlib,struct,zlib,json,shutil,os
H=Path(__file__).resolve().parent; R=H.parents[1]
sys.path.insert(0,str(R/'deployment'))
from firmware_formats_20261012 import read_fdt,write_fdt,read_cpio,write_cpio
O=Path(os.environ.get('ECHO_SD_OUTPUT_DIR',str(H/'fixed_sd'))); O.mkdir(parents=True,exist_ok=True)
fit,res,cpu=read_fdt((R/'deployment/echo_interface_guard_20261026/image.ub').read_bytes())
images=fit.child('images'); ram=next(n for n in images.children if n.properties.get('type')==b'ramdisk\0')
entries=read_cpio(gzip.decompress(ram.properties['data']))
def add(name,data,mode=0o100644):
 for p in reversed(Path(name).parents):
  k=p.as_posix()
  if k!='.' and k not in entries: entries[k]={'fields':[0,0o40755,0,0,2,0,0,0,0,0,0,0,0],'data':b''}
 entries[name]={'fields':[0,mode,0,0,1,0,0,0,0,0,0,0,0],'data':data}
runtime=(H/'echo-runtime').read_text()
runtime=runtime.replace('    modprobe uio_pdrv_genirq', '    if ! ip -4 addr show dev eth0 | grep -q "inet "; then ifconfig eth0 192.168.77.2 netmask 255.255.255.0 up; fi\n    modprobe uio_pdrv_genirq')
add('opt/echo/bin/echo-runtime',runtime.encode(),0o100755)
for n in ['echo-health','echo-lcd-gif']:add('opt/echo/bin/'+n,(H/'transfer'/n).read_bytes(),0o100755)
add('opt/echo/bin/echo-portable',(H/'build/arm/echo-portable').read_bytes(),0o100755)
add('opt/echo/bin/echo-gateway',(R/'deployment/echo_interface_guard_20261026/build/arm/echo-gateway').read_bytes(),0o100755)
room_overlay=R/'deployment/echo_room_and_metrics_fix_20261029/registry'
if (room_overlay/'SOFTWARE_ACCEPTED').exists():
 for p in room_overlay.rglob('*'):
  if p.is_file() and p.suffix in ('.json','.smp'):add('opt/echo/registry/'+p.relative_to(room_overlay).as_posix(),p.read_bytes())
xkb=R/'deployment/ps_arm_sysroot_20261012/sysroot/usr/share/X11/xkb'
for p in xkb.rglob('*'):
 if p.is_file():add('opt/echo/share/X11/xkb/'+p.relative_to(xkb).as_posix(),p.read_bytes())
ordered=dict(sorted(entries.items(),key=lambda v:(len(Path(v[0]).parts),0 if v[1]['fields'][1]&0o170000==0o040000 else 1,v[0])))
ram.properties['data']=gzip.compress(write_cpio(ordered),mtime=0)
dtb=(R/'deployment/echo_boot_diagnosis_20261026/system_bootdiag.dtb').read_bytes()
for n in images.children:
 if n.properties.get('type')==b'flat_dt\0':n.properties['data']=dtb
 if 'data' in n.properties:
  for c in n.children:
   if c.name.startswith('hash'):
    a=c.properties['algo'].rstrip(b'\0').decode();d=n.properties['data']
    c.properties['value']=struct.pack('>I',zlib.crc32(d)) if a=='crc32' else hashlib.new(a,d).digest()
(O/'image.ub').write_bytes(write_fdt(fit,res,cpu));(O/'system.dtb').write_bytes(dtb)
script=b'''echo "ECHO corrected SD boot"
setenv initrd_high 0xffffffff
setenv fdt_high 0xffffffff
if fatload mmc 0:1 0x04000000 image.ub; then
 if fatload mmc 0:1 0x02000000 system.dtb; then
  bootm 0x04000000:kernel-1 0x04000000:ramdisk-1 0x02000000
 fi
fi
echo "ECHO SD boot failed"
'''
body=struct.pack('>II',len(script),0)+script
h=struct.pack('>7I4B32s',0x27051956,0,0,len(body),0,0,zlib.crc32(body),5,2,6,0,b'ECHO corrected SD boot')
h=h[:4]+struct.pack('>I',zlib.crc32(h))+h[8:]
(O/'boot.scr').write_bytes(h+body)
for n in ['BOOT.BIN','ECHO_RELEASE.json']:
 shutil.copy2(R/'deployment/echo_sd_write_20261026/boot_files'/n,O/n)
release=json.loads((O/'ECHO_RELEASE.json').read_text())
release.update(version=os.environ.get('ECHO_RELEASE_VERSION','20261029-auto-input-room-and-weighting-fix'),PSImageReused=False,newBitstream=False,newBOOT=False,
 gatewayHotfix='20261029-auto-input-lock-background-reference-event-monitor',
 gatewaySHA256=hashlib.sha256((R/'deployment/echo_interface_guard_20261026/build/arm/echo-gateway').read_bytes()).hexdigest(),
 imageSHA256=hashlib.sha256((O/'image.ub').read_bytes()).hexdigest(),PC_PS_APIChanged=False,algorithmChanged=True,roomAlgorithmRevision="auto-input-background-reference-1s-20261029",spectralKurtosisFrames=8,
 runtimeLinkTested=True,psP1ViewQueueBounded=True,panelSHA256=hashlib.sha256((H/"build/arm/echo-portable").read_bytes()).hexdigest(),referenceRetentionTested=True,stipaFinalResultAccepted=False,liveFftProtocol="echo-live-fft-1",liveStreamObservedHz=22.4,displayMaxHz=5.0,displayTransitionMs=100,hardwareAccepted=False)
release.update(eventLoopRecording=True,eventStorageLimitBytes=536870912,eventLoopHighWatermark=0.9,eventLoopTargetWatermark=0.8,eventBackgroundHardwareReadback=False,pcTimeSyncOptional=True)
(O/'ECHO_RELEASE.json').write_text(json.dumps(release,indent=2)+'\n')
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in O.iterdir() if p.is_file() and p.name!='SHA256SUMS'}
(O/'SHA256SUMS').write_bytes(''.join(f'{v}  {k}\n' for k,v in manifest.items()).encode())
for n in ['image.ub','system.dtb','boot.scr','SHA256SUMS']:shutil.copy2(O/n,H/'transfer'/n)
print(json.dumps(manifest,indent=2))
