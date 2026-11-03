#pragma once
#include "protocol.h"
#include <QtNetwork>
#include <functional>

class Client:public QObject {
public:
    QTcpSocket control,binary;
    QElapsedTimer clock;
    QTimer poll,reconnect,deadline;
    QJsonObject status,caps,config;
    QJsonArray events;
    sm::Measurements measured;
    QString message,host="127.0.0.1",session,epoch,token,subscription;
    quint16 port=48120;
    bool connected=false,fixture=false,pending=false;
    int monitorIntent=-1;
    qint64 monitorSince=-1;
    quint32 monitorFirstFrame=0;
    QVector<float> spectrum,bands;
    QVector<float> channelLevels;
    qint64 levelsReceived=-1;
    QString levelsJob,bandsJob;
    bool bandsPending=false;
    quint32 bandsStarted=0,bandsCompleted=0;
    bool featureRead=false,levelsPending=false;
    bool spectrumPending=false;
    QString spectrumJob;
    qint64 liveRateEpoch=-1;
    quint32 liveRateFrames=0;
    double liveRate=0;
    qint64 spectrumReceived=-1,bandsReceived=-1;
    QString spectrumUnit;
    QString spectrumService="snapshot";
    quint32 spectrumFrame=0;
    QVector<float> noiseReference;
    bool noiseLearning=false;
    int noiseSamples=0;
    quint32 noiseFrame=0;
    std::function<void()> changed;
    QJsonObject profile;
    explicit Client(QObject *parent=nullptr);
    ~Client() override;
    void connectDevice();
    void claim();
    void release();
    void setPage(int page);
    void setMonitor(bool enabled);
    void setPeriodic(bool enabled);
    void refreshEvents();
    void clearEventList();
    void cancelSubscriptions();
    quint64 request(const QString &op,QJsonObject args=QJsonObject());
    bool capability(const char *name) const {return caps.value(name).toBool();}
    QString trText(const QString &zh,const QString &en) const {return english?en:zh;}
    bool english=false;
private:
    QByteArray controlBuffer,binaryBuffer;
    QHash<QString,QString> requests;
    QHash<QString,QJsonObject> requestArgs;
    QHash<quint32,QJsonObject> schemas;
    QHash<quint32,quint32> sequences;
    QHash<quint32,QString> expectedHashes;
    QHash<quint32,quint32> serviceCommits;
    quint64 requestId=0;
    int currentPage=0,pollCount=0;
    QString binaryToken;
    quint64 hiddenEventThrough=0;
    void consumeControl();
    void consumeBinary();
    void reply(const QJsonObject &obj);
    void subscribeResults();
    void notify(){if(changed)changed();}
    void changeConfig(int index,quint32 value);
    void acceptSpectrum(const QVector<float>&,quint32,const QString&);
};
