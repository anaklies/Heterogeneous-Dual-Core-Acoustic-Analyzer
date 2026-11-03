set out C:/Users/sunxi/Desktop/sixmic3D/deployment/echo_vivado_screenshots_20261101
write_bd_layout -force -format svg -orientation landscape $out/Vivado_Block_Design.svg
write_bd_layout -force -format pdf -orientation landscape $out/Vivado_Block_Design.pdf
report_utilization -hierarchical -hierarchical_depth 4 -file $out/hierarchical_utilization.rpt
report_timing_summary -name ECHO_FINAL_TIMING -file $out/current_timing.rpt
puts ECHO_REPORT_EXPORT_DONE
