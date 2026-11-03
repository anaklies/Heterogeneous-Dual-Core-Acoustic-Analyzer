"""Compile with the existing ARM Qt5 sysroot; no BSP or FPGA changes."""
from pathlib import Path
import subprocess,json,os
HERE=Path(__file__).resolve().parent;ROOT=Path(os.environ.get('SIXMIC_WORKSPACE',str(HERE.parents[1]))).resolve()
sysroot=ROOT/'deployment/ps_arm_sysroot_20261012/sysroot';out=HERE/'build/arm';out.mkdir(parents=True,exist_ok=True)
tool=Path('D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
cxx=tool/'arm-linux-gnueabihf-g++.exe'
common=['--sysroot='+str(sysroot),'-O2','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-Wall','-Wextra','-Werror','-fPIC','-std=c++11','-D__remove_cv=__sixmic_remove_cv','-nostdinc++']
inc=['-I'+str(sysroot/p) for p in ['usr/include/c++/11','usr/include/arm-linux-gnueabihf/c++/11','usr/include/c++/11/backward','usr/include/arm-linux-gnueabihf']]
qt=sysroot/'usr/include/arm-linux-gnueabihf/qt5';inc+=['-I'+str(qt)]+['-I'+str(qt/m) for m in ['QtCore','QtGui','QtWidgets','QtNetwork']]
lib=sysroot/'usr/lib/arm-linux-gnueabihf';base=sysroot/'usr/lib/gcc/arm-linux-gnueabihf/11'
ld=['-B'+str(base)+'/', '-L'+str(base),'-B'+str(lib)+'/', '-L'+str(lib),'-L'+str(sysroot/'lib/arm-linux-gnueabihf'),'-Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3','-Wl,-rpath-link,'+str(lib),'-Wl,-rpath-link,'+str(sysroot/'lib/arm-linux-gnueabihf')]
commands=[]
def run(args,name):
    commands.append(list(map(str,args)));r=subprocess.run(list(map(str,args)),capture_output=True)
    (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError(name+' failed, see log')
for name in ['main','client']:run([cxx,*common,*inc,'-c',HERE/'app'/(name+'.cpp'),'-o',out/(name+'.o')],name)
run([cxx,*common,*ld,out/'main.o',out/'client.o','-lQt5Widgets','-lQt5Gui','-lQt5Network','-lQt5Core','-lpthread','-o',out/'echo-portable'],'link')
b=(out/'echo-portable').read_bytes();assert b[:5]==b'\x7fELF\x01' and int.from_bytes(b[18:20],'little')==40 and int.from_bytes(b[36:40],'little')&0x400
(out/'commands.json').write_text(json.dumps(commands,indent=2))
(out/'ELF_CHECK.json').write_text(json.dumps(dict(status='ARM_BUILD_PASS',machine=40,hardFloat=True,bytes=len(b),hardwareDisplayTested=False),indent=2))
print('ARM_BUILD_PASS',len(b),'bytes, ELF32 Cortex-A9 hard-float; display not tested')
