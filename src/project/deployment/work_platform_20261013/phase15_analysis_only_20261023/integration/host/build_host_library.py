from pathlib import Path
import subprocess,json,os
here=Path(__file__).resolve().parent;root=here.parents[4]
sysroot=root/'deployment/ps_arm_sysroot_20261012/sysroot'
tool=Path('D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
flags=['--sysroot='+str(sysroot),'-I'+str(sysroot/'usr/include/arm-linux-gnueabihf'),'-O2','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-std=c99','-Wall','-Wextra','-Werror']
temp=root/'tmp/host_sdk_build';temp.mkdir(parents=True,exist_ok=True);env=dict(os.environ,TEMP=str(temp),TMP=str(temp),TMPDIR=str(temp))
objects=[];commands=[]
for name in ['sixmic_host','service_result','profile_upload','raw_cursor','fft_snapshot']:
 obj=here/(name+'_arm.o');cmd=[str(tool/'arm-linux-gnueabihf-gcc.exe'),*flags,'-c',str(here/(name+'.c')),'-o',str(obj)];commands.append(cmd);subprocess.run(cmd,check=True,env=env);objects.append(str(obj))
cmd=[str(tool/'arm-linux-gnueabihf-ar.exe'),'rcs',str(here/'libsixmic_host_arm.a'),*objects];commands.append(cmd);subprocess.run(cmd,check=True,env=env)
(here/'HOST_ARM_COMMANDS.json').write_text(json.dumps(commands,indent=2));print('HOST_ARM_LIBRARY_BUILD_PASS Cortex-A9 C ABI configuration service results private upload live raw cursor; physical not tested')

