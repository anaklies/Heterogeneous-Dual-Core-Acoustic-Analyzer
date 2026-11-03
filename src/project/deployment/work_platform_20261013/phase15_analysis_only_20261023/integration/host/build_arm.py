from pathlib import Path
import subprocess,json
here=Path(__file__).resolve().parent
root=here.parents[4]
sysroot=root/'deployment/ps_arm_sysroot_20261012/sysroot'
cc='D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin/arm-linux-gnueabihf-gcc.exe'
args=[cc,'--sysroot='+str(sysroot),'-I'+str(sysroot/'usr/include/arm-linux-gnueabihf'),'-O2','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-std=c99','-Wall','-Wextra','-Werror','-no-pie',
 '-B'+str(sysroot/'usr/lib/gcc/arm-linux-gnueabihf/11')+'/', '-L'+str(sysroot/'usr/lib/gcc/arm-linux-gnueabihf/11'),
 '-B'+str(sysroot/'usr/lib/arm-linux-gnueabihf')+'/', '-L'+str(sysroot/'usr/lib/arm-linux-gnueabihf'),'-L'+str(sysroot/'lib/arm-linux-gnueabihf'),
 '-Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3','-Wl,-rpath-link,'+str(sysroot/'usr/lib/arm-linux-gnueabihf'),'-Wl,-rpath-link,'+str(sysroot/'lib/arm-linux-gnueabihf'),str(here/'sixmic_host.c'),str(here/'sixmic_supervisor.c'),'-o',str(here/'sixmic-supervisor-arm')]
(here/'ARM_BUILD_COMMAND.json').write_text(json.dumps(args,indent=2))
r=subprocess.run(args,capture_output=True,text=True);(here/'ARM_BUILD.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
print('SUPERVISOR_ARM_BUILD_PASS compiled only; board watchdog NOT TESTED')
