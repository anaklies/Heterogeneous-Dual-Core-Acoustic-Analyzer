"""Human-readable, gap-preserving WAV copies of verified event PCM. No DSP."""
from datetime import datetime
from pathlib import Path
import json,struct
from ..model.audio import write_wav6_24bit
from ..errors import BackendError

def write_event_audio(container, output: Path, unix_ms: int, *, received_time=False):
    if not container.header.record_count:raise BackendError('file_corrupt',{'reason':'event-has-no-audio'})
    output.mkdir(parents=True,exist_ok=True)
    stamp=datetime.fromtimestamp(unix_ms/1000).strftime('%Y-%m-%d_%H-%M-%S')+f'.{unix_ms%1000:03d}'
    if received_time:stamp='接收_'+stamp
    base=stamp;counter=1
    while (output/base).exists():
        try:existing=json.loads((output/base/'事件信息.json').read_text(encoding='utf8'))
        except (OSError,ValueError):existing={}
        if existing.get('wavFiles') and existing.get('sourceSha256')==container.sha256 and all(Path(p).is_file() for p in existing.get('wavFiles',[])):
            return existing
        counter+=1;base=f'{stamp}_{counter:02d}'
    folder=output/base;folder.mkdir()
    raw=container.records;stride=container.header.record_bytes;start=0;previous=None;segments=[]
    for pos in range(0,len(raw),stride):
        index=struct.unpack_from('<Q',raw,pos+24)[0]
        if previous is not None:
            if index<=previous:raise BackendError('file_corrupt',{'reason':'non-increasing-event-samples'})
            if index!=previous+1:segments.append((start,pos));start=pos
        previous=index
    segments.append((start,len(raw)));files=[];details=[]
    for i,(a,b) in enumerate(segments):
        suffix='_六通道' if len(segments)==1 else f'_六通道_片段{i+1:02d}'
        path=folder/(base+suffix+'.wav')
        details.append(write_wav6_24bit(path,raw[a:b],real_sample_rate_hz=container.header.sample_rate_hz));files.append(str(path))
    result={'eventId':str(container.header.event_id),'sourceSha256':container.sha256,
        'timeUnixMs':str(unix_ms),'timeBasis':'received' if received_time else 'device-saved',
        'folder':str(folder),'wavFiles':files,'audio':details,'gapsSplit':len(segments)>1,'syntheticSamplesInserted':0}
    temp=folder/'事件信息.json.tmp';temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(folder/'事件信息.json')
    return result
