#include "client.h"
#include <QtWidgets>
#include <QtNetwork/QNetworkInterface>
#include <algorithm>

class Chart:public QWidget {
    QVector<float> previous,shown;
    QElapsedTimer transition;
    QTimer animator;
public:
    QVector<float> data;
    QVector<float> noise;
    bool dimNoise=false;
    bool instant=true;
    int transitionMs=100;
    bool columns=false,hold=false;
    QString title,emptyText,unit="dB re FS²/bin";
    explicit Chart(QWidget *parent=nullptr):QWidget(parent){
        setMinimumHeight(230);animator.setInterval(66);
        QObject::connect(&animator,&QTimer::timeout,this,[this]{update();if(!transition.isValid()||transition.elapsed()>=transitionMs)animator.stop();});
    }
    void requestPaint(){if(!instant&&isVisible()){if(!animator.isActive())animator.start();}else update();}
    void setData(const QVector<float> &values){
        if(values==data)return;
        previous=shown.size()==values.size()?shown:values;
        data=values;transition.restart();
        if(data.isEmpty()){previous.clear();shown.clear();}
    }
    // Piecewise display axis: 0..-30:15%, -30..-60:30%,
    // -60..-90:40%, -90..-120:15%. Raw power is unchanged.
    static double dbPosition(double db){
        double d=qBound(0.0,-db,120.0);
        if(d<=30)return d/30*.15;
        if(d<=60)return .15+(d-30)/30*.30;
        if(d<=90)return .45+(d-60)/30*.40;
        return .85+(d-90)/30*.15;
    }
protected:
    void paintEvent(QPaintEvent*) override {
        QPainter p(this);p.setRenderHint(QPainter::Antialiasing);
        p.fillRect(rect(),QColor("#101d2c"));p.setPen(QColor("#e8eff7"));p.setFont(QFont(font().family(),16,QFont::DemiBold));
        p.drawText(QRect(20,12,width()-40,32),Qt::AlignVCenter,title);
        QRectF a(64,65,width()-90,height()-105);
        p.setFont(QFont(font().family(),12));
        for(int n=0;n<5;n++){double y=a.top()+dbPosition(-n*30)*a.height();p.setPen(QColor("#2d3c4d"));p.drawLine(QPointF(a.left(),y),QPointF(a.right(),y));p.setPen(QColor("#91a5bb"));p.drawText(QRectF(2,y-12,53,24),Qt::AlignRight,QString::number(-n*30));}
        if(data.isEmpty()){
            p.setPen(QColor("#c4d1df"));p.setFont(QFont(font().family(),16));p.drawText(a.adjusted(12,15,-12,-15),Qt::AlignCenter|Qt::TextWordWrap,emptyText);return;
        }
        p.save();p.setClipRect(a);QPainterPath path,foreground;bool abovePrevious=false;
        // Display transition only; data remains the unmodified PL result.
        double mix=!instant&&transition.isValid()?qMin(1.0,double(transition.elapsed())/qMax(1,transitionMs)):1.0;
        shown.resize(data.size());
        for(int i=0;i<data.size();i++){
            // Interpolate the displayed dB coordinate, not linear power. This avoids
            // a brief high-power bin dominating the whole visual transition.
            double oldDb=10*std::log10(qMax(1.e-12,double(previous.size()==data.size()?previous[i]:data[i])));
            double newDb=10*std::log10(qMax(1.e-12,double(data[i])));
            shown[i]=float(std::pow(10.0,(oldDb*(1-mix)+newDb*mix)/10.0));
            double db=shown[i]>0?10*std::log10(double(shown[i])):-120;
            double x=a.left()+(double(i)/qMax(1,data.size()-1))*a.width();
            double y=a.top()+dbPosition(db)*a.height();
            if(columns){double bw=a.width()/qMax(1,data.size());p.fillRect(QRectF(a.left()+i*bw,y,qMax(1.0,bw-4),a.bottom()-y),QColor("#56aee9"));}
            else{if(i==0)path.moveTo(x,y);else path.lineTo(x,y);}
            if(!columns&&dimNoise&&noise.size()==data.size()){
                bool above=data[i]>qMax(1.e-20f,noise[i])*4.f;
                if(above){if(abovePrevious)foreground.lineTo(x,y);else foreground.moveTo(x,y);}abovePrevious=above;
            }
        }
        p.setPen(QPen(QColor(dimNoise?"#52667a":"#6bc5ef"),dimNoise?1:2));p.drawPath(path);
        if(dimNoise){p.setPen(QPen(QColor("#6bc5ef"),2));p.drawPath(foreground);}p.restore();
        p.setPen(QColor("#aebed0"));p.setFont(QFont(font().family(),12));
        p.drawText(QRectF(a.left(),a.bottom()+7,130,26),Qt::AlignLeft,columns?"31.25 Hz":"0 Hz");
        p.drawText(QRectF(a.center().x()-70,a.bottom()+7,140,26),Qt::AlignCenter,columns?"707 Hz":"12 kHz");
        p.drawText(QRectF(a.right()-130,a.bottom()+7,130,26),Qt::AlignRight,columns?"16 kHz":"24 kHz");
    }
};

