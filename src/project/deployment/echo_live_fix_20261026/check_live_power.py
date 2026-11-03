from pathlib import Path
import json
H=Path(__file__).resolve().parent
s=(H/'probe_cadence.py').read_text()
s=s.replace('>3:break','>5:break').replace('range(300)','range(2000)')
s=s.replace(' rows.append(row)', ''' if typ==6 and row.get('resultWords')==1025:
  values=struct.unpack_from('<1025f',data,64)
  row.update(powerMin=min(values),powerMax=max(values),powerSum=sum(values),nonzeroBins=sum(x!=0 for x in values),peakBin=max(range(len(values)),key=lambda i:values[i]),payloadHash=hashlib.sha256(data[64:]).hexdigest())
 rows.append(row)''')
s=s.replace("'STREAM_CADENCE.json'","'LIVE_POWER_RESPONSE.json'")
s=s[:s.index('print(json.dumps')]+'''print(json.dumps([p for p in rows if 'powerMax' in p]),flush=True)
b.close();r.close();c.close()
'''
exec(compile(s,str(H/'probe_binary.py'),'exec'),{'__file__':str(H/'probe_binary.py')})
