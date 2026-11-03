from pathlib import Path
import json
B=Path(__file__).resolve().parent
P=B.parent
R=P/'src/project'
old=json.loads((B/'PACKAGE_INFO.json').read_text(encoding='utf-8'))['originalWorkspace'].replace('\\','/')
source=R/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/shared_backend'
out=B/'out/hls_configs';out.mkdir(parents=True,exist_ok=True)
for name in ['scalar.cfg','stream.cfg','hier.cfg']:
 text=(source/name).read_text(encoding='utf-8').replace(old,R.as_posix())
 for line in text.splitlines():
  if line.startswith('syn.file='):assert Path(line.partition('=')[2]).is_file(),line
 (out/name).write_text(text,encoding='utf-8')
print('HLS_CONFIGS_RELOCATED',out)
