// Optional LCD player. Localization and main UI never depend on this process.
#include <QCoreApplication>
#include <QtEndian>
#include <QElapsedTimer>
#include <QCryptographicHash>
#include <QThread>
#include <QDir>
#include <QFile>
#include <cstdio>
#include <cstring>
#include <csignal>
#include <cstdint>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/file.h>
#include <sys/resource.h>
#include <linux/gpio.h>
#include <linux/spi/spidev.h>

static volatile sig_atomic_t stopping;
static void stop(int) { stopping = 1; }

class Lcd {
    int gpio = -1, spi = -1, memory = -1, lock = -1;
    volatile uint32_t *regs = nullptr, *slcr = nullptr;
    uint32_t control = 0;
    bool started = false;

    void writeReg(unsigned offset, uint32_t value) {
        __sync_synchronize();
        regs[offset / 4] = value;
        __sync_synchronize();
    }

    bool pins(int dc, int reset, int light) {
        gpiohandle_data data = {};
        data.values[0] = dc; data.values[1] = reset; data.values[2] = light;
        return ioctl(gpio, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &data) == 0;
    }

    bool transfer(const uint8_t *data, unsigned size) {
        if (stopping) return false;
        if (spi >= 0) {
            // Stay below the standard spidev 4096-byte buffer limit.
            while (size) {
                unsigned count = qMin(size, 4096u);
                spi_ioc_transfer transaction = {};
                transaction.tx_buf = uintptr_t(data);
                transaction.len = count;
                transaction.speed_hz = 16666666;
                transaction.bits_per_word = 8;
                if (ioctl(spi, SPI_IOC_MESSAGE(1), &transaction) != int(count)) return false;
                data += count; size -= count;
            }
            return true;
        }
        // Cadence PS SPI0, manual CS and manual-start; FIFO bursts <= 64 bytes.
        // Exact register bits follow AMD XSpiPs. A 20 ms deadline bounds each burst.
        writeReg(0, (control & ~0x3c00u) | 0x3800u);
        while (size && !stopping) {
            unsigned count = qMin(size, 64u), received = 0;
            writeReg(4, 0x43);
            for (unsigned i = 0; i < count; ++i) writeReg(0x1c, data[i]);
            writeReg(0, (control & ~0x3c00u) | 0x3800u | 0x10000u);
            QElapsedTimer timer; timer.start();
            while (received < count) {
                uint32_t status = regs[1];
                if (status & 0x3u) { writeReg(0, control); return false; }
                if (status & 0x10u) { (void)regs[0x20 / 4]; ++received; }
                else if (timer.elapsed() >= 20 || stopping) { writeReg(0, control); return false; }
            }
            data += count; size -= count;
        }
        writeReg(0, control);
        return !stopping;
    }

    bool command(uint8_t code, std::initializer_list<uint8_t> bytes = {}) {
        if (!pins(0, 1, started ? 1 : 0) || !transfer(&code, 1) || !pins(1, 1, started ? 1 : 0)) return false;
        return bytes.size() == 0 || transfer(bytes.begin(), bytes.size());
    }

public:
    ~Lcd() {
        if (gpio >= 0) { pins(1, 1, 0); close(gpio); }
        if (regs) { writeReg(0x14, 0); munmap(const_cast<uint32_t *>(regs), 4096); }
        if (slcr) munmap(const_cast<uint32_t *>(slcr), 4096);
        if (memory >= 0) close(memory);
        if (spi >= 0) close(spi);
        if (lock >= 0) close(lock);
    }

