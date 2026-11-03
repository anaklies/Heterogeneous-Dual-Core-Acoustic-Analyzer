from pathlib import Path
import subprocess,json,os,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
arm='--arm' in sys.argv;gw=HERE/'gateway';out=HERE/'build'/('arm' if arm else 'host');out.mkdir(parents=True,exist_ok=True)
integration=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/host'
wire=ROOT/'interfaces/pc_backend_v1/c'
tool=Path('D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin/arm-linux-gnueabihf-gcc.exe') if arm else Path('D:/mingw64/bin/gcc.exe')
flags=['-O2','-std=c99','-Wall','-Wextra','-Werror','-I'+str(gw/'include'),'-I'+str(integration),'-I'+str(wire)]
link=[]
if arm:
 s=ROOT/'deployment/ps_arm_sysroot_20261012/sysroot';lib=s/'usr/lib/arm-linux-gnueabihf';gcc=s/'usr/lib/gcc/arm-linux-gnueabihf/11'
 flags+=['--sysroot='+str(s),'-I'+str(s/'usr/include/arm-linux-gnueabihf'),'-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-no-pie','-D_GNU_SOURCE']
 link=['-B'+str(gcc)+'/', '-L'+str(gcc),'-B'+str(lib)+'/', '-L'+str(lib),'-L'+str(s/'lib/arm-linux-gnueabihf'),'-Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3','-Wl,-rpath-link,'+str(lib),'-Wl,-rpath-link,'+str(s/'lib/arm-linux-gnueabihf')]
else:flags+=['-D_WIN32_WINNT=0x0601'];link=['-lws2_32']
sources=[f for f in (gw/'src').glob('*.c') if f.name!='main.c']+[integration/'sixmic_host.c',integration/'service_result.c']
commands=[]
def build(name,src):
 args=[tool,*flags,*src,*link,'-o',out/(name+('' if arm else '.exe'))];commands.append(list(map(str,args)))
 r=subprocess.run(list(map(str,args)),capture_output=True);(out/(name+'.log')).write_bytes(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError(name+' failed, read '+str(out/(name+'.log')))
 print('BUILD_PASS',name,flush=True)
if '--fixture-only' in sys.argv:
 build('test-feature-server',[*sources,gw/'tests/test_feature_server.c',integration/'profile_upload.c'])
 sys.exit(0)
build('echo-gateway',[*sources,gw/'src/main.c'])
build('echo-bootstrap',[HERE/'echo_bootstrap.c',gw/'src/json.c',gw/'src/utf8.c',gw/'src/sha256.c',integration/'profile_upload.c',integration/'sixmic_host.c'])
if arm:build('echo-pl-watchdog',[integration/'sixmic_supervisor.c',integration/'sixmic_host.c'])
if not arm and '--minimal' not in sys.argv:
 build('test-gateway',[*sources,gw/'tests/fake_mmio.c',gw/'tests/test_client.c',gw/'tests/test_gateway.c'])
 build('test-echo',[*sources,gw/'tests/fake_mmio.c',gw/'tests/test_echo.c'])
if not arm:
 build('test-feature-server',[*sources,gw/'tests/test_feature_server.c',integration/'profile_upload.c'])
(out/'services_commands.json').write_text(json.dumps(commands,indent=2))
