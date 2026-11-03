#pragma once
#include <QtCore>
#include <cstring>
#include <cmath>

namespace sm {
struct LevelAverage {
    bool valid=false;
    double dbfs=-120,peak=0;
};
inline LevelAverage averageSixLevels(const QVector<float>& levels) {
    LevelAverage out;if(levels.size()!=48)return out;
    double power=0;
    for(int ch=0;ch<6;++ch){
        double rms=levels[ch*8],peak=levels[ch*8+1];
        if(!std::isfinite(rms)||!std::isfinite(peak)||rms<0||peak<0)return out;
        power+=rms*rms;out.peak+=peak/6.0;
    }
    out.valid=true;out.dbfs=10*std::log10(qMax(1.e-12,power/6.0));return out;
}
inline quint32 u32(const QByteArray &b,int at) { return qFromLittleEndian<quint32>(reinterpret_cast<const uchar*>(b.constData()+at)); }
inline quint16 u16(const QByteArray &b,int at) { return qFromLittleEndian<quint16>(reinterpret_cast<const uchar*>(b.constData()+at)); }
inline quint64 u64(const QByteArray &b,int at) { return qFromLittleEndian<quint64>(reinterpret_cast<const uchar*>(b.constData()+at)); }
inline float real(quint32 w) { float x; std::memcpy(&x,&w,4); return x; }
inline quint32 crc(const QByteArray &b) {
    // Same IEEE CRC32, one lookup per byte instead of eight bitwise rounds.
    static const QVector<quint32> table=[]{
        QVector<quint32> t(256);
        for(int i=0;i<256;++i){quint32 v=quint32(i);for(int n=0;n<8;++n)v=(v>>1)^((v&1)?0xedb88320u:0u);t[i]=v;}
        return t;
    }();
    quint32 v=0xffffffffu;
    for (char c:b) v=(v>>8)^table[int((v^quint8(c))&255u)];
    return v^0xffffffffu;
}
inline QByteArray frame(quint16 type,quint64 epoch,const QJsonObject &json) {
    QByteArray p=QJsonDocument(json).toJson(QJsonDocument::Compact);uchar h[64]={0};
    auto put16=[&](int at,quint16 v){qToLittleEndian(v,h+at);};
    auto put32=[&](int at,quint32 v){qToLittleEndian(v,h+at);};
    std::memcpy(h,"SMA1",4);put16(4,1);put16(6,64);put16(8,type);put16(10,1);put32(12,quint32(p.size()));
    qToLittleEndian(epoch,h+24);put32(56,crc(p));return QByteArray(reinterpret_cast<const char*>(h),64)+p;
}
struct Packet {quint16 type=0,flags=0;quint32 stream=0,sequence=0,frame=0,config=0;QByteArray payload;};
inline QByteArray heartbeat(quint64 epoch) {
    uchar h[64]={0};std::memcpy(h,"SMA1",4);
    qToLittleEndian<quint16>(1,h+4);qToLittleEndian<quint16>(64,h+6);
    qToLittleEndian<quint16>(9,h+8);qToLittleEndian(epoch,h+24);
    return QByteArray(reinterpret_cast<const char*>(h),64);
}
// -1 means malformed; 0 means incomplete. Caller closes a malformed connection.
inline int take(QByteArray &buffer,quint64 epoch,Packet &p,QString &error) {
    if(buffer.size()<64)return 0;
    quint32 n=u32(buffer,12);
    if(buffer.left(4)!="SMA1"||u16(buffer,4)!=1||u16(buffer,6)!=64||u32(buffer,60)!=0||n>1048576||u64(buffer,24)!=epoch){error="binary_header";return -1;}
    if(buffer.size()<64+int(n))return 0;
    p.type=u16(buffer,8);p.flags=u16(buffer,10);p.stream=u32(buffer,16);p.sequence=u32(buffer,20);p.frame=u32(buffer,48);p.config=u32(buffer,52);p.payload=buffer.mid(64,int(n));
    if((n&&!(p.flags&1))||((p.flags&1)&&crc(p.payload)!=u32(buffer,56))){error="binary_crc";return -1;}
    buffer.remove(0,64+int(n));return 1;
}
struct Measurements {
    QVector<quint32> words;
    qint64 received=-1;
    bool simulated=false;
    bool accept(const Packet &p,qint64 now) {
        if(p.payload.size()!=128)return false;
        QVector<quint32> v;for(int i=0;i<32;i++)v<<u32(p.payload,i*4);
        if(v[0]!=3||v[2]!=p.frame||v[3]!=p.config)return false;
        if(words.size()==32&&words[2]==v[2]&&words[3]==v[3]&&words[4]==v[4])return true;
        words=v;received=now;return true;
    }
    bool fresh(qint64 now) const {return received>=0&&now-received<1500;}
};
struct Environment {
    bool temperatureValid=false,humidityValid=false,pressureValid=false,speedValid=false,reference=false;
    double temperature=0,humidity=0,pressureHpa=0,speed=0;
    unsigned mode=0;
    static Environment decode(const QVector<quint32> &w,bool fresh){
        Environment e;if(w.size()!=32||!fresh)return e;
        quint32 valid=w[21],faults=(w[28]>>16)&255u;
        e.temperature=qint16(w[17]&65535u)/100.0;
        e.temperatureValid=(valid&1)&&!(faults&0x16u)&&e.temperature>=-20&&e.temperature<=60;
        // The paired SHT30 temperature/humidity frame shares CRC and age validity.
        e.humidity=100.0*double(w[18]&65535u)/65535.0;e.humidityValid=e.temperatureValid;
        e.pressureHpa=w[19]/100.0;e.pressureValid=(valid&2)&&!(faults&0x20u)&&w[19]>=30000&&w[19]<=120000;
        e.mode=(valid>>4)&3u;e.speed=sm::real(w[20]);e.reference=e.mode==0;
        bool supported=e.mode==0||(e.temperatureValid&&(e.mode<3||e.pressureValid));
        e.speedValid=(valid&8)&&supported&&std::isfinite(e.speed)&&e.speed>=300&&e.speed<=400;
        return e;
    }
};
}