class Panel:public QWidget {
    Client &client;
    QStackedWidget *pages;
    QVector<QPushButton*> nav;
    QLabel *connection,*clockText,*toast,*source,*level,*peak,*cycles,*environment,*health,*eventsState,*diagnostic;
    Chart *homeChart,*spectrumChart,*bandChart;
    QPushButton *holdButton,*monitorButton,*periodicButton,*ownerButton,*clearEventsButton;
    QListWidget *eventList;
    QJsonArray shownEvents;
    QCheckBox *language;
    QComboBox *spectrumMode;
    QPushButton *learnNoise;
    QCheckBox *dimNoise;
    QCheckBox *softPlot;
    bool frozen=false,preview=false;
    int selected=0;
    quint32 oldFrame=0;
    qint64 lastFrameMs=-1;
    double hz=0;
    qint64 lastHeartbeat=-1000;
    QVector<float> frozenSpectrum,frozenBands;
    QLabel *label(QVBoxLayout *box,const QString &text,int size=20,const char *object=nullptr){
        auto w=new QLabel(text);w->setWordWrap(true);w->setFont(QFont(font().family(),size,size>=26?QFont::DemiBold:QFont::Normal));if(object)w->setObjectName(object);box->addWidget(w);return w;
    }
    QPushButton *button(const QString &text){auto w=new QPushButton(text);w->setMinimumHeight(58);w->setCursor(Qt::PointingHandCursor);return w;}
    QWidget *page(const QString &name,QVBoxLayout *&layout){
        auto w=new QWidget;layout=new QVBoxLayout(w);layout->setContentsMargins(18,14,18,10);layout->setSpacing(12);
        auto title=new QLabel(name);title->setObjectName("pageTitle");layout->addWidget(title);pages->addWidget(w);return w;
    }
public:
    explicit Panel(Client &c,bool isPreview=false):client(c),preview(isPreview){
        setWindowTitle("echo 便携声学分析仪");resize(1024,600);setMinimumSize(1024,600);
        auto outer=new QVBoxLayout(this);outer->setContentsMargins(0,0,0,0);outer->setSpacing(0);
        auto top=new QWidget;top->setObjectName("top");top->setFixedHeight(58);auto topRow=new QHBoxLayout(top);topRow->setContentsMargins(18,4,18,4);
        auto brand=new QLabel("echo");brand->setObjectName("brand");topRow->addWidget(brand);topRow->addStretch();connection=new QLabel;topRow->addWidget(connection);clockText=new QLabel;topRow->addSpacing(28);topRow->addWidget(clockText);outer->addWidget(top);
        auto center=new QHBoxLayout;center->setSpacing(0);auto rail=new QWidget;rail->setObjectName("rail");rail->setFixedWidth(148);auto menu=new QVBoxLayout(rail);menu->setContentsMargins(10,16,10,12);menu->setSpacing(12);
        QStringList names={"总览","频谱","频带","异常监测","设备","设置"};
        for(int i=0;i<names.size();i++){auto b=button(names[i]);b->setCheckable(true);nav<<b;menu->addWidget(b);QObject::connect(b,&QPushButton::clicked,this,[this,i]{select(i);});}menu->addStretch();
        source=new QLabel;source->setWordWrap(true);source->setObjectName("source");menu->addWidget(source);center->addWidget(rail);pages=new QStackedWidget;center->addWidget(pages,1);outer->addLayout(center,1);
        toast=new QLabel;toast->setFixedHeight(42);toast->setObjectName("toast");toast->setContentsMargins(18,0,18,0);outer->addWidget(toast);
        QVBoxLayout *box;
        page("实时测量",box);auto metrics=new QHBoxLayout;
        auto metric=[&](const QString &caption,QLabel *&value){auto col=new QVBoxLayout;auto cap=new QLabel(caption);cap->setObjectName("metricCaption");col->addWidget(cap);value=new QLabel("—");value->setObjectName("metricValue");col->addWidget(value);metrics->addLayout(col);};
        metric("六通道 RMS · dBFS",level);metric("平均峰值 · FS",peak);metric("接收更新 · Hz",cycles);box->addLayout(metrics);
        homeChart=new Chart;box->addWidget(homeChart,1);environment=label(box,"",17);environment->setTextFormat(Qt::RichText);
        page("频谱",box);spectrumChart=new Chart;box->addWidget(spectrumChart,1);auto tools=new QHBoxLayout;holdButton=button("冻结显示");tools->addWidget(holdButton);auto latest=button("恢复实时");tools->addWidget(latest);box->addLayout(tools);
        spectrumMode=new QComboBox;spectrumMode->setMinimumHeight(48);spectrumMode->addItem("瞬时频谱","snapshot");spectrumMode->addItem("时间平均","spectrum_ema");spectrumMode->addItem("频率平滑","smoothing");spectrumMode->setCurrentIndex(1);tools->addWidget(spectrumMode);
        QObject::connect(spectrumMode,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){client.spectrumService=spectrumMode->currentData().toString();client.spectrum.clear();client.spectrumReceived=-1;frozen=false;QSettings().setValue("spectrumService",client.spectrumService);refresh();});
        if(QSettings().value("liveSpectrumRevision",0).toInt()<3){QSettings().setValue("spectrumService","snapshot");QSettings().setValue("liveSpectrumRevision",3);}
        int savedMode=spectrumMode->findData(QSettings().value("spectrumService","snapshot"));if(savedMode>=0){QSignalBlocker guard(spectrumMode);spectrumMode->setCurrentIndex(savedMode);client.spectrumService=spectrumMode->currentData().toString();}
        auto noiseTools=new QHBoxLayout;learnNoise=button("记录底噪");dimNoise=new QCheckBox("底噪淡化（仅显示）");dimNoise->setMinimumHeight(46);noiseTools->addWidget(learnNoise);noiseTools->addWidget(dimNoise);box->addLayout(noiseTools);
        softPlot=new QCheckBox("柔和绘图");softPlot->setChecked(QSettings().value("softLivePlot",true).toBool());softPlot->setToolTip("约100毫秒绘图过渡，不改变采集、测量或保存数据");noiseTools->addWidget(softPlot);QObject::connect(softPlot,&QCheckBox::toggled,this,[this](bool on){QSettings().setValue("softLivePlot",on);refresh();});
        QObject::connect(learnNoise,&QPushButton::clicked,this,[this]{if(!client.connected)return;client.noiseReference.clear();client.noiseSamples=0;client.noiseFrame=0;client.noiseLearning=true;dimNoise->setChecked(false);client.message=client.trText("请保持安静，采集3次同类PL谱更新","Keep quiet for 3 updates of the selected PL spectrum");refresh();});
        QObject::connect(spectrumMode,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){client.noiseLearning=false;client.noiseSamples=0;client.noiseReference.clear();dimNoise->setChecked(false);});
        QObject::connect(holdButton,&QPushButton::clicked,this,[this]{frozen=!frozen;if(frozen){frozenSpectrum=client.spectrum;frozenBands=client.bands;}refresh();});
        QObject::connect(latest,&QPushButton::clicked,this,[this]{frozen=false;refresh();});
        page("三分之一倍频程",box);bandChart=new Chart;bandChart->columns=true;box->addWidget(bandChart,1);label(box,"相对频带能量，不作为绝对声压级。",17);
        page("异常监测",box);eventsState=label(box,"",21);eventList=new QListWidget;eventList->setMinimumHeight(170);eventList->setWordWrap(true);box->addWidget(eventList,1);auto eventTools=new QHBoxLayout;monitorButton=button("开始监测");eventTools->addWidget(monitorButton);clearEventsButton=button("清除全部");eventTools->addWidget(clearEventsButton);box->addLayout(eventTools);
        QObject::connect(clearEventsButton,&QPushButton::clicked,this,[this]{
            if(QMessageBox::question(this,client.trText("清除事件列表","Clear event list"),client.trText("清除本机全部已显示事件？保存的录音和电脑记录会保留，新事件仍正常显示。","Clear all displayed events? Saved audio and PC records are kept; new events still appear."),QMessageBox::Yes|QMessageBox::No,QMessageBox::No)==QMessageBox::Yes)client.clearEventList();
        });
        QObject::connect(monitorButton,&QPushButton::clicked,this,[this]{auto a=client.config.value("active").toArray();if(a.size()==32)client.setMonitor((quint32(a[14].toDouble())&1u)==0);});
        QObject::connect(eventList,&QListWidget::itemClicked,this,[this](QListWidgetItem *item){
            auto e=item->data(Qt::UserRole).toJsonObject();quint32 reason=quint32(e.value("clipReason").toDouble());
            QString category=(reason&1)?client.trText("声音增强","Sound increase"):(reason&2)?client.trText("频带变化","Band change"):(reason&4)?client.trText("规律声中断","Sound interruption"):client.trText("声音变化","Sound change");
            QString text=category+"\n"+client.trText("记录编号：","Record ID: ")+e.value("eventId").toString()+"\n"+client.trText("录音已保存在SD卡；电脑可下载音频和数据。","Recording saved to SD; download audio and data on the PC.")+"\n"+client.trText("超过循环容量时会自动替换最早记录。","Oldest recordings are replaced at the storage limit.");
            QMessageBox::information(this,client.trText("事件详情","Event details"),text);
        });
        page("设备与连接",box);health=label(box,"",21);diagnostic=label(box,"",18);box->addStretch();auto controls=new QHBoxLayout;ownerButton=button("本机控制");periodicButton=button("暂停扩展分析");controls->addWidget(ownerButton);controls->addWidget(periodicButton);box->addLayout(controls);auto retry=button("重新连接");box->addWidget(retry);
        QObject::connect(retry,&QPushButton::clicked,this,[this]{client.control.abort();client.connectDevice();});
        QObject::connect(ownerButton,&QPushButton::clicked,this,[this]{if(client.token.isEmpty())client.claim();else client.release();});
        QObject::connect(periodicButton,&QPushButton::clicked,this,[this]{auto a=client.config.value("active").toArray();if(a.size()==32)client.setPeriodic(!(quint32(a[8].toDouble())&1));});
        page("设置",box);language=new QCheckBox("English / 中文");language->setMinimumHeight(64);box->addWidget(language);
        label(box,"本机显示冻结只暂停图表；持续采样不会停止。",19);label(box,"控制方式：本机或电脑单独持有控制权。",19);
        label(box,"制作人  刘珉志  孟德旭\n黑龙江大学",22);box->addStretch();auto release=button("释放设备控制权");box->addWidget(release);QObject::connect(release,&QPushButton::clicked,this,[this]{client.release();});
        QObject::connect(language,&QCheckBox::toggled,this,[this](bool v){client.english=v;QSettings().setValue("english",v);retranslate();refresh();});
        language->setChecked(QSettings().value("english",false).toBool());
        // Network snapshots may arrive much faster than the display refresh.
        // Paint at 5 Hz rather than rebuilding every label for each packet.
        // One display clock owns all widgets. Packet callbacks only update the
        // latest Client data, avoiding competing transitions and stale clears.
        client.changed=[]{};
        auto tick=new QTimer(this);QObject::connect(tick,&QTimer::timeout,this,[this]{refresh();});tick->start(200);
        select(0);refresh();
    }
    void select(int i){selected=i;pages->setCurrentIndex(i);for(int n=0;n<nav.size();n++)nav[n]->setChecked(n==i);client.setPage(i);refresh();}
    void retranslate(){
        const QVector<QPair<QString,QString>> text={
            {"恢复实时","Resume live"},{"相对频带能量，不作为绝对声压级。","Relative band energy; not calibrated SPL."},
            {"重新连接","Reconnect"},{"本机显示冻结只暂停图表；持续采样不会停止。","Freezing pauses the display; acquisition continues."},
            {"控制方式：本机或电脑单独持有控制权。","Only the panel or PC can hold device control at one time."},
            {"制作人  刘珉志  孟德旭\n黑龙江大学","Created by Liu Minzhi and Meng Dexu\nHeilongjiang University"},
            {"释放设备控制权","Release device control"}
        };
        for(auto pair:text){
            for(auto w:findChildren<QLabel*>())if(w->text()==pair.first||w->text()==pair.second)w->setText(client.english?pair.second:pair.first);
            for(auto w:findChildren<QPushButton*>())if(w->text()==pair.first||w->text()==pair.second)w->setText(client.english?pair.second:pair.first);
        }
        QStringList zh={"总览","频谱","频带","异常监测","设备","设置"},en={"Overview","Spectrum","Bands","Events","Device","Settings"};
        QStringList zhTitles={"实时测量","频谱","三分之一倍频程","异常监测","设备与连接","设置"},enTitles={"Live measurement","Spectrum","One-third octave","Event monitoring","Device and connection","Settings"};
        for(int i=0;i<nav.size();i++){nav[i]->setText(client.english?en[i]:zh[i]);pages->widget(i)->findChild<QLabel*>("pageTitle")->setText(client.english?enTitles[i]:zhTitles[i]);}
        auto caps=pages->widget(0)->findChildren<QLabel*>("metricCaption");QStringList a=client.english?QStringList{"6CH RMS · dBFS","Mean peak · FS","Receive update · Hz"}:QStringList{"六通道 RMS · dBFS","平均峰值 · FS","接收更新 · Hz"};for(int i=0;i<qMin(caps.size(),a.size());i++)caps[i]->setText(a[i]);
    }
    void refresh(){
        if(client.clock.elapsed()-lastHeartbeat>=1000){
            QString file=qEnvironmentVariable("ECHO_HEARTBEAT_FILE");
            if(!file.isEmpty()){QFile beat(file);if(beat.open(QIODevice::WriteOnly|QIODevice::Truncate))beat.write(QByteArray::number(client.clock.elapsed()));}
            lastHeartbeat=client.clock.elapsed();
        }
        bool fresh=client.measured.fresh(client.clock.elapsed());auto &w=client.measured.words;auto T=[&](const QString &a,const QString &b){return client.trText(a,b);};
        clockText->setText(QDateTime::currentDateTime().toString("HH:mm"));
        connection->setText(client.connected?T("设备已连接","Connected"):T("等待设备服务","Waiting for device"));
        source->setText(preview?T("已保存板上测试数据","Saved board test data"):client.fixture?T("测试夹具","Test fixture"):fresh?T("PL 实时数据","PL live data"):T("暂无实时数据","No live data"));
        toast->setText(client.message);level->setText("—");peak->setText("—");
        // Levels and the FFT are independently timestamped live data, not
        // invalidated when a separate metadata/status stream pauses.
        if(client.channelLevels.size()==48&&client.levelsReceived>=0&&client.clock.elapsed()-client.levelsReceived<2000){
            auto average=sm::averageSixLevels(client.channelLevels);
            if(average.valid){level->setText(QString::number(average.dbfs,'f',1));peak->setText(QString::number(average.peak,'f',3));}
        }
        if(fresh&&w.size()==32){
            if(w[2]!=oldFrame){qint64 now=client.clock.elapsed();if(lastFrameMs>=0&&now>lastFrameMs)hz=1000.0/(now-lastFrameMs);oldFrame=w[2];lastFrameMs=now;}
            cycles->setText(preview?"—":QString::number(hz,'f',1));
        }else cycles->setText("—");
        if(client.capability("_liveFft")&&client.liveRate>0&&client.levelsReceived>=0&&client.clock.elapsed()-client.levelsReceived<2000)cycles->setText(QString::number(client.liveRate,'f',1));
        sm::Environment env=sm::Environment::decode(w,fresh);
        QString temp=env.temperatureValid?QString::number(env.temperature,'f',1)+" °C":"—";
        QString humid=env.humidityValid?QString::number(env.humidity,'f',1)+" %RH":"—";
        QString pressure=env.pressureValid?QString::number(env.pressureHpa,'f',1)+" hPa":"—";
        QString speed=env.speedValid?QString::number(env.speed,'f',1)+" m/s":"—";
        QString speedTitle=env.speedValid&&env.reference?T("参考声速","Reference speed"):T("估计声速","Estimated speed");
        QString envHtml="<table width='100%'><tr>";
        for(auto item:{qMakePair(T("温度","Temperature"),temp),qMakePair(T("湿度","Humidity"),humid),qMakePair(T("气压","Pressure"),pressure),qMakePair(speedTitle,speed)})envHtml+="<td width='25%'><span style='font-size:19px;color:#bdcfdf'>"+item.first+"</span><br><b style='font-size:23px'>"+item.second+"</b></td>";
        environment->setText(envHtml+"</tr></table>");
        bool specFresh=client.spectrumReceived>=0&&client.clock.elapsed()-client.spectrumReceived<5000;
        bool bandFresh=client.bandsReceived>=0&&client.clock.elapsed()-client.bandsReceived<5000;
        QVector<float> spec=frozen?frozenSpectrum:client.spectrum;
        QVector<float> band=frozen?frozenBands:client.bands;
        QString modeTitle=client.spectrumService=="spectrum_ema"?T("时间平均频谱","Time-averaged spectrum"):client.spectrumService=="smoothing"?T("频率平滑谱","Frequency-smoothed spectrum"):T("瞬时频谱","Instantaneous spectrum");
        bool noiseReady=!client.noiseLearning&&client.noiseSamples>=3&&client.noiseReference.size()==client.spectrum.size();
        learnNoise->setText(client.noiseLearning?T("正在记录 ","Learning ")+QString::number(client.noiseSamples)+"/3":T("记录底噪","Learn background"));learnNoise->setEnabled(client.connected&&!client.noiseLearning);
        softPlot->setText(T("柔和绘图","Soft display"));dimNoise->setText(T("底噪淡化（仅显示）","Dim background (display only)"));dimNoise->setEnabled(noiseReady);
        for(auto chart:{homeChart,spectrumChart}){chart->noise=client.noiseReference;chart->dimNoise=noiseReady&&dimNoise->isChecked();chart->instant=client.spectrumService=="snapshot"&&!softPlot->isChecked();chart->transitionMs=client.spectrumService=="snapshot"?100:600;}
        for(auto chart:{homeChart,spectrumChart}){chart->setData(spec);chart->title=modeTitle+(frozen?T(" · 已冻结"," · frozen"):!specFresh?T(" · 等待更新"," · waiting"):T(" · 更新帧 "," · frame ")+QString::number(client.spectrumFrame));chart->emptyText=T("等待所选PL频谱\n下一次周期结果到达后显示","Waiting for selected PL spectrum\nShown on the next scheduled result");chart->requestPaint();}
        spectrumMode->setItemText(0,T("瞬时频谱","Instantaneous"));spectrumMode->setItemText(1,T("时间平均","Time average"));spectrumMode->setItemText(2,T("频率平滑","Frequency smoothing"));
        bandChart->setData(band);bandChart->title=T("三分之一倍频程 · 相对能量","One-third octave · relative energy")+(!bandFresh?T(" · 等待更新"," · waiting"):QString());bandChart->emptyText=T("等待设备频带结果","Waiting for device band results");bandChart->update();
        holdButton->setText(frozen?T("显示已冻结","Display frozen"):T("冻结显示","Freeze display"));
        auto active=client.config.value("active").toArray();bool known=client.config.value("activeWordsKnown").toBool()&&active.size()==32;
        bool monitor=known&&(quint32(active[14].toDouble())&1u);
        monitorButton->setText(client.monitorIntent>=0?T("正在申请控制…","Requesting control…"):client.pending?T("正在应用…","Applying…"):monitor?T("停止监测","Stop monitoring"):T("开始监测","Start monitoring"));
        monitorButton->setEnabled(!preview&&client.connected&&known&&client.monitorIntent<0&&!client.pending&&client.capability("eventCapture")&&client.capability("configCommit"));
        clearEventsButton->setText(T("清除全部","Clear all"));clearEventsButton->setEnabled(!client.events.isEmpty());
        eventsState->setText(monitor?(fresh?T("已开启 · 等待声音变化；最近事件 ","Enabled · waiting for sound changes; recent events ")+QString::number(client.events.size()):T("已设置开启，但采集数据未更新","Enabled in config, but acquisition is stale")):T("未开启 · 点击开始后才监测","Off · press Start to monitor"));
        quint32 learnedFrames=(client.measured.words.size()==32&&client.measured.words[2]>=client.monitorFirstFrame)?client.measured.words[2]-client.monitorFirstFrame:0;
        if(monitor&&fresh&&client.monitorSince>=0&&learnedFrames<24)
            eventsState->setText(T("正在准备背景（按采集帧估算） ","Preparing background (frame estimate) ")+QString::number(learnedFrames)+" / 24");
        auto queues=client.status.value("queues").toObject();
        eventsState->setText(eventsState->text()+"\n"+T("SD循环存储 ","SD loop storage ")+QString::number(queues.value("eventSpoolBytes").toString().toDouble()/1048576.0,'f',1)+" / "+QString::number(queues.value("eventSpoolLimitBytes").toString().toDouble()/1048576.0,'f',0)+T(" MiB · 满时替换最早事件"," MiB · oldest replaced when full"));
        if(!client.capability("eventCapture"))eventsState->setText(T("事件采集尚未接通","Event capture not connected yet"));
        if(shownEvents!=client.events){
            shownEvents=client.events;
            eventList->clear();for(auto e:client.events){
                auto o=e.toObject();QString id=o.value("eventId").toString();
                QString state=o.value("acked").toBool()?T("已确认","Acknowledged"):T("已保存","Saved");
                quint32 eventFlags=quint32(o.value("flags").toDouble());
                if(eventFlags&1u)state+=T(" · 片段不完整"," · incomplete clip");
                if(eventFlags&2u)state+=T(" · 有事件丢失"," · events lost");
                if(eventFlags&4u)state+=T(" · 摘要过期"," · stale summary");
                bool firstOk=false,lastOk=false;quint64 first=o.value("firstSampleIndex").toString().toULongLong(&firstOk),last=o.value("lastSampleIndex").toString().toULongLong(&lastOk);
                float fs=sm::real(quint32(o.value("sampleRateFloat32Bits").toDouble()));QString timing=T("采样时间未知","Sample time unavailable");
                if(firstOk&&lastOk&&last>=first&&std::isfinite(fs)&&fs>=8000&&fs<=192000)timing=T("片段起点 +","Clip start +")+QString::number(double(first)/fs,'f',2)+T(" 秒 · 时长 "," s · duration ")+QString::number(double(last-first+1)/fs,'f',2)+T(" 秒"," s");
                quint32 reason=quint32(o.value("clipReason").toDouble());
                QString category=(reason&1)?T("声音增强","Sound increase"):(reason&2)?T("频带变化","Band change"):(reason&4)?T("规律声中断","Sound interruption"):T("声音变化","Sound change");
                auto item=new QListWidgetItem(category+" · "+id.right(8)+" · "+state+"\n"+timing);item->setSizeHint(QSize(600,70));item->setData(Qt::UserRole,o);eventList->addItem(item);
            }
        }
        QString fault=T("尚无有效快照","No valid snapshot");if(w.size()==32&&fresh){
            QStringList reasons;quint32 v=w[10];
            if(v&(1u<<23))reasons<<T("传感器未接通或异常","Sensor unavailable or fault");
            if(v&(1u<<14))reasons<<T("事件时间存在间隔","Event timestamp gap");
            if(v&(1u<<20))reasons<<T("录音缓冲异常","Recording buffer fault");
            if(v&(1u<<21))reasons<<T("事件有丢失","Event lost");
            if(v&(1u<<30))reasons<<T("配置被拒绝","Configuration rejected");
            if(v&0x800003feu)reasons<<T("采样或处理链异常","Acquisition or processing fault");
            fault=v?reasons.join(T("、",", ")):T("无报告故障","No reported faults");if(v&&reasons.isEmpty())fault=T("其他故障，请查看电脑诊断","Other fault; inspect PC diagnostics");
        }
        health->setText(T("采样 ","Acquisition ")+(fresh?T("运行中","Running"):T("等待数据","Waiting"))+"\n"+T("当前故障 ","Faults ")+fault);
        QStringList ips;for(auto a:QNetworkInterface::allAddresses())if(a.protocol()==QAbstractSocket::IPv4Protocol&&!a.isLoopback())ips<<a.toString();
        diagnostic->setText(T("网口地址：","IP: ")+(preview?T("预览不读取板卡网口","Not read in preview"):(ips.isEmpty()?T("未连接","Not connected"):ips.first()))+"\n"+T("电脑端口：48120 / 48121","PC ports: 48120 / 48121")+"\n"+T("温度 ","Temp ")+temp+T("   湿度 ","   Humidity ")+humid+"\n"+T("气压 ","Pressure ")+pressure+"   "+speedTitle+" "+speed);
        ownerButton->setText(client.token.isEmpty()?T("本机控制","Local control"):T("释放控制","Release control"));ownerButton->setEnabled(client.connected&&!preview);
        periodicButton->setEnabled(!preview&&known&&!client.pending&&!client.token.isEmpty()&&client.capability("configCommit"));
        periodicButton->setText(known&&(quint32(active[8].toDouble())&1)?T("暂停扩展分析","Pause analysis"):T("恢复扩展分析","Resume analysis"));
    }
};

