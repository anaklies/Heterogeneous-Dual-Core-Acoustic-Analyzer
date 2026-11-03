"""Small, bounds-checked FDT/newc helpers for the supplied vendor firmware."""
import struct
from dataclasses import dataclass, field

@dataclass
class Node:
    name:str
    properties:dict=field(default_factory=dict)
    children:list=field(default_factory=list)
    def child(self,name):
        return next((c for c in self.children if c.name==name),None)
    def walk(self):
        yield self
        for c in self.children:yield from c.walk()

def read_fdt(blob):
    if len(blob)<40:raise ValueError('Short FDT')
    h=struct.unpack_from('>10I',blob)
    if h[0]!=0xd00dfeed or h[1]>len(blob):raise ValueError('Invalid FDT header')
    cursor=h[2];strings=h[3];stack=[];root=None
    while cursor<h[2]+h[9]:
        token=struct.unpack_from('>I',blob,cursor)[0];cursor+=4
        if token==1:
            end=blob.index(0,cursor);n=Node(blob[cursor:end].decode())
            cursor=(end+4)&~3
            if stack:stack[-1].children.append(n)
            else:root=n
            stack.append(n)
        elif token==2:stack.pop()
        elif token==3:
            size,off=struct.unpack_from('>2I',blob,cursor);cursor+=8
            if cursor+size>h[1] or off>=h[8]:raise ValueError('Invalid FDT property')
            nameend=blob.index(0,strings+off)
            name=blob[strings+off:nameend].decode()
            stack[-1].properties[name]=blob[cursor:cursor+size];cursor=(cursor+size+3)&~3
        elif token==4:continue
        elif token==9:break
        else:raise ValueError('Unknown FDT token')
    reserves=bytearray();cursor=h[4]
    while True:
        value=blob[cursor:cursor+16]
        if len(value)!=16:raise ValueError('Invalid FDT reserve map')
        reserves+=value;cursor+=16
        if value==bytes(16):break
    return root,bytes(reserves),h[7]

def write_fdt(root,reserves=bytes(16),bootcpu=0):
    names={};strings=bytearray();body=bytearray()
    def word(n):body.extend(struct.pack('>I',n))
    def padded(data):body.extend(data);body.extend(bytes((-len(data))%4))
    def emit(n):
        word(1);padded(n.name.encode()+b'\0')
        for name,value in n.properties.items():
            if name not in names:names[name]=len(strings);strings.extend(name.encode()+b'\0')
            word(3);word(len(value));word(names[name]);padded(value)
        for c in n.children:emit(c)
        word(2)
    emit(root);word(9)
    offset=40+len(reserves);soffset=offset+len(body);total=soffset+len(strings)
    return struct.pack('>10I',0xd00dfeed,total,offset,soffset,40,17,16,bootcpu,len(strings),len(body))+reserves+body+strings

def read_cpio(blob):
    entries={};cursor=0
    while cursor<len(blob):
        if blob[cursor:cursor+6] not in [b'070701',b'070702']:raise ValueError('Invalid newc magic')
        fields=[int(blob[cursor+6+i*8:cursor+14+i*8],16) for i in range(13)]
        begin=cursor+110;namesize=fields[11]
        name=blob[begin:begin+namesize-1].decode()
        begin=(begin+namesize+3)&~3
        if name=='TRAILER!!!':break
        if name.startswith('/') or '..' in name.split('/'):raise ValueError('Unsafe newc path')
        data=blob[begin:begin+fields[6]]
        if len(data)!=fields[6]:raise ValueError('Truncated newc data')
        entries[name]={'fields':fields,'data':data}
        cursor=(begin+fields[6]+3)&~3
    return entries

def write_cpio(entries):
    output=bytearray()
    next_inode=max((item['fields'][0] for item in entries.values()),default=0)+1
    for inode,(name,item) in enumerate([*entries.items(),('TRAILER!!!',{'fields':[0]*13,'data':b''})],1):
        encoded=name.encode()+b'\0';data=item['data'];fields=item['fields'][:]
        if item.get('added',False):fields[0]=next_inode;next_inode+=1
        fields[6]=len(data);fields[11]=len(encoded);fields[12]=0
        output.extend(b'070701'+''.join(f'{v:08x}' for v in fields).encode())
        output.extend(encoded);output.extend(bytes((-len(output))%4));output.extend(data)
        output.extend(bytes((-len(output))%4))
    output.extend(bytes((-len(output))%512))
    return bytes(output)

def needed_libraries(blob):
    if blob[:5]!=b'\x7fELF\x01' or blob[5]!=1:return []
    off=struct.unpack_from('<I',blob,28)[0]
    size,count=struct.unpack_from('<HH',blob,42)
    programs=[struct.unpack_from('<8I',blob,off+i*size) for i in range(count)]
    dynamic=next((p for p in programs if p[0]==2),None)
    if dynamic is None:return []
    values=[struct.unpack_from('<2I',blob,dynamic[1]+i) for i in range(0,dynamic[4],8)]
    address=next((value for tag,value in values if tag==5),None)
    if address is None:return []
    segment=next(p for p in programs if p[0]==1 and p[2]<=address<p[2]+p[4])
    strings=segment[1]+address-segment[2]
    return [blob[strings+v:blob.index(0,strings+v)].decode() for tag,v in values if tag==1]
