from pathlib import Path
import json
P=Path(__file__).resolve().parents[1];M=P.parent/'phase12m_product_algorithm_acceptance_20261021'
old=json.loads((M/'PRODUCT_ALGORITHMS.json').read_text(encoding='utf-8'))
groups={tier:[r['id'] for r in old if r['productTier']==tier and r['softwareStatus']!='deferred_experimental'] for tier in ['P0','P1','P2']}
# M's event entry was deferred. N implemented it; the old offline rectified path remains deferred.
groups['P1'].append('event_trigger')
groups['P1']+=['frequency_time_weighting','level_statistics']
groups['P2']+=['room_decay','relative_insulation','stipa_experimental','noise_rating','room_clarity','spectral_decay']
rows=[]
for tier in ['P0','P1','P2']:
    for name in groups[tier]:rows.append(dict(id=name,bit=len(rows),tier=tier,softwareReference=True,wholeBoardAccepted=False))
assert len(rows)==52 and len({r['id'] for r in rows})==52
masks={t:sum(1<<r['bit'] for r in rows if r['tier']==t) for t in groups}
value=dict(protocolVersion='sixmic-analysis/1',functions=rows,tierMasks=masks,
           actualHardwareCapabilityMask=0,algorithmVersionWhenNoBackend=0,
           warning='Registered software functions are not automatically deployed hardware capabilities')
(P/'interfaces/FUNCTION_REGISTRY.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
h='#ifndef SIXMIC_ANALYSIS_REGISTRY_H\n#define SIXMIC_ANALYSIS_REGISTRY_H\n#include <stdint.h>\n'
for r in rows:h+=f'#define SIXMIC_FN_{r["id"].upper()} (UINT64_C(1)<<{r["bit"]})\n'
for t,m in masks.items():h+=f'#define SIXMIC_{t}_MASK UINT64_C(0x{m:016x})\n'
h+='\n#define SIXMIC_ABI_VERSION UINT32_C(0x00010000)\n#define SIXMIC_MAGIC UINT32_C(0x534d4131)\n#endif\n'
(P/'interfaces/function_registry.h').write_text(h)
print('REGISTERED_SOFTWARE_FUNCTIONS',len(rows),{k:len(v) for k,v in groups.items()})
