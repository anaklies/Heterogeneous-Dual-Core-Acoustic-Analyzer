from pathlib import Path
import subprocess,json
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
s=ROOT/'deployment/ps_arm_sysroot_20261012/sysroot'
tools=Path('D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
lib=s/'usr/lib/arm-linux-gnueabihf';gcc=s/'usr/lib/gcc/arm-linux-gnueabihf/11'
flags=['--sysroot='+str(s),'-O2','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-Wall','-Wextra','-Werror','-fPIC','-I'+str(s/'usr/include/arm-linux-gnueabihf')]
ld=['-B'+str(gcc)+'/', '-L'+str(gcc),'-B'+str(lib)+'/', '-L'+str(lib),'-L'+str(s/'lib/arm-linux-gnueabihf'),'-Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3','-Wl,-rpath-link,'+str(lib),'-Wl,-rpath-link,'+str(s/'lib/arm-linux-gnueabihf')]
qt=s/'usr/include/arm-linux-gnueabihf/qt5'
cpp=['-std=c++11','-D__remove_cv=__sixmic_remove_cv','-nostdinc++']+['-I'+str(s/p) for p in ['usr/include/c++/11','usr/include/arm-linux-gnueabihf/c++/11','usr/include/c++/11/backward']]+['-I'+str(qt),'-I'+str(qt/'QtCore'),'-I'+str(qt/'QtGui')]
commands=[([tools/'arm-linux-gnueabihf-gcc.exe',*flags,'-std=c99',HERE/'echo_health.c',*ld,'-o',HERE/'transfer/echo-health'],'health'),([tools/'arm-linux-gnueabihf-g++.exe',*flags,*cpp,HERE/'echo_lcd_gif.cpp',*ld,'-lQt5Gui','-lQt5Core','-lpthread','-o',HERE/'transfer/echo-lcd-gif'],'lcd')]
host=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/host'
commands.append(([tools/'arm-linux-gnueabihf-gcc.exe',*flags,'-std=c99','-I'+str(host),HERE/'read_input_stats.c',host/'sixmic_host.c',*ld,'-o',HERE/'transfer/read-input-stats'],'input-stats'))
for cmd,label in commands:
 r=subprocess.run(list(map(str,cmd)),capture_output=True);(HERE/(label+'_build.log')).write_bytes(r.stdout+r.stderr)
 if r.returncode:raise SystemExit(label+' build failed')
 print('ARM_BUILD_PASS',label)
