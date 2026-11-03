"""Gateway/registry hotfix: reuse all hardware and DSP plans."""
from pathlib import Path
import gzip,hashlib,io,json,struct,sys,tarfile,zipfile,zlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'deployment'))
from firmware_formats_20261012 import read_cpio,write_cpio,read_fdt,write_fdt

def sha(b):return hashlib.sha256(b).hexdigest()
fixed=(HERE/'registry/INTERFACE_REGISTRY.json').read_bytes()
gateway=(HERE/'build/arm/echo-gateway').read_bytes()
assert gateway[:5]==b'\x7fELF\x01'
registry=json.loads(fixed)
f=next(f for f in registry['features'] if f['featureId']=='zoom_fft')
prep=json.loads((ROOT/'deployment/echo_feature_closure_20261025/registry'/f['acquisitionPreparationPlan']['file']).read_text())
assert all(f['acquisitionPreparationPlan'][k]==prep[k] for k in ['inputWords','inputWordOffset'])
checks=json.loads((HERE/'reports/ALL_51_PATHS.json').read_text())
assert checks['status']=='PASS' and checks['featureCount']==51
input_zip=ROOT/'deployment/releases/ECHO_Board_SeparateIO_ZoomFix_20261026_RC.zip'
output_zip=ROOT/'deployment/releases/ECHO_Board_SeparateIO_InterfaceFix_20261026_RC.zip'
prefix='ECHO_Board_SeparateIO_InterfaceFix_20261026_RC/'
with zipfile.ZipFile(input_zip) as src:
    original={n.split('/',1)[1]:n for n in src.namelist()}
    image=src.read(original['sd/image.ub'])
    fit,reserves,cpu=read_fdt(image)
    ramdisk=next(n for n in fit.child('images').children if n.properties.get('type',b'').rstrip(b'\0')==b'ramdisk')
    entries=read_cpio(gzip.decompress(ramdisk.properties['data']))
    target='opt/echo/registry/INTERFACE_REGISTRY.json'
    before_hash=sha(entries[target]['data'])
    old=json.loads(entries[target]['data']);old_feature=next(f for f in old['features'] if f['featureId']=='zoom_fft')
    assert old_feature['acquisitionPreparationPlan']['inputWords']==4159
    assert old_feature['acquisitionPreparationPlan']['inputWordOffset']==1069056
    entries[target]['data']=fixed
    entries['opt/echo/bin/echo-gateway']['data']=gateway
    ramdisk.properties['data']=gzip.compress(write_cpio(entries),compresslevel=6,mtime=0)
    for node in fit.child('images').children:
        if 'data' not in node.properties:continue
        for child in node.children:
            if child.name.startswith('signature'):raise RuntimeError('Cannot modify a signed FIT')
            if not child.name.startswith('hash'):continue
            algo=child.properties.get('algo',b'').rstrip(b'\0').decode()
            if algo in ['sha1','sha256']:child.properties['value']=hashlib.new(algo,node.properties['data']).digest()
            elif algo=='crc32':child.properties['value']=struct.pack('>I',zlib.crc32(node.properties['data']))
            else:raise RuntimeError('Unknown FIT hash')
    image_fixed=write_fdt(fit,reserves,cpu)
    # The filesystem archive contains the same device registry as image.ub.
    old_payload=src.read(original['echo-emmc-apps.tar.gz']);payload_file=HERE/'echo-emmc-apps.tar.gz'
    with tarfile.open(fileobj=io.BytesIO(old_payload),mode='r:gz') as tf,tarfile.open(payload_file,'w:gz',compresslevel=3) as out:
        found=0
        for info in tf:
            if info.isfile():
                data=fixed if info.name=='registry/INTERFACE_REGISTRY.json' else gateway if info.name=='bin/echo-gateway' else tf.extractfile(info).read()
                if info.name=='registry/INTERFACE_REGISTRY.json':found+=1
                info.size=len(data);out.addfile(info,io.BytesIO(data))
            else:out.addfile(info)
        assert found==1
    (HERE/'image.ub').write_bytes(image_fixed)
    (HERE/'INTERFACE_REGISTRY.json').write_bytes(fixed)
    report={'date':'2026-10-26','fix':'typed band reference; nonblank reference declaration; config/event permission guards',
            'inputWords':prep['inputWords'],'inputWordOffset':prep['inputWordOffset'],
            'addressUnits':'32-bit words in the PL analysis arena, not bytes/FFT-bin index',
            'registryBeforeSHA256':before_hash,'registryAfterSHA256':sha(fixed),
            'onlyDeviceRegistryChanged':False,'PLChanged':False,'gatewayBinaryChanged':True,
            'gatewaySHA256':sha(gateway),
            'networkProtocolChanged':False,'physicalBoardTested':False,
            'test':checks}
    (HERE/'FIX_STATUS.json').write_text(json.dumps(report,indent=2)+'\n')
    replacements={
        'sd/image.ub':image_fixed,
        'echo-emmc-apps.tar.gz':payload_file.read_bytes(),
        'interfaces/INTERFACE_REGISTRY.json':fixed,
        'FIX_STATUS.json':(HERE/'FIX_STATUS.json').read_bytes(),
        '接口保护修复说明.md':(HERE/'README.md').read_bytes(),
        'gateway/src/feature_runtime.c':(HERE/'gateway/src/feature_runtime.c').read_bytes(),
        'gateway/tests/test_feature_server.c':(HERE/'gateway/tests/test_feature_server.c').read_bytes(),
        'build_services.py':(HERE/'build_services.py').read_bytes(),
        'validation/ALL_51_PATHS.json':(HERE/'reports/ALL_51_PATHS.json').read_bytes(),
        'validation/check_all_paths.py':(HERE/'tests/check_all_paths.py').read_bytes(),
        'interfaces/51_FEATURE_CALLS.csv':(ROOT/'deployment/echo_feature_closure_20261025/51_FEATURE_CALLS.csv').read_bytes()}
    release=json.loads(src.read(original['RELEASE.json']));release.update(registryHotfix='20261026-zoom-preparation-1',gatewayHotfix='20261026-interface-guards-1',registrySHA256=sha(fixed),gatewaySHA256=sha(gateway),softwarePathsPassed=51,hardwareAccepted=False)
    replacements['RELEASE.json']=json.dumps(release,indent=2).encode()
    replacements['sd/ECHO_RELEASE.json']=replacements['RELEASE.json']
    payload_names=['echo-emmc-apps.tar.gz','sd/BOOT.BIN','sd/image.ub','sd/system.dtb']
    replacements['PAYLOAD.sha256']=''.join(sha(replacements[n] if n in replacements else src.read(original[n]))+'  '+n+'\n' for n in payload_names).encode()
    hashes={}
    with zipfile.ZipFile(output_zip,'w',compression=zipfile.ZIP_STORED) as dst:
        for rel,name in original.items():
            if rel=='SHA256SUMS.txt':continue
            data=replacements.pop(rel,None)
            if data is None:data=src.read(name)
            dst.writestr(prefix+rel,data);hashes[rel]=sha(data)
        for rel,data in replacements.items():dst.writestr(prefix+rel,data);hashes[rel]=sha(data)
        dst.writestr(prefix+'SHA256SUMS.txt',''.join(h+'  '+n+'\n' for n,h in sorted(hashes.items())))
    # Prove the executable hardware/kernel were reused, not silently replaced.
    with zipfile.ZipFile(output_zip) as dst:
        for rel in ['sd/BOOT.BIN','sd/echo_separate_io.bit','sd/echo_separate_io.xsa','sd/system.dtb']:
            assert dst.read(prefix+rel)==src.read(original[rel])
    # Keep the mutable build staging assets current; published old ZIPs stay intact.
    board=ROOT/'deployment/echo_board_release_20261026'
    (board/'sd/image.ub').write_bytes(image_fixed)
    (board/'echo-emmc-apps.tar.gz').write_bytes(payload_file.read_bytes())
    (board/'build/arm/echo-gateway').write_bytes(gateway)
    (board/'gateway/src/feature_runtime.c').write_bytes((HERE/'gateway/src/feature_runtime.c').read_bytes())
    (board/'interfaces/INTERFACE_REGISTRY.json').write_bytes(fixed)
with zipfile.ZipFile(ROOT/'deployment/releases/ECHO_Interface_Guards_Hotfix_20261026.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
    for n in ['INTERFACE_REGISTRY.json','README.md','FIX_STATUS.json']:z.write(HERE/n,n)
    z.write(HERE/'build/arm/echo-gateway','echo-gateway')
    z.write(HERE/'reports/ALL_51_PATHS.json','ALL_51_PATHS.json')
print('INTERFACE_FIX_PACKAGE_READY',output_zip)
