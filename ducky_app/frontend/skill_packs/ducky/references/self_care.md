---
description: "When Ducky or the PC feels slow, laggy or out of memory: ducky_health finds the cause in plain words, ducky_self_care fixes what Ducky can"
metadata:
  order: 4
  label: "Ducky feels slow: check and fix itself"
  default_enabled: false
  load_condition: "The person says Ducky, the PC or UEFN is slow, laggy, frozen, stuttering, hot, using lots of memory or CPU, or asks why"
---

## Check first, then explain, then fix

1. `ducky_health()`: one call. It samples CPU for a second and lists Ducky's window process
   (memory, threads, handles), its helpers (WebView2, shells, servers), other Ducky processes
   (leftover tool servers flagged `orphan`), sandbox programs, terminals, disk use, UEFN's
   memory, the PC's memory and its top apps, and `findings`: the likely causes, most important
   first, each with its fix.
2. Tell the person what it found in plain words, with the numbers that matter ("Ducky uses
   0.4 GB; UEFN uses 38 GB after 5 hours, which is what stalls the editor"). Say clearly when
   it is NOT Ducky.
3. Fix what Ducky can with `ducky_self_care(action=...)`:
   - `stop_sandbox` (target = a chat id, or `all`): sandbox programs still running.
   - `close_idle_terminals`: agent terminals that are done (never the person's, never running ones).
   - `stop_orphan_bridges`: Ducky tool servers whose IDE or agent is gone.
   - `trim_caches`: video downloads. `prune_sandboxes`: old sandboxes and deleted chats'.
   - `collect_garbage`: a Python collection in the app (rarely the fix by itself).
   Then `ducky_health()` again and say what changed.
4. What only the person can do, say as one clear step: reopen UEFN (its memory never comes back
   during a session), close Browser tabs or heavy chats, close other apps from the top list,
   restart Ducky if its own memory or handles keep climbing.

## Digging deeper (Ducky itself is the cause)

- `ducky_perf_report()`: the slowest UI work, tool payloads and stalls.
- `ducky_memory_report(start_trace=true)`, wait a minute of normal use, call it again: `grew`
  names what keeps allocating.
- Report the exact cause and where in Ducky it is; that is a bug to fix, not a setting.
