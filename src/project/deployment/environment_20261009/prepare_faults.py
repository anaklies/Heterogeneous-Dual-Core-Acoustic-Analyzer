from pathlib import Path
P=Path(__file__).resolve().parent;F=P.parents[2]/'sixmic3D_fpga'
s=(F/'pl/environment_20261009/before/pl_health_monitor.sv').read_text(encoding='utf8')
s=s.replace('sensor_faults[0] | sensor_faults[4]','sensor_faults[0] | sensor_faults[4] | sensor_faults[5]').replace('sensor_faults[1] | sensor_faults[5]','sensor_faults[1]')
(P/'pl_health_monitor.sv').write_text(s)
s=(F/'pl/environment_20261009/before/fault_catalog.h').read_text(encoding='utf8')
s=s.replace('const int mapped[] = {20, 21, 22, 23, 20};','const int mapped[] = {20, 21, 22, 23, 20, 20};')
s=s.replace('for (int i = 0; i < 5; ++i)','for (int i = 0; i < 6; ++i)')
s=s.replace('            out << f;\n        }\n    if (sensors & 0xe0)', '''            if (i == 5)
            {
                f.title = en ? "IMU pressure unavailable" : "IMU 气压不可用";
                f.location = en ? "Location: IMU registers 0x45/0x46" : "位置：IMU 气压寄存器 0x45/0x46";
                f.cause = en ? "Pressure read failed or value is outside 30..120 kPa." : "气压读取失败或读数不在30～120kPa范围。";
                f.action = en ? "Check IMU pressure capability and I2C; standard-pressure compensation remains available." : "处理：检查IMU气压功能和I²C；系统继续采用标准气压补偿。";
                f.blocking = false;
            }
            out << f;
        }
    if (sensors & 0xc0)''')
(P/'fault_catalog.h').write_text(s,encoding='utf8')
print('Pressure failure is reported separately and does not block localization.')
