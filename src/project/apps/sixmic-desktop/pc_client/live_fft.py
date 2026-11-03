"""Opt-in live PL frame transport. No FFT, filtering or acoustic DSP on PC.

Uses existing 48120/48121 with a separate read-only subscriber. Older backends
and the frozen v1 protocol continue to work without this optional extension.
"""
from __future__ import annotations
import hashlib,json,math,socket,struct,threading,time,zlib

LIVE_WORDS=16+3075+48+12288

def decode_live_frame(payload,frame,config,channel):
    if len(payload)!=LIVE_WORDS*4:raise ValueError('live FFT payload length')
    h=struct.unpack_from('<16I',payload)
    if h[0]!=0x3154464c or h[1]!=1 or h[2]!=frame or h[3]!=config or h[5]!=channel or h[7:8]!=(2048,) or h[10:14]!=(1025,3075,48,12288) or h[15]:raise ValueError('live FFT metadata mismatch')
    fs=struct.unpack('<f',struct.pack('<I',h[6]))[0]
    if not math.isfinite(fs) or not 8000<=fs<=192000:raise ValueError('live FFT sample rate')
    values=struct.unpack_from('<3123f',payload,64)
    if not all(math.isfinite(v) for v in values):raise ValueError('live FFT nonfinite data')
    pcm=struct.unpack_from('<12288i',payload,64+3123*4)
    if any(v< -8388608 or v>8388607 for v in pcm):raise ValueError('live PCM sign extension')
    return {'frame':frame,'config':config,'session':h[4],'channel':channel,'sampleRateHz':fs,
            'firstSampleIndex':str(h[8]|h[9]<<32),'lastSampleIndex':str((h[8]|h[9]<<32)+2047),
            'gap':bool(h[14]),'sourceKind':'pl-live','receivedNs':time.monotonic_ns()},payload[64:]