int main(int argc,char **argv){
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);QApplication app(argc,argv);
    QCoreApplication::setOrganizationName("echo");QCoreApplication::setApplicationName("portable-panel");
    QString fontFile=qEnvironmentVariable("SIXMIC_FONT_FILE");
    if(fontFile.isEmpty())fontFile=QCoreApplication::applicationDirPath()+"/../share/fonts/NotoSansCJK-Regular.ttc";
    if(QFile::exists(fontFile))QFontDatabase::addApplicationFont(fontFile);
    QFont f("Noto Sans CJK SC");f.setPixelSize(22);f.setWeight(QFont::Medium);app.setFont(f);
    app.setStyle("Fusion");app.setStyleSheet(
        "QWidget{background:#18283a;color:#eaf1f8;} QLabel{background:transparent;}"
        "#top,#rail{background:#102033;} #brand{font-size:28px;font-weight:700;color:#7ec8ef;}"
        "#pageTitle{font-size:27px;font-weight:600;} #metricCaption{font-size:19px;color:#b4c7d9;}"
        "#metricValue{font-size:38px;font-weight:600;} #toast{background:#0f1d2c;font-size:18px;color:#b9cedf;}"
        "#source{font-size:17px;color:#c1d1df;} QPushButton{background:#30465e;border:1px solid #4a627b;border-radius:9px;padding:6px 12px;font-size:22px;font-weight:600;}"
        "QPushButton:checked{background:#245e88;border-color:#70bae8;} QPushButton:pressed{background:#3579a7;}"
        "QPushButton:disabled{background:#243448;color:#8c9eaf;border-color:#354a60;}"
        "QListWidget{background:#102033;border:1px solid #38516c;border-radius:8px;font-size:21px;} QListWidget::item{padding:8px;}"
        "QCheckBox{font-size:24px;} QCheckBox::indicator{width:34px;height:34px;} QMessageBox QLabel{font-size:20px;}"
    );
    QCommandLineParser parser;parser.addHelpOption();
    parser.addOption(QCommandLineOption("host","Gateway host","host","127.0.0.1"));
    parser.addOption(QCommandLineOption("port","Control port","port","48120"));
    parser.addOption(QCommandLineOption("profile","Installed profile metadata for service decoding","file"));
    parser.addOption(QCommandLineOption("preview","Explicit saved test input; never device live","file"));
    parser.addOption(QCommandLineOption("screenshot","Save a preview screenshot and exit","file"));
    parser.addOption(QCommandLineOption("page","Initial page 0..5","page","0"));
    parser.addOption(QCommandLineOption("windowed","Window mode for PC verification"));parser.process(app);
    Client client;client.host=parser.value("host");bool ok=false;int p=parser.value("port").toInt(&ok);if(!ok||p<1||p>65535)return 2;client.port=quint16(p);
    if(parser.isSet("profile")){QFile file(parser.value("profile"));if(!file.open(QIODevice::ReadOnly)||file.size()>1048576)return 3;client.profile=QJsonDocument::fromJson(file.readAll()).object();}
    bool preview=parser.isSet("preview");
    if(preview){QFile file(parser.value("preview"));if(!file.open(QIODevice::ReadOnly)||file.size()>1048576)return 4;auto d=QJsonDocument::fromJson(file.readAll()).object();for(auto x:d.value("spectrum").toArray())client.spectrum<<float(x.toDouble());for(auto x:d.value("bands").toArray())client.bands<<float(x.toDouble());client.message="已保存板上测试数据预览 · 不代表真实麦克风";}
    Panel panel(client,preview);panel.select(qBound(0,parser.value("page").toInt(),5));
    if(parser.isSet("windowed"))panel.show();else panel.showFullScreen();
    if(!preview)client.connectDevice();
    if(parser.isSet("screenshot"))QTimer::singleShot(350,&app,[&]{bool saved=panel.grab().save(parser.value("screenshot"));app.exit(saved?0:5);});
    QObject::connect(&app,&QCoreApplication::aboutToQuit,&client,[&]{client.release();client.cancelSubscriptions();client.control.flush();});
    return app.exec();
}
