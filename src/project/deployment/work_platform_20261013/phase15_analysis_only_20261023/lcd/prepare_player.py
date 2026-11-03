"""Reproducibly adapt a read-only legacy PS driver into this isolated candidate."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
source = (ROOT/'deployment/sixmic_lcd_gif_20261012.cpp').read_text(encoding='utf-8')
source = source.replace('#include <QImageReader>', '#include <QtEndian>')
source = source.replace('#include <QPainter>\n', '')
source = source.replace('        pins(1, 0, 0); QThread::msleep(30); pins(1, 1, 0); QThread::msleep(120);',
'''        if (!pins(1, 0, 0)) return false;
        QThread::msleep(30);
        if (!pins(1, 1, 0)) return false;
        QThread::msleep(120);''')
# Keep existing hardware transport/init; replace runtime GIF decoder with bounded package reader.
source = source[:source.index('static QByteArray render(')] + r'''
static bool load(const QString &filename, QVector<QByteArray> &frames, QVector<int> &delays) {
    QFile file(filename);
    if (!file.open(QIODevice::ReadOnly)) return false;
    const QByteArray header = file.read(16);
    if (header.size() != 16 || std::memcmp(header.constData(), "S6LCD01\0", 8)) return false;
    const auto *p = reinterpret_cast<const uchar *>(header.constData());
    const unsigned width = qFromLittleEndian<quint16>(p+8);
    const unsigned height = qFromLittleEndian<quint16>(p+10);
    const unsigned count = qFromLittleEndian<quint32>(p+12);
    if (width != 320 || height != 172 || count < 1 || count > 120 ||
        file.size() != 16 + qint64(count)*(4+320*172*2)) return false;
    for (unsigned i=0; i<count; ++i) {
        QByteArray delayBytes = file.read(4);
        if (delayBytes.size() != 4) return false;
        unsigned delay = qFromLittleEndian<quint32>(reinterpret_cast<const uchar *>(delayBytes.constData()));
        QByteArray pixels = file.read(320*172*2);
        if (delay < 20 || delay > 60000 || pixels.size() != 320*172*2) return false;
        frames.push_back(pixels); delays.push_back(int(delay));
    }
    return true;
}

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto args = application.arguments();
    bool test = args.contains("--test");
    bool mmio = args.contains("--reserved-spi0");
    QString filename = "/usr/share/sixmic/easter-egg.lcd";
    int index = args.indexOf("--asset");
    if (index >= 0) {
        if (index+1 >= argc || args[index+1].startsWith("--")) return 2;
        filename = args[index+1];
    }
    signal(SIGTERM, stop); signal(SIGINT, stop); setpriority(PRIO_PROCESS, 0, 10);
    QVector<QByteArray> frames; QVector<int> delays;
    if (!load(filename, frames, delays)) { fprintf(stderr,"LCD asset invalid/unavailable\n"); return 2; }
    if (test) {
        QCryptographicHash digest(QCryptographicHash::Sha256);
        int cycle = 0;
        for (int i=0; i<frames.size(); ++i) { digest.addData(frames[i]); cycle += delays[i]; }
        printf("LCD_ASSET_TEST frames=%d width=320 height=172 frame_bytes=%d cycle_ms=%d sha256=%s no_hardware=true\n",
               frames.size(), frames[0].size(), cycle, digest.result().toHex().constData());
        return 0;
    }
    Lcd lcd;
    if (!lcd.open(mmio)) { fprintf(stderr,"Optional LCD unavailable: %s; localization continues\n",strerror(errno)); return 78; }
    while (!stopping) for (int i=0; i<frames.size() && !stopping; ++i) {
        QElapsedTimer elapsed; elapsed.start();
        if (!lcd.frame(frames[i])) { fprintf(stderr,"LCD transfer timeout/error; player stopped\n"); return stopping ? 0 : 4; }
        int delay = qMax(0, delays[i]-int(elapsed.elapsed()));
        for (int remaining=delay; remaining>0 && !stopping; remaining-=20) QThread::msleep(qMin(20,remaining));
    }
    return 0;
}
'''
(HERE/'sixmic_lcd_player.cpp').write_text(source, encoding='utf-8')