class LiveFFTWorker(threading.Thread):
    """Read-only live frame subscriber.

    Frames can be delivered one-by-one through on_frame, or - for display
    consumers - published into a single-slot mailbox and pulled with
    take_latest().  The mailbox keeps only the newest frame so a busy GUI
    thread can never build an ever-growing live delay; dropped counts the
    frames that were superseded before the UI asked for them.
    """
    def __init__(self,host,port,channel,on_frame=None,on_state=None,on_frame_ready=None):
        super().__init__(daemon=True,name='echo-live-fft');self.host=host;self.port=int(port);self.channel=int(channel)
        self.on_frame=on_frame;self.on_state=on_state or (lambda state:None);self.on_frame_ready=on_frame_ready
        self.stop_event=threading.Event();self.sockets=[];self.frames=0;self.dropped=0
        self._latest_lock=threading.Lock();self._latest=None;self._delivery_pending=False
    def take_latest(self):
        """GUI-thread pull of the newest decoded frame; None when nothing waits."""
        with self._latest_lock:
            item=self._latest;self._latest=None;self._delivery_pending=False
            return item
    def _publish(self,meta,body):
        with self._latest_lock:
            self._latest=(meta,body)
            if self._delivery_pending:
                self.dropped+=1
                notify=False
            else:
                self._delivery_pending=True
                notify=True
        if notify and self.on_frame_ready is not None:
            self.on_frame_ready()
    def stop(self):
        self.stop_event.set()
        for s in self.sockets:
            try:s.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    def run(self):
        reader=None
        try:
            c=socket.create_connection((self.host,self.port),3);self.sockets.append(c);c.settimeout(3);reader=c.makefile('rb');seq=0;session=None
            def call(op,args):
                nonlocal seq,session
                seq+=1;request={'protocol':'sixmic-analysis','version':1,'requestId':str(seq),'op':op,'args':args}
                if session:request['sessionId']=session
                c.sendall(json.dumps(request,separators=(',',':')).encode()+b'\n')
                while True:
                    line=reader.readline(65537)
                    if not line or len(line)>65536:raise ValueError('live control closed/oversize')
                    v=json.loads(line)
                    if v.get('requestId')!=str(seq):continue
                    if v.get('status')!='ok':raise ValueError(str(v.get('error')))
                    return v['result']
            h=call('hello',{'clientName':'ECHO-LiveView','clientVersion':'1','maxBinaryPayloadBytes':1048576});session=h['sessionId'];epoch=int(h['connectionEpoch'])
            api=h.get('capabilities',{}).get('gateway',{}).get('featureApi',{})
            if api.get('liveFftProtocol')!='echo-live-fft-1':raise ValueError('设备尚未提供高速实时帧通路，需要更新匹配的PS包')
            sub=call('subscribe',{'streams':[{'type':f'liveFft{self.channel}'}],'deliverSchema':True});opened=call('stream.open',{'subscriptionId':sub['subscriptionId']})
            b=socket.create_connection((self.host,int(opened['port'])),3);self.sockets.append(b);b.settimeout(.5)
            def send(typ,data=b''):
                header=bytearray(64);struct.pack_into('<4sHHHHIIIQ',header,0,b'SMA1',1,64,typ,1 if data else 0,len(data),0,0,epoch)
                if data:struct.pack_into('<I',header,56,zlib.crc32(data))
                b.sendall(header+data)
            send(1,json.dumps({'protocol':'sixmic-analysis','version':1,'connectionEpoch':str(epoch),'token':opened['binaryToken'],'maxPayloadBytes':1048576},separators=(',',':')).encode())
            def read(n):
                chunks=bytearray();deadline=time.monotonic()+5
                while len(chunks)<n and not self.stop_event.is_set():
                    try:v=b.recv(n-len(chunks))
                    except socket.timeout:
                        if time.monotonic()>deadline:raise TimeoutError('实时帧停止更新')
                        continue
                    if not v:raise EOFError('实时数据连接已关闭')
                    chunks.extend(v)
                if len(chunks)!=n:raise EOFError('实时检测已停止')
                return bytes(chunks)
            expected={v['streamId']:v['schemaSha256'] for v in sub['streams']};schemas=set();last_control=time.monotonic();announced=False
            while not self.stop_event.is_set():
                hd=read(64)
                if hd[:4]!=b'SMA1' or struct.unpack_from('<HH',hd,4)!=(1,64) or struct.unpack_from('<Q',hd,24)[0]!=epoch or struct.unpack_from('<I',hd,60)[0]:raise ValueError('SMA1 header invalid')
                typ,flags=struct.unpack_from('<HH',hd,8);n,stream,sequence=struct.unpack_from('<III',hd,12)
                if n>1048576:raise ValueError('live packet oversized')
                data=read(n) if n else b''
                if n and (not flags&1 or zlib.crc32(data)!=struct.unpack_from('<I',hd,56)[0]):raise ValueError('live packet CRC invalid')
                if typ==3:
                    sc=json.loads(data)
                    if hashlib.sha256(data).hexdigest()!=expected.get(stream) or sc.get('sourceKind')!='pl-live' or sc.get('simulated') or sc.get('extension')!='echo-live-fft-1':raise ValueError('live schema/source invalid')
                    schemas.add(stream)
                elif typ==9:send(9)
                elif typ==0x20:
                    if stream not in schemas:raise ValueError('live data before schema')
                    frame,config=struct.unpack_from('<II',hd,48);meta,body=decode_live_frame(data,frame,config,self.channel);meta.update(streamId=stream,sequence=sequence,connectionEpoch=str(epoch))
                    self.frames+=1
                    if not announced:self.on_state({'connected':True,'source':'pl-live'});announced=True
                    if self.on_frame_ready is not None:self._publish(meta,body)
                    elif self.on_frame is not None:self.on_frame(meta,body)
                elif typ in (10,11):raise ValueError(data.decode(errors='replace'))
                if time.monotonic()-last_control>10:call('heartbeat',{});last_control=time.monotonic()
        except Exception as exc:
            if not self.stop_event.is_set():self.on_state({'connected':False,'reason':str(exc)[:240]})
        finally:
            if reader:
                try:reader.close()
                except OSError:pass
            for s in self.sockets:
                try:s.close()
                except OSError:pass
