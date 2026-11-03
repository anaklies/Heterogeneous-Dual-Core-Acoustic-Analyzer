import struct
from sixmic_backend.data.events import EventManager

def test_live_gateway_event_metadata_is_normalized(tmp_path):
 m=EventManager(tmp_path)
 event=m.ingest_known({'eventId':'9007199254740993','sourceKind':'pl-live',
   'flags':9,'firstSampleIndex':'100','lastSampleIndex':'199','recordCount':'100',
   'sampleRateFloat32Bits':struct.unpack('<I',struct.pack('<f',48000))[0],
   'totalBytes':'3264','sha256':'a'*64,'acked':True}).to_dict()
 assert event['flags']['incomplete'] and event['flags']['envInvalid']
 assert not event['flags']['poseInvalid']
 assert event['sampleRateHz']==48000 and event['frames']==100
 assert event['capturedFirstSampleIndex']=='100'
 assert event['file']['state']=='available' and event['ack']['acked']