    bool open(bool allowMmio) {
        lock = ::open("/run/sixmic/lcd.lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
        if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) return false;
        for (const QString &entry : QDir("/dev").entryList({"gpiochip*"}, QDir::System)) {
            QByteArray name = ("/dev/" + entry).toLocal8Bit();
            int chip = ::open(name.constData(), O_RDONLY | O_CLOEXEC);
            if (chip < 0) continue;
            gpiochip_info info = {};
            if (!ioctl(chip, GPIO_GET_CHIPINFO_IOCTL, &info) &&
                std::strstr(info.label, "zynq") && info.lines >= 57) {
                gpiohandle_request request = {};
                request.lineoffsets[0] = 54; request.lineoffsets[1] = 55; request.lineoffsets[2] = 56;
                request.lines = 3; request.flags = GPIOHANDLE_REQUEST_OUTPUT;
                request.default_values[0] = 1; request.default_values[1] = 1;
                std::strcpy(request.consumer_label, "sixmic-lcd");
                if (!ioctl(chip, GPIO_GET_LINEHANDLE_IOCTL, &request)) gpio = request.fd;
            }
            close(chip); if (gpio >= 0) break;
        }
        if (gpio < 0) return false;
        spi = ::open("/dev/spidev0.0", O_RDWR | O_CLOEXEC);
        if (spi >= 0) {
            uint8_t mode = SPI_MODE_3, bits = 8;
            uint32_t speed = 16666666;
            if (ioctl(spi, SPI_IOC_WR_MODE, &mode) || ioctl(spi, SPI_IOC_WR_BITS_PER_WORD, &bits) ||
                ioctl(spi, SPI_IOC_WR_MAX_SPEED_HZ, &speed)) return false;
        } else {
            // This fallback is ONLY allowed when DT leaves SPI0 disabled: no
            // kernel owner can race the MMIO access. No arbitrary addresses.
            QFile status("/sys/firmware/devicetree/base/amba/spi@e0006000/status");
            if (!allowMmio || !status.open(QIODevice::ReadOnly) || status.readAll() != QByteArray("disabled\0", 9)) return false;
            memory = ::open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
            if (memory < 0) return false;
            void *r = mmap(nullptr, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, memory, 0xe0006000);
            void *s = mmap(nullptr, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, memory, 0xf8000000);
            if (r == MAP_FAILED || s == MAP_FAILED) {
                if (r != MAP_FAILED) munmap(r, 4096);
                if (s != MAP_FAILED) munmap(s, 4096);
                return false;
            }
            regs = static_cast<volatile uint32_t *>(r); slcr = static_cast<volatile uint32_t *>(s);
            slcr[8 / 4] = 0xdf0d; // SLCR unlock; only SPI0 clock-enable bits change.
            slcr[0x12c / 4] |= (1u << 14); // APER SPI0 clock.
            slcr[0x154 / 4] |= 1u; // SPI0 reference clock; FSBL divisor retained.
            slcr[4 / 4] = 0x767b;
            __sync_synchronize();
            writeReg(0x14, 0); writeReg(0x0c, 0x7f);
            // Master, CPOL/CPHA=3, 166.67MHz / 16, force CS, manual start.
            control = 1u | 6u | (3u << 3) | 0x4000u | 0x8000u | 0x3c00u;
            writeReg(0, control); writeReg(0x28, 1); writeReg(0x2c, 1);
            for (unsigned i = 0; i < 128 && (regs[1] & 0x10); ++i) (void)regs[8];
            writeReg(4, 0x43); writeReg(0x14, 1);
        }
        if (!pins(1, 0, 0)) return false;
        QThread::msleep(30);
        if (!pins(1, 1, 0)) return false;
        QThread::msleep(120);
        // Vendor 1.47 inch IPS initialization, landscape, row offset 34.
        if (!command(0x11)) return false;
        QThread::msleep(120);
        if (!command(0x36, {0xa0}) || !command(0x3a, {0x05}) ||
            !command(0xb2, {0x0c, 0x0c, 0x00, 0x33, 0x33}) || !command(0xb7, {0x35}) ||
            !command(0xbb, {0x35}) || !command(0xc0, {0x2c}) || !command(0xc2, {0x01}) ||
            !command(0xc3, {0x13}) || !command(0xc4, {0x20}) || !command(0xc6, {0x0f}) ||
            !command(0xd0, {0xa4, 0xa1}) || !command(0xd6, {0xa1}) ||
            !command(0xe0, {0xf0,0x00,0x04,0x04,0x04,0x05,0x29,0x33,0x3e,0x38,0x12,0x12,0x28,0x30}) ||
            !command(0xe1, {0xf0,0x07,0x0a,0x0d,0x0b,0x07,0x28,0x33,0x3e,0x36,0x14,0x14,0x29,0x32}) ||
            !command(0x21) || !command(0x29)) return false;
        return true;
    }

    bool frame(const QByteArray &pixels) {
        if (pixels.size() != 320 * 172 * 2) return false;
        if (!command(0x2a, {0,0,1,0x3f}) || !command(0x2b, {0,34,0,205}) || !command(0x2c)) return false;
        if (!transfer(reinterpret_cast<const uint8_t *>(pixels.constData()), pixels.size())) return false;
        started = true;
        return pins(1, 1, 1);
    }
};


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
