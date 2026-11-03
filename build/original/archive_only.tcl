set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/deployment/echo_separate_mic_clocks_20261026
set_param general.maxThreads 2
open_project $root/tmp/echo_separate_io_20261026/instrument_board/instrument_board.xpr
# archive_project uses CWD/.Xil. Keep that path short on Windows.
cd $root/tmp
archive_project -force $out/hardware/recoverable_project.zip
puts SEPARATE_IO_RELEASE_READY
