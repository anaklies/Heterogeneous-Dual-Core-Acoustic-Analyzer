# Runtime independent review and resolution

Read-only native child: /root/pl_runtime_review. It ran no tests.

Accepted finding1: zero-count response and newrequest in one cycle could cancel outstanding activity. Reproduced failure in pl_system/cache/axi_guard_red/simulate.log; fixed explicit old-counter checks. Green18 checks.

Accepted finding2: smoothing float parameter was converted to unsigned before range rejection. Added pre-conversion bounds;21 numeric comparisons groups/3137values and5 invalid inputs passed, plus vendor Cmodel safe_transport.

Parent additional fix: HLS APdone does not replace target DMA quiescence. Added WAIT_DMA and kernel_dma_idle; bridge423 checks include pending DMA ownership. kernel_dma_idle must be produced by actual selected-core monitors, not tied high in a physical integration.

No DeepSeek or dualmodel execution acceptance claimed.
