"""Replay recorded ARM builds without changing delivered binaries. See REPRODUCE.md."""
from pathlib import Path
import argparse,json,subprocess,zipfile
def relocate(value,root):
    s=str(value).replace('\\','/')
    while '//' in s:s=s.replace('//','/')
    old='C:/Users/sunxi/Desktop/sixmic3D'
    return s.replace(old,root.as_posix())
def main():
    p=argparse.ArgumentParser();p.add_argument('--toolchain-bin',type=Path,required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    B=Path(__file__).resolve().parent;R=B.parent/'src/project';sr=R/'deployment/ps_arm_sysroot_20261012/sysroot'
    logs=sorted((B/'recorded_commands').rglob('*commands.json'));n=0
    for log in logs:
        for command in json.loads(log.read_text(encoding='utf-8')):
            args=[relocate(v,R) for v in command]
            args[0]=str(a.toolchain_bin/Path(command[0].replace('\\','/')).name)
            for v in args[1:]:
                if v.lower().endswith(('.c','.cpp')) and not Path(v).is_file():raise FileNotFoundError(v)
            if not a.dry_run:
                if not sr.exists():
                    sr.mkdir(parents=True)
                    with zipfile.ZipFile(B/'deps/arm_sysroot.zip') as z:z.extractall(sr)
                if '-o' in args:Path(args[args.index('-o')+1]).parent.mkdir(parents=True,exist_ok=True)
                subprocess.run(args,check=True,cwd=R)
            n+=1
    if not n:raise RuntimeError('No recorded commands')
    print('ARM_COMMANDS_VALIDATED' if a.dry_run else 'ARM_REBUILD_PASS',n)
if __name__=='__main__':main()
