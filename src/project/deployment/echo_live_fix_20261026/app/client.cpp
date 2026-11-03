#include "client.h"
#include <algorithm>
#include <vector>

Client::~Client(){
    changed={};poll.stop();reconnect.stop();deadline.stop();
    QObject::disconnect(&control,nullptr,this,nullptr);QObject::disconnect(&binary,nullptr,this,nullptr);
    control.abort();binary.abort();
}

Client::Client(QObject *parent):QObject(parent) {
    clock.start();control.setReadBufferSize(131072);binary.setReadBufferSize(2097280);
    QObject::connect(&control,&QTcpSocket::connected,this,[this]{request("hello",{{"clientName","echo-ps-panel"},{"clientVersion","1.0.0"},{"maxBinaryPayloadBytes",1048576}});});
    QObject::connect(&control,&QTcpSocket::readyRead,this,[this]{consumeControl();});
    QObject::connect(&binary,&QTcpSocket::readyRead,this,[this]{consumeBinary();});
    QObject::connect(&control,&QTcpSocket::disconnected,this,[this]{
        connected=false;pending=false;monitorIntent=-1;token.clear();session.clear();requests.clear();requestArgs.clear();binary.abort();schemas.clear();sequences.clear();expectedHashes.clear();
        channelLevels.clear();levelsReceived=-1;levelsJob.clear();levelsPending=false;bandsJob.clear();bandsPending=false;spectrumJob.clear();spectrumPending=false;featureRead=false;noiseLearning=false;noiseReference.clear();noiseSamples=0;
        controlBuffer.clear();binaryBuffer.clear();subscription.clear();serviceCommits.clear();measured=sm::Measurements();spectrum.clear();bands.clear();config={};
        message=trText("设备服务未连接","Device service disconnected");notify();reconnect.start(2000);
    });
    QObject::connect(&binary,&QTcpSocket::disconnected,this,[this]{schemas.clear();spectrumReceived=-1;bandsReceived=-1;measured.received=-1;notify();});
    QObject::connect(&binary,&QTcpSocket::connected,this,[this]{binary.write(sm::frame(1,epoch.toULongLong(),{{"protocol","sixmic-analysis"},{"version",1},{"connectionEpoch",epoch},{"token",binaryToken},{"maxPayloadBytes",1048576}}));});
    reconnect.setSingleShot(true);QObject::connect(&reconnect,&QTimer::timeout,this,[this]{connectDevice();});
    QObject::connect(&poll,&QTimer::timeout,this,[this]{
        if(!connected)return;
        if(requests.size()>20){message=trText("设备服务响应超时","Device service timeout");control.abort();return;}
        request("status.get");
        if(currentPage==2&&pollCount%2==0){
            if(!bandsJob.isEmpty())request("feature.get",{{"jobId",bandsJob}});
            else if(!bandsPending){bandsPending=true;if(request("feature.start",{{"featureId","third_octave"},{"params",QJsonObject()}}))bandsStarted++;else bandsPending=false;}
        }else if(currentPage!=2&&!bandsJob.isEmpty()){
            request("feature.stop",{{"jobId",bandsJob}});bandsJob.clear();bandsPending=false;
        }
        if(binary.state()==QAbstractSocket::ConnectedState&&pollCount%25==0)
            binary.write(sm::heartbeat(epoch.toULongLong()));
        if(featureRead&&!capability("_liveFft")){
            if(!levelsJob.isEmpty())request("feature.get",{{"jobId",levelsJob}});
            else if(!levelsPending&&pollCount%2==0){levelsPending=true;QJsonObject p;if(capability("_p0TransientFrames"))p["framePolicy"]="latest";request("feature.start",{{"featureId","levels_core"},{"params",p}});}
            if(capability("_p0TransientFrames")&&spectrumService=="snapshot"){
                if(!spectrumJob.isEmpty())request("feature.get",{{"jobId",spectrumJob}});
                else if(!spectrumPending){spectrumPending=true;request("feature.start",{{"featureId","fft"},{"params",QJsonObject{{"component","power"},{"framePolicy","latest"}}}});}
            }
        }
        if(pollCount%25==0)request("capabilities.get");
        if(++pollCount%25==0){request("heartbeat");if(!token.isEmpty())request("control.renew",{{"controlToken",token}});if(!subscription.isEmpty()&&binary.state()==QAbstractSocket::UnconnectedState)request("stream.open",{{"subscriptionId",subscription}});}
        if(currentPage==3&&pollCount%2==0)refreshEvents();
        notify();
    });poll.start(200);
    deadline.setSingleShot(true);QObject::connect(&deadline,&QTimer::timeout,this,[this]{if(pending){pending=false;message=trText("尚未确认生效，请检查设备状态","Apply not confirmed; check device status");notify();}});
}
void Client::connectDevice(){
    if(control.state()!=QAbstractSocket::UnconnectedState)return;
    message=trText("正在连接设备服务","Connecting to device service");control.connectToHost(host,port);notify();
    reconnect.start(3000);
}
quint64 Client::request(const QString &op,QJsonObject args){
    if(control.state()!=QAbstractSocket::ConnectedState)return 0;
    QString id=QString("ps-%1").arg(++requestId);
    QJsonObject obj{{"protocol","sixmic-analysis"},{"version",1},{"requestId",id},{"op",op},{"args",args}};
    if(op!="hello")obj.insert("sessionId",session);
    requests.insert(id,op);requestArgs.insert(id,args);control.write(QJsonDocument(obj).toJson(QJsonDocument::Compact)+'\n');return requestId;
}
void Client::consumeControl(){
    controlBuffer+=control.readAll();if(controlBuffer.size()>131072){control.abort();return;}
    int end;while((end=controlBuffer.indexOf('\n'))>=0){
        QByteArray line=controlBuffer.left(end);controlBuffer.remove(0,end+1);
        if(line.isEmpty())continue;
        if(line.size()>65535||line.contains('\r')){control.abort();return;}
        QJsonParseError e;auto d=QJsonDocument::fromJson(line,&e);
        if(e.error!=QJsonParseError::NoError||!d.isObject()){control.abort();return;}reply(d.object());
    }
    if(controlBuffer.size()>65535)control.abort();
}
void Client::reply(const QJsonObject &obj){
    if(obj.value("version").toInt()!=1||obj.value("protocol").toString()!="sixmic-analysis"){control.abort();return;}
    QString type=obj.value("type").toString();
    if(type=="event"){
        QString event=obj.value("event").toString();auto data=obj.value("data").toObject();
        if(event=="configApplied"){pending=false;deadline.stop();request("config.read");request("status.get");message=data.value("applied").toBool()?trText("设置已生效","Settings applied"):trText("设置未生效","Settings rejected");}
        if(event=="controlLost"){token.clear();pending=false;}
        if(event=="controlChanged"&&!data.value("held").toBool()){token.clear();pending=false;}
        notify();return;
    }
    const auto args=requestArgs.take(obj.value("requestId").toString());
    QString op=requests.take(obj.value("requestId").toString());if(op.isEmpty())return;
    if(obj.value("status").toString()=="error"){
        if(op=="control.claim")monitorIntent=-1;
        if(op=="feature.start"){
            const QString f=args.value("featureId").toString();
            if(f=="levels_core")levelsPending=false;
            if(f=="fft")spectrumPending=false;
            if(f=="third_octave")bandsPending=false;
        }
        if(op=="feature.get"||op=="feature.result"){
            const QString j=args.value("jobId").toString();
            if(j==levelsJob)levelsJob.clear();
            if(j==spectrumJob)spectrumJob.clear();
            if(j==bandsJob)bandsJob.clear();
        }
        auto code=obj.value("error").toObject().value("code").toString();
        if(code=="busy")message=trText("设备正在调度，将稍后重试","Device scheduling; retrying shortly");
        else if(code=="control_conflict")message=trText("电脑正在控制设备","The PC currently controls the device");
        else if(code=="not_ready"||code=="unsupported_feature")message=trText("此功能尚未接通","This function is not connected yet");
        else message=trText("操作未完成","Operation not completed")+" · "+code;
        if(op=="control.renew"||code=="bad_token")token.clear();
        if(op=="config.commit"){pending=false;deadline.stop();}
        notify();return;
    }
    auto r=obj.value("result").toObject();
    if(op=="hello"){
        bool ok=false;epoch=r.value("connectionEpoch").toString();epoch.toULongLong(&ok);
        if(!ok||r.value("protocolVersion").toInt()!=1){control.abort();return;}
        session=r.value("sessionId").toString();if(session.isEmpty()){control.abort();return;}
        hiddenEventThrough=QSettings().value("eventHidden/"+host+"/"+epoch,QString("0")).toString().toULongLong();
        auto capabilities=r.value("capabilities").toObject();caps=capabilities.value("device").toObject();
        featureRead=capabilities.value("gateway").toObject().value("featureApi").toObject().value("enabled").toBool();
        fixture=capabilities.value("gateway").toObject().value("mockFixture").toBool();
        caps["_serviceSnapshotEnabled"]=capabilities.value("gateway").toObject().value("serviceSnapshotEnabled").toBool();
        caps["_p0TransientFrames"]=capabilities.value("gateway").toObject().value("featureApi").toObject().value("p0TransientFrames").toBool();
        caps["_liveFft"]=capabilities.value("gateway").toObject().value("featureApi").toObject().value("liveFftProtocol").toString()=="echo-live-fft-1";
        measured.simulated=fixture;connected=true;message=trText("设备服务已连接","Device service connected");reconnect.stop();
        request("status.get");request("config.read");subscribeResults();
    }else if(op=="capabilities.get"){
        featureRead=r.value("gateway").toObject().value("featureApi").toObject().value("enabled").toBool();
        bool wasLive=capability("liveResults");caps=r.value("device").toObject();caps["_serviceSnapshotEnabled"]=r.value("gateway").toObject().value("serviceSnapshotEnabled").toBool();
        caps["_p0TransientFrames"]=r.value("gateway").toObject().value("featureApi").toObject().value("p0TransientFrames").toBool();
        caps["_liveFft"]=r.value("gateway").toObject().value("featureApi").toObject().value("liveFftProtocol").toString()=="echo-live-fft-1";
        if(!wasLive&&capability("liveResults")){cancelSubscriptions();subscribeResults();}
    }else if(op=="status.get"){
        if(r.value("connectionEpoch").toString()!=epoch){control.abort();return;}status=r;
        if(pending&&r.value("config").toObject().value("activeVersion")==config.value("awaitVersion")){
            pending=false;deadline.stop();request("config.read");message=trText("设置已生效","Settings applied");
        }
    }else if(op=="config.read"){
        config=r;
        auto active=r.value("active").toArray();
        if(active.size()==32 && (quint32(active[14].toDouble())&1u)){
            if(monitorSince<0){monitorSince=clock.elapsed();monitorFirstFrame=measured.words.size()==32?measured.words[2]:0;}
        }else monitorSince=-1;
        if(monitorIntent>=0&&!token.isEmpty()){
            bool enabled=monitorIntent!=0;monitorIntent=-1;setMonitor(enabled);
        }
    }
    else if(op=="control.claim"){token=r.value("controlToken").toString();message=trText("本机控制已开启","Local control enabled");request("config.read");}
    else if(op=="control.release"){token.clear();message=trText("已释放控制权","Control released");}
    else if(op=="subscribe"){
        subscription=r.value("subscriptionId").toString();
        for(auto v:r.value("streams").toArray()){auto a=v.toObject();expectedHashes.insert(quint32(a.value("streamId").toDouble()),a.value("schemaSha256").toString());}
        request("stream.open",{{"subscriptionId",subscription}});
    }else if(op=="stream.open"){
        binaryToken=r.value("binaryToken").toString();int binaryPort=r.value("port").toInt();
        if(binaryPort<=0||binaryPort>65535){control.abort();return;}
        binary.abort();binaryBuffer.clear();schemas.clear();sequences.clear();binary.connectToHost(host,quint16(binaryPort));
    }else if(op=="feature.start"){
        if(r.value("featureId").toString()=="third_octave"){
            bandsPending=false;bandsJob=r.value("jobId").toString();
            if(currentPage!=2&&!bandsJob.isEmpty()){request("feature.stop",{{"jobId",bandsJob}});bandsJob.clear();}
            return;
        }
        if(r.value("featureId").toString()=="fft"){
            spectrumPending=false;spectrumJob=r.value("jobId").toString();if(!spectrumJob.isEmpty())request("feature.get",{{"jobId",spectrumJob}});return;
        }
        if(r.value("featureId").toString()!="levels_core")return;
        levelsPending=false;levelsJob=r.value("jobId").toString();
        if(!levelsJob.isEmpty())request("feature.get",{{"jobId",levelsJob}});
    }else if(op=="feature.get"){
        if(!bandsJob.isEmpty()&&r.value("jobId").toString()==bandsJob){
            const QString state=r.value("state").toString();
            if(state=="completed"||state=="failed"||state=="canceled"){if(state=="completed")bandsCompleted++;bandsJob.clear();}
            return;
        }
        if(!spectrumJob.isEmpty()&&r.value("jobId").toString()==spectrumJob){
            QString state=r.value("state").toString();
            if(state=="completed")request("feature.result",{{"jobId",spectrumJob},{"maxWords",4096}});
            else if(state=="failed"||state=="canceled")spectrumJob.clear();
            return;
        }
        if(r.value("jobId").toString()==levelsJob){
            QString state=r.value("state").toString();
            if(state=="completed")request("feature.result",{{"jobId",levelsJob},{"maxWords",48}});
            else if(state=="failed"||state=="canceled"){levelsJob.clear();channelLevels.clear();levelsReceived=-1;}
        }
    }else if(op=="feature.result"){
        if(!spectrumJob.isEmpty()&&r.value("jobId").toString()==spectrumJob&&r.value("featureId").toString()=="fft"){
            auto words=r.value("words").toArray();auto identity=r.value("configuration").toObject();QVector<float> values;
            bool valid=words.size()==1025&&!r.value("more").toBool()&&r.value("sourceKind").toString()==(fixture?"test-fixture":"pl-live")&&r.value("schema").toObject().value("units").toString()=="FS squared per bin";
            if(measured.words.size()==32)valid=valid&&quint32(identity.value("session").toDouble())==measured.words[4]&&quint32(identity.value("config").toDouble())==measured.words[3];
            for(auto w:words){float v=sm::real(quint32(w.toDouble()));if(!std::isfinite(v)||v<0)valid=false;values<<v;}
            if(valid&&spectrumService=="snapshot")acceptSpectrum(values,quint32(identity.value("sourceFrame").toString().toULongLong()),"FS squared per bin");
            spectrumJob.clear();return;
        }
        if(r.value("jobId").toString()==levelsJob&&r.value("featureId").toString()=="levels_core"){
            auto words=r.value("words").toArray();QString source=r.value("sourceKind").toString();
            bool valid=words.size()==48&&r.value("totalWords").toInt()==48&&!r.value("more").toBool()&&source==(fixture?"test-fixture":"pl-live");
            auto identity=r.value("configuration").toObject();
            if(measured.words.size()==32)valid=valid&&quint32(identity.value("session").toDouble())==measured.words[4]&&quint32(identity.value("config").toDouble())==measured.words[3];
            QVector<float> values;
            for(auto w:words){float v=sm::real(quint32(w.toDouble()));if(!std::isfinite(v))valid=false;values<<v;}
            if(valid){channelLevels=values;levelsReceived=clock.elapsed();}else{channelLevels.clear();levelsReceived=-1;}
            levelsJob.clear();
        }
    }else if(op=="event.list"){
        QJsonArray retained;
        for(auto e:r.value("events").toArray())if(e.toObject().value("eventId").toString().toULongLong()>hiddenEventThrough)retained.append(e);
        for(auto e:events)if(e.toObject().value("eventId").toString().toULongLong()>hiddenEventThrough&&!retained.contains(e))retained.append(e);
        std::vector<QJsonObject> sorted;for(auto e:retained)sorted.push_back(e.toObject());
        std::sort(sorted.begin(),sorted.end(),[](const QJsonObject&a,const QJsonObject&b){return a.value("eventId").toString().toULongLong()<b.value("eventId").toString().toULongLong();});
        events={};for(size_t i=sorted.size()>15?sorted.size()-15:0;i<sorted.size();++i)events.append(sorted[i]);
        QString cursor=r.value("nextCursor").toString();
        if(!cursor.isEmpty())request("event.list",{{"limit",200},{"cursor",cursor}});
    }
    notify();
}
void Client::subscribeResults(){
    if(!connected||!subscription.isEmpty())return;
    QJsonArray streams;
    if(capability("liveResults")||fixture)streams.append(QJsonObject{{"type","resultWords"}});
    if(capability("_serviceSnapshotEnabled"))streams.append(QJsonObject{{"type","serviceSnapshot"}});
    if(capability("_liveFft"))streams.append(QJsonObject{{"type","liveFft0"}});
    if(!streams.isEmpty())request("subscribe",{{"streams",streams},{"deliverSchema",true}});
}
void Client::consumeBinary(){
    binaryBuffer+=binary.readAll();if(binaryBuffer.size()>2097280){binary.abort();return;}
    sm::Packet p;QString error;int rc;
    while((rc=sm::take(binaryBuffer,epoch.toULongLong(),p,error))>0){
        if(p.type==3){
            auto d=QJsonDocument::fromJson(p.payload).object();
            QString hash=QString::fromLatin1(QCryptographicHash::hash(p.payload,QCryptographicHash::Sha256).toHex());
            if(!expectedHashes.contains(p.stream)||hash!=expectedHashes.value(p.stream)||quint32(d.value("streamId").toDouble())!=p.stream||d.value("connectionEpoch").toString()!=epoch){binary.abort();return;}
            bool sim=d.value("simulated").toBool();QString source=d.value("sourceKind").toString();
            if((source!="pl-live"&&source!="test-fixture")||(sim&&!fixture)||(!fixture&&source!="pl-live")){binary.abort();return;}
            schemas.insert(p.stream,d);sequences.insert(p.stream,p.sequence);continue;
        }
        if(p.type==9||p.type==2)continue;
        if(p.type==10||p.type==11){binary.abort();return;}
        if(p.type==8){measured.received=-1;spectrumReceived=-1;bandsReceived=-1;message=trText("数据出现间断，保留最后图表","Data gap; last chart retained");continue;}
        if(p.type==0x20){
            if(!schemas.contains(p.stream)||schemas[p.stream].value("extension").toString()!="echo-live-fft-1"||p.payload.size()!=61708||sm::u32(p.payload,0)!=0x3154464c||sm::u32(p.payload,4)!=1||sm::u32(p.payload,8)!=p.frame||sm::u32(p.payload,12)!=p.config||sm::u32(p.payload,20)!=0||sm::u32(p.payload,40)!=1025||sm::u32(p.payload,44)!=3075||sm::u32(p.payload,48)!=48||sm::u32(p.payload,52)!=12288){binary.abort();return;}
            QVector<float> power,levels;bool valid=true;
            for(int i=0;i<1025;i++){float v=sm::real(sm::u32(p.payload,64+(3*i+2)*4));if(!std::isfinite(v)||v<0)valid=false;power<<v;}
            for(int i=0;i<48;i++){float v=sm::real(sm::u32(p.payload,64+3075*4+i*4));if(!std::isfinite(v))valid=false;levels<<v;}
            if(!valid){binary.abort();return;}
            qint64 now=clock.elapsed();if(liveRateEpoch<0)liveRateEpoch=now;
            ++liveRateFrames;if(now-liveRateEpoch>=1000){liveRate=1000.0*liveRateFrames/(now-liveRateEpoch);liveRateFrames=0;liveRateEpoch=now;}
            channelLevels=levels;levelsReceived=clock.elapsed();
            if(spectrumService=="snapshot")acceptSpectrum(power,p.frame,"FS squared per bin");
            notify();continue;
        }
        if(p.type!=5&&p.type!=6)continue;
        if(!schemas.contains(p.stream)){binary.abort();return;}
        if(sequences.contains(p.stream)&&p.sequence!=sequences.value(p.stream)+1){message=trText("状态更新有间隔","Update gap detected");}
        sequences[p.stream]=p.sequence;
        // GAP_BEFORE describes missed history. This complete snapshot is still
        // valid; a result-stream gap must not erase another stream's spectrum.
        if(p.flags&2)message=trText("状态更新有间隔","Update gap detected");
        if(p.type==5){
            if(measured.words.size()==32&&p.payload.size()==128&&(measured.words[3]!=sm::u32(p.payload,12)||measured.words[4]!=sm::u32(p.payload,16))){serviceCommits.clear();spectrum.clear();bands.clear();}
            if(schemas[p.stream].value("streamType").toString()!="resultWords32"||!measured.accept(p,clock.elapsed())){binary.abort();return;}
            static bool logged=false;if(!logged){qInfo("ECHO_RESULT_ACCEPT frame=%u config=%u",p.frame,p.config);logged=true;}
        }else{
            if(schemas[p.stream].value("streamType").toString()!="serviceSnapshot"||p.payload.size()<64)continue;
            quint32 count=sm::u32(p.payload,40),descriptor=sm::u32(p.payload,44);
            if(count>16384||p.payload.size()!=64+int(count)*4||sm::u32(p.payload,0)!=0x52534c54||sm::u32(p.payload,48)||sm::u32(p.payload,56)!=1)continue;
            if(measured.words.size()!=32||sm::u32(p.payload,8)!=measured.words[4]||sm::u32(p.payload,12)!=measured.words[3])continue;
            if(serviceCommits.contains(descriptor)&&serviceCommits.value(descriptor)==sm::u32(p.payload,4))continue;
            auto services=profile.value("p1_services").toObject();
            for(auto it=services.begin();it!=services.end();++it){auto s=it.value().toObject();quint32 base=quint32(s.value("descriptor").toDouble());
                // The scheduler publishes its table descriptor, not the source
                // program allocation. QJsonObject sorts keys; never infer order from it.
                const QStringList order={"snapshot","peak_hold","spectrum_ema","smoothing","octave","third_octave","shape","flux_delta","welch","frequency_drift","selected_pair_CSD"};
                auto cfg=profile.value("config32").toArray();int index=order.indexOf(it.key());
                bool original=descriptor>=base&&descriptor<base+64&&(descriptor-base)%16==0;
                bool scheduled=false;if(cfg.size()==32&&index>=0){auto tables=profile.value("managedP1Tables").toArray();if(tables.isEmpty())tables.append(cfg[6]);for(auto v:tables){quint32 table=quint32(v.toDouble())+quint32(index)*64;scheduled|=descriptor>=table&&descriptor<table+64&&(descriptor-table)%16==0;}}
                if(!original&&!scheduled)continue;
                if(quint32(s.value("output_words").toDouble())!=count||sm::u32(p.payload,16)!=quint32(profile.value("generation").toDouble()))continue;
                QVector<float> values;bool finite=true;for(quint32 i=0;i<count;i++){float x=sm::real(sm::u32(p.payload,64+int(i)*4));if(!std::isfinite(x)||x<0){finite=false;break;}values<<x;}
                if(!finite)continue;
                serviceCommits[descriptor]=sm::u32(p.payload,4);
                // Never alternate instantaneous, EMA and smoothed curves under
                // the same trace label as the P1 carousel advances.
                if(it.key()==spectrumService&&!(spectrumService=="snapshot"&&capability("_p0TransientFrames"))){acceptSpectrum(values,sm::u32(p.payload,24),s.value("metadata").toObject().value("units").toString());static int logged=0;if(logged<6){qInfo("ECHO_SPECTRUM_ACCEPT source=%s words=%u descriptor=%u frame=%u",qPrintable(it.key()),count,descriptor,spectrumFrame);++logged;}}
                if(it.key()=="third_octave"){bands=values;bandsReceived=clock.elapsed();}
            }
        }
    }
    if(rc<0){message=trText("数据校验失败","Data validation failed");binary.abort();}notify();
}
void Client::claim(){if(connected)request("control.claim",{{"leaseSeconds",30}});}
void Client::release(){if(!token.isEmpty())request("control.release",{{"controlToken",token}});}
void Client::cancelSubscriptions(){
    if(!subscription.isEmpty())request("unsubscribe",{{"subscriptionId",subscription}});
    subscription.clear();binary.abort();binaryBuffer.clear();schemas.clear();expectedHashes.clear();sequences.clear();
}
void Client::setPage(int page){
    currentPage=page;
    if(page==3)refreshEvents();
    // Read-only page navigation never starts jobs or arms monitoring.
}
void Client::refreshEvents(){if(connected&&!requests.values().contains("event.list"))request("event.list",{{"limit",200},{"cursor",QString::number(hiddenEventThrough)}});}
void Client::clearEventList(){
    for(auto e:events)hiddenEventThrough=qMax(hiddenEventThrough,e.toObject().value("eventId").toString().toULongLong());
    QSettings().setValue("eventHidden/"+host+"/"+epoch,QString::number(hiddenEventThrough));
    events={};message=trText("列表已清空，保存的录音保留","List cleared; saved audio kept");notify();
}
void Client::changeConfig(int index,quint32 value){
    if(token.isEmpty()||pending||!capability("configCommit"))return;
    if(!config.value("activeWordsKnown").toBool()||config.value("pending").toBool()){message=trText("当前设置未知，暂不能修改","Active configuration unknown");notify();return;}
    auto words=config.value("active").toArray();if(words.size()!=32)return;
    quint32 version=quint32(config.value("activeVersion").toDouble());if(version==0xffffffffu)return;
    words[index]=double(value);words[1]=double(version+1);config["awaitVersion"]=double(version+1);
    pending=true;deadline.start(12000);message=trText("正在应用设置","Applying settings");
    request("config.commit",{{"controlToken",token},{"version",double(version+1)},{"words",words}});notify();
}
void Client::setMonitor(bool enabled){
    if(!connected||pending||!capability("eventCapture"))return;
    if(token.isEmpty()){
        if(monitorIntent>=0)return;
        monitorIntent=enabled?1:0;
        message=trText("正在申请控制权","Requesting control");
        request("control.claim",{{"leaseSeconds",30}});notify();return;
    }
    auto words=config.value("active").toArray();if(words.size()!=32)return;
    // Enabling requires the recorder already provisioned by a validated profile.
    if(enabled&&!(quint32(words[8].toDouble())&8)){message=trText("请先配置事件录音缓冲区","Provision event recording buffers first");notify();return;}
    quint32 version=quint32(config.value("activeVersion").toDouble());if(version==0xffffffffu)return;
    words[14]=enabled?1:0;
    if(enabled){
        const quint32 defaults[6]={0x02000000u,0x00800200u,0x00040018u,0x000c00c0u,0x00000400u,0x08000004u};
        quint32 any=0;for(int k=16;k<22;++k)any|=quint32(words[k].toDouble());
        if(!any)for(int k=0;k<6;++k)words[16+k]=double(defaults[k]);
        quint32 controlWord=quint32(words[16].toDouble())|6u;
        if(!(controlWord&0xff00u)){const quint32 edges[9]={2,10,20,40,80,160,320,640,1025};controlWord|=0xff00u;for(int k=0;k<8;++k)words[22+k]=double(edges[k]|(edges[k+1]<<16));}
        words[16]=double(controlWord);
        quint32 ratios=quint32(words[17].toDouble());if((ratios>>16)>32u)words[17]=double((ratios&65535u)|(32u<<16));
    }
    words[1]=double(version+1);config["awaitVersion"]=double(version+1);
    pending=true;deadline.start(12000);message=enabled?trText("正在准备背景，请保持正常环境声","Preparing background; keep normal ambient sound"):trText("正在停止监测","Stopping monitoring");
    request("config.commit",{{"controlToken",token},{"version",double(version+1)},{"words",words}});notify();
}
void Client::setPeriodic(bool enabled){
    auto words=config.value("active").toArray();if(words.size()!=32)return;
    quint32 flags=quint32(words[8].toDouble());changeConfig(8,enabled?(flags|1u):(flags&~1u));
}

void Client::acceptSpectrum(const QVector<float>& values,quint32 frame,const QString& units){
    if(noiseLearning&&noiseFrame!=frame){
        noiseFrame=frame;
        if(noiseSamples==0||noiseReference.size()!=values.size())noiseReference=values;
        else for(int n=0;n<values.size();++n)noiseReference[n]=qMax(noiseReference[n],values[n]);
        if(++noiseSamples>=3){noiseLearning=false;message=trText("底噪参考已记录，仅用于显示淡化","Noise reference captured; display dimming only");}
    }
    spectrum=values;spectrumFrame=frame;spectrumReceived=clock.elapsed();spectrumUnit=units;
}
