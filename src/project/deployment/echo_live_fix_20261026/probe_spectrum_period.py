import socket,json,struct,zlib,hashlib,time
from pathlib import Path
c=socket.create_connection(('192.168.77.2',48120),3);c.settimeout(3);r=c.makefile('rb');seq=0;session=None
def call(op,args):
 global seq,session
 seq+=1;q={'protocol':'sixmic-analysis','version':1,'requestId':str(seq),'op':op,'args':args}
 if session:q['sessionId']=session
 c.sendall(json.dumps(q).encode()+b'\n')
 while True:
  v=json.loads(r.readline())
  if v.get('requestId')==str(seq):break
 assert v['status']=='ok',v
 return v['result']
h=call('hello',dict(clientName='binary-live-probe',clientVersion='1',maxBinaryPayloadBytes=1048576));session=h['sessionId'];epoch=int(h['connectionEpoch'])
sub=call('subscribe',{'streams':[{'type':'resultWords'},{'type':'serviceSnapshot'}],'deliverSchema':True});opened=call('stream.open',{'subscriptionId':sub['subscriptionId']})
b=socket.create_connection(('192.168.77.2',opened['port']),3);b.settimeout(3)
payload=json.dumps({'protocol':'sixmic-analysis','version':1,'connectionEpoch':str(epoch),'token':opened['binaryToken'],'maxPayloadBytes':1048576},separators=(',',':')).encode()
header=bytearray(64);struct.pack_into('<4sHHHHIIIQ',header,0,b'SMA1',1,64,1,1,len(payload),0,0,epoch);struct.pack_into('<I',header,56,zlib.crc32(payload));b.sendall(header+payload)
def recv(n):
 data=bytearray()
 while len(data)<n:
  chunk=b.recv(n-len(data));assert chunk,'binary disconnected';data.extend(chunk)
 return bytes(data)
expected={s['streamId']:s.get('schemaSha256') for s in sub['streams']};rows=[];kinds=set();start=time.monotonic()
for _ in range(2000):
 p=recv(64);n,stream,sequence=struct.unpack_from('<III',p,12);typ,flags=struct.unpack_from('<HH',p,8);data=recv(n)
 row={'type':typ,'flags':flags,'stream':stream,'sequence':sequence,'bytes':n,'epoch':struct.unpack_from('<Q',p,24)[0],'headerFrame':struct.unpack_from('<I',p,48)[0],'headerConfig':struct.unpack_from('<I',p,52)[0],'crcOK':zlib.crc32(data)==struct.unpack_from('<I',p,56)[0]}
 if typ==3:
  schema=json.loads(data);row.update(schema=schema,schemaHashMatches=hashlib.sha256(data).hexdigest()==expected.get(stream))
 if typ==5:
  words=struct.unpack('<32I',data);row.update(wordVersion=words[0],wordFrame=words[2],wordConfig=words[3],sampleIndexLow=words[8],sensorValidity=words[21],temperatureRaw=words[17],pressurePa=words[19]);kinds.add(5)
 if typ==6:row.update(serviceHeader=list(struct.unpack_from('<16I',data)),resultWords=struct.unpack_from('<I',data,40)[0]);kinds.add(6)
 if typ in [10,11]:row['error']=data.decode(errors='replace')
 if typ==6 and row.get('resultWords')==1025:
  v=struct.unpack_from('<1025f',data,64);row.update(powerValues=list(v),peakBin=max(range(len(v)),key=lambda i:v[i]),low5=sum(v[:5]),total=sum(v))
 rows.append(row)
 if time.monotonic()-start>8:break
result={'seconds':round(time.monotonic()-start,3),'subscription':sub,'packets':rows}
Path(__file__).with_name('SPECTRUM_PERIOD_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps([{'descriptor':p['serviceHeader'][11],'frame':p['serviceHeader'][6],'peakBin':p['peakBin'],'low5':p['low5'],'total':p['total']} for p in rows if 'powerValues' in p]),flush=True)
b.close();r.close();c.close()
