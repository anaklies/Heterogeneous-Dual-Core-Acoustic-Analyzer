from pathlib import Path
import wave
from sixmic_backend.data.event_audio import write_event_audio
from sixmic_backend.protocol.event_file import build_event_container,parse_event_container
from sixmic_backend.protocol.pcm import encode_record
from sixmic_backend.model.audio import read_24bit_wav

def sample(indices):
 records=b''.join(encode_record([100,-200,300,-400,500,-600],i) for i in indices)
 return parse_event_container(build_event_container(event_id=123,flags=0,clip_reason=1,first_sample_index=indices[0],last_sample_index=indices[-1],sample_rate_hz=48000,records=records))

def test_timestamp_wav_contains_all_six_channels(tmp_path):
 c=sample([10,11,12]);r=write_event_audio(c,tmp_path,1793270680512)
 assert len(r['wavFiles'])==1 and '123' not in Path(r['wavFiles'][0]).stem
 raw,meta=read_24bit_wav(r['wavFiles'][0]);assert meta['channels']==6
 # readback reconstructs only PCM words; recorded indices remain in SMC.
 assert raw[:24]==c.records[:24]
 with wave.open(r['wavFiles'][0],'rb') as f:assert f.getnframes()==3
 assert write_event_audio(c,tmp_path,1793270680512)['wavFiles']==r['wavFiles']

def test_gap_is_split_and_received_time_is_marked(tmp_path):
 r=write_event_audio(sample([0,1,5,6]),tmp_path,1793270680512,received_time=True)
 assert len(r['wavFiles'])==2 and r['gapsSplit']
 assert all(Path(p).name.startswith('接收_') for p in r['wavFiles'])
 assert r['syntheticSamplesInserted']==0 and r['timeBasis']=='received'
