# Clock ancestry is MMCM -> BUFIO(SerialClk) and BUFR /5(PixelClk).
# The old PixelClk -> SerialClk declaration reversed that physical ancestry.
# MMCM/BUFR clocks propagate the actual worst-case 300MHz serial/60MHz
# pixel startup mode. The production driver limits later modes to <=60MHz.
