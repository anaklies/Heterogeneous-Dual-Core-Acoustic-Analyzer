# Profile scheduler RTL interface and test evidence

`rtl/control/profile_scheduler.sv` is synthesizable control logic, not an implementation of any of the44 acoustic functions. `CONTROL_TEST_ACCEPTANCE.json` records94 passing XSim assertions and hashes of the tested RTL/TB. No synthesis or hardware measurement was run.

## Integration contract

- One clock domain. Cross PS/PC requests using a proper mailbox/CDC bridge before these ports.
- `implemented_mask` must be a hardware-owned mask of genuinely available algorithms. It is returned unchanged as `capabilities`. Never feed the wish-list/catalog mask. Default `MANDATORY_MASK` contains ten P0 bits; integration must assign bit positions explicitly. Missing P0 bits set `mandatory_missing_mask`, inhibit launch and report error2 rather than generate false results.
- Config request is ready/valid. A single pending slot holds the PS+PC union independently for periodic and optional masks. Unsupported or wrong-priority bits reject the request without changing the active configuration. Requests are not silently overwritten.
- Pending configuration commits only on `frame_start`. Version increments, and response request ID identifies the applied request. A request accepted on the same edge as a frame commits at a later frame, not half-way through this frame.
- Every accepted frame requests mandatory P0. P1 is due every2frames; P2 every11frames, and immediately on an applied new configuration. An active P2 group can suppress unrelated P1 through `pause_unrelated_periodic`. A PS-held subscription is not removed when the PC leaves its page.
- Mask bits identify tasks, not datapath instantiations. Required dependencies within a selected group must be resolved by the integrated backend. Mandatory FFT/PCM/etc remain in P0. This control module does not prove shared FFT/MAC scheduling or arbitrary long P2 preemption. Long P2 jobs must yield/cache state so that mandatory P0 deadlines can still be met.
- `job_start` is a pulse when the backend is idle. Capture `job_mask`, `job_frame_id`, `job_transaction_id` and `job_config_version`. Completion/progress must echo transaction and version. No valid `result_publish` is emitted for an old, canceled or mismatched completion.
- The module dispatches one bounded batch at a time. If another frame arrives while the old batch is still running, it increments `missed_frames`; it never overwrites a live batch. A config change cancels an old live batch, warms/resets the backend, explicitly counts cancellation/miss, then waits for a new frame. This is safe recovery, not a claim of zero dropped frames during config changes.

## Watchdog and recovery

All timeout parameters are **clock cycles**, not milliseconds. P1/P2 periods are **frame counts**. Defaults target4,718,592 maximum job cycles,491,620 no-progress cycles and16 reset cycles; integration must validate these against the actual49.162MHz/96ms workload.

- Absolute job deadline prevents a misleading continuous progress signal from keeping a job alive forever.
- No-progress timeout also bounds a backend that never accepts `job_start`.
- Orphan-busy timeout detects a backend stuck busy even when the dispatcher has no job.
- A timeout gives one finite warm reset and increments counters. Three consecutive timeouts latch `fault_latched` and stop automatic retries. A successful matching batch clears consecutive strikes.
- `clear_counters` clears diagnostic history only; it cannot rearm the fault. `clear_fault` explicitly rearms and gives a finite backend reset. No repeated whole-board reboot loop is implemented.
- Error codes:1unsupported/illegal request,2missing P0 capability,3absolute deadline,4no progress,5orphan busy. Separate canceled/stale/missed/timeout counters remain visible.

## Tests and scope

Runner: `tests/control/run_control.ps1`; creates a new isolated cache directory each time. `run_control.tcl` executes the short TB. Assertions cover mandatory work, P1/P2 decimation, PS/PC subscription union, atomic versions, unsupported bits, wrong/stale transactions, config cancellation, three-strike lockout, separate clears, absolute/no-progress/orphan timeouts and truthful capability reporting.

The first invocation did not run the TB because XSim's generated Tcl misread Windows backslashes. Runner now passes a forward-slash Tcl path. This was a launcher-path defect, not an algorithm pass. The successful run and exact source hashes are in `CONTROL_TEST_ACCEPTANCE.json`; earlier failed logs are retained in its sibling cache directories.

No actual FFT/NN/P2 engine is connected by this standalone test. Do not use it to mark complete PCM, actual throughput, whole-board fit or all44-functions acceptance as passed.
