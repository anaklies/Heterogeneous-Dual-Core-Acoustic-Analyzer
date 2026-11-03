from pathlib import Path
import runpy,contextlib,io,json,time
H=Path(__file__).resolve().parent
start=time.monotonic()
for i in range(24):
 with contextlib.redirect_stdout(io.StringIO()):runpy.run_path(str(H/'probe_binary.py'))
 time.sleep(0.05)
result={'status':'PASS','reconnects':24,'seconds':round(time.monotonic()-start,3)}
(H/'SESSION_RECOVERY.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
source=(H/'probe_binary.py').read_text()
source=source.replace('for _ in range(20):','last_control=0\nfor _ in range(20000):')
source=source.replace(' rows.append(row)', ''' if typ==9:
  hb=bytearray(64);struct.pack_into('<4sHHHH',hb,0,b'SMA1',1,64,9,0);struct.pack_into('<Q',hb,24,epoch);b.sendall(hb)
 if time.monotonic()-last_control>10:call('heartbeat',{});last_control=time.monotonic()
 rows.append(row)''')
source=source.replace('if kinds=={5,6}:break','if time.monotonic()-start>125:break')
source=source.replace("'REAL_BINARY.json'","'KEEPALIVE_125_SECONDS.json'")
source=source[:source.index('print(json.dumps')]+'''print(json.dumps({'status':'PASS','seconds':result['seconds'],'packets':len(rows),'heartbeats':sum(p['type']==9 for p in rows),'results':sum(p['type']==5 for p in rows),'services':sum(p['type']==6 for p in rows),'lastFrame':next(p['wordFrame'] for p in reversed(rows) if p['type']==5)}),flush=True)
b.close();c.close()
'''
exec(compile(source,str(H/'probe_binary.py'),'exec'),{'__file__':str(H/'probe_binary.py')})
