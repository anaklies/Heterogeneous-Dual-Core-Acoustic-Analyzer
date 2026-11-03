import struct
from ui.viewmodels.feature_codec import decode_feature_result

def f32w(v): return struct.unpack("<I", struct.pack("<f", v))[0]

def test_scalars_layout():
    words=[0,0,f32w(1.5),7]
    raw=struct.pack("<" + "I"*len(words), *words)
    out=decode_feature_result({"schema":{"kind":"scalars","encoding":"LE float32","units":"FS","layout":{"fields":{"a":{"offset":2,"type":"float32"},"b":{"offset":3,"type":"uint32"}}}}}, raw)
    assert out["render"]=="scalars" and out["scalars"]["a"]==1.5 and out["scalars"]["b"]==7

def test_triplet_series():
    words=[1,2,3,4,5,6]
    raw=struct.pack("<"+"I"*6,*words)
    out=decode_feature_result({"schema":{"kind":"tensor","units":"FS","axes":{"centersHz":[100,200]},
        "layout":{"fields":{"triplets":{"offset":0,"count":2,"fields":["amp","psd","bin"]}}}}}, raw)
    assert out["render"]=="line" and len(out["series"])==3
    assert out["series"][0]["points"]==[[100.0,1.0],[200.0,4.0]]

def test_actual_producer_layout_precedence():
    words=[10,20,30,40]
    raw=struct.pack("<"+"I"*4,*words)
    schema={"kind":"scalars","actualProducerLayout":{"fields":{"p":0,"q":0}},"producerLayout":{"fields":{"p":2}}}
    out=decode_feature_result({"schema":schema}, raw)
    assert out["render"]=="scalars" and out["scalars"]["p"]==10

def test_waveform_pcm24():
    words=[0xFFFFFF,0x000001]
    raw=struct.pack("<II",*words)
    out=decode_feature_result({"schema":{"kind":"waveform","axes":{"channels":1}}}, raw)
    assert out["render"]=="waveform" and out["channels"][0]==[-1.0,1.0]

def test_missing_layout_no_guess():
    raw=struct.pack("<I",1)
    out=decode_feature_result({"schema":{"kind":"tensor","fields":["x"]}}, raw)
    assert out["available"] is False and out["reason"]=="missing-producer-layout"
