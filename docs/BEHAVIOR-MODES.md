# Test-bed modes

The charm exposes a `bad-behavior-mode` config option that lets a
single deployed instance simulate a specific bad-behavior pattern.
This file documents what each mode does, which `juju advisorship`
protocol clause it violates, and whether the current v1 `juju advisor`
detector catches it.

The default `none` preserves the charm's well-behaved baseline. The
charm is still used by its own CI as a "compliant charm" reference; the
test-bed modes are opt-in per deployed application.

## Quick start

```bash
# Deploy a compliant charm
juju deploy ./juju-norma-k8s_amd64.charm compliant-charm \
    --resource juju-norma-image=localhost:32000/juju-norma:0.1.0 --trust

# Deploy a misbehaving charm alongside it
juju deploy ./juju-norma-k8s_amd64.charm bad-active \
    --resource juju-norma-image=localhost:32000/juju-norma:0.1.0 --trust \
    --config bad-behavior-mode=active-with-message

# Or change an existing deploy
juju config bad-active bad-behavior-mode=blocked-no-message
```

Run `juju advisor` once across the model and observe how each instance
surfaces (or does not surface) findings.

## Mode catalogue

### `none` (default)

Well-behaved baseline. The charm emits `ActiveStatus()` with empty
message (per §4c.2 convention). v1 `juju advisor` returns no findings.

### `active-with-message`

**Clause violated**: §4c.2 — "active conventionally carries NO
message" (advisor-brief.md:282).

**Implementation**: `_bad_behavior_unit_status()` returns
`ops.ActiveStatus(f"serving on port {port}")`.

**Detected by**: v1 advisor Signal 1 (`active-with-message`, severity
`info`, owner `charm-author`).

**Recovery**: `juju config <app> bad-behavior-mode=none`.

### `blocked-no-message`

**Clause violated**: §4c.2 — "blocked MUST carry an actionable
message" (brief:275). The empty Info string here is deliberately
un-actionable.

**Implementation**: `_bad_behavior_unit_status()` returns
`ops.BlockedStatus("")`.

**Detected by**: forward-looking detector candidate. v1 advisor does
not yet check this.

**Observable in `juju status`**: `Workload: blocked`, `Message: (empty)`.

**Recovery**: `juju config <app> bad-behavior-mode=none`.

### `stuck-maintenance`

**Clause violated**: §4c.2 derivation — maintenance is for
long-running but **bounded** work. Holding it indefinitely is a
misuse; operators have no signal that the charm is actually idle.

**Implementation**: `_bad_behavior_unit_status()` returns
`ops.MaintenanceStatus("preparing calibration suite")` on every
reconcile.

**Detected by**: forward-looking. v1 advisor does not yet check this.

**Observable in `juju status`**: `Workload: maintenance`, `Message:
preparing calibration suite` (no progression).

**Recovery**: `juju config <app> bad-behavior-mode=none`.

### `status-churn`

**Clause violated**: §4c.2 stability — status flips between active
and waiting on every reconcile. Operators reading `juju status` twice
in succession see different states.

**Implementation**: parity of `len(self._event_ledger)` selects
between `ops.ActiveStatus()` and `ops.WaitingStatus("waiting for
nothing in particular")`. Each reconcile flips the parity.

**Detected by**: forward-looking. v1 advisor does not yet check this.

**Observable in `juju status`**: alternating states across consecutive
runs.

**Recovery**: `juju config <app> bad-behavior-mode=none`.

### `hook-error`

**Clause violated**: §4c.1 — hooks MUST complete. An uncaught
exception interrupts the firing protocol and drives the unit to error.

**Implementation**: `_maybe_trigger_hook_error()` raises a
`RuntimeError` inside `_reconcile`, after the event-ledger entry has
been written.

**Detected by**: forward-looking. v1 advisor does not yet check this.

**Observable in `juju status`**: `Workload: error`, `Agent: failed`.

**Recovery** (two steps, both required):

```bash
# 1. Change the config back to a non-crashing mode. The config-changed
#    reconcile will also crash, but the config value is recorded BEFORE
#    the reconcile fires, so the new value is persisted.
juju config <app> bad-behavior-mode=none

# 2. Tell Juju to retry the failed hook.
juju resolve <unit>
```

### `secret-in-relation`

**Clause violated**: §4c.4 — "cryptographic material in plaintext
relation data" anti-pattern. The relation databag is visible to every
unit on the relation and survives `juju show-unit` indefinitely.

**Implementation**: the leader writes `password = "hunter2"` and
`api-key = "AKIA..."` keys into every `calibration-provider` relation
databag during `_update_relation_data`. Only fires when an integration
is established on `calibration-provider`.

**Detected by**: forward-looking. v1 advisor does not yet check this.

**Observable**: `juju show-unit <unit>` exposes the keys under the
relation's `application-data` section.

**Recovery**: `juju config <app> bad-behavior-mode=none` then
`juju refresh` or rebuild — the leader needs to overwrite the data on
the next reconcile.

### `stuck-dying`

**Clause violated**: §4c.1 — hooks MUST complete. Unlike `hook-error`,
this mode raises ONLY during teardown events so the unit deploys
cleanly first. The unit wedges in `Life=Dying` when an operator runs
`juju remove-application <app>`, because the first departure hook
fails.

**Implementation**: `_maybe_trigger_stuck_dying(event)` raises a
`RuntimeError` if the event is a `StopEvent`, `RemoveEvent`,
`RelationBrokenEvent`, or `RelationDepartedEvent`. Called from
`_reconcile()` (catches relation-broken/-departed) and from
`_on_stop()` / `_on_remove()` (catches stop/remove when no relations
are present). The unit's install/start/config-changed hooks complete
normally — only teardown crashes.

**Detected by**: `entity-stuck-dying` (juju advisor). Once the unit
has been wedged for 5+ minutes in Life=Dying with agent=failed, the
detector flags it as a warning.

**Observable in `juju status`**: `Agent: failed`, `Workload:` varies
(may be `active`, `error`, or last-known). `juju show-unit <unit>`
shows `life: dying`. The unit does not progress past Dying because the
departure hook never completes.

**Recovery** (three steps, all required):

```bash
# 1. Change the config back to a non-crashing mode so the retried
#    teardown hook will succeed.
juju config <app> bad-behavior-mode=none

# 2. Tell Juju to retry the failed departure hook. The unit will
#    progress from Dying to Dead.
juju resolve <unit>

# 3. Re-issue the removal. Without an outstanding teardown failure,
#    Juju now reaps the application and its units.
juju remove-application <app>
```

## Multi-instance demo

A canonical multi-instance demo deploys one compliant charm plus four bad
ones in the same model:

```bash
juju add-model norma-demo mk8s

CHARM=./juju-norma-k8s_amd64.charm
RES="--resource juju-norma-image=localhost:32000/juju-norma:0.1.0"

juju deploy $CHARM good        $RES --trust
juju deploy $CHARM bad-active  $RES --trust --config bad-behavior-mode=active-with-message
juju deploy $CHARM bad-blocked $RES --trust --config bad-behavior-mode=blocked-no-message
juju deploy $CHARM bad-stuck   $RES --trust --config bad-behavior-mode=stuck-maintenance
juju deploy $CHARM bad-churn   $RES --trust --config bad-behavior-mode=status-churn

juju status
juju advisor
```

Expected `juju advisor` output (current v1 detector set):

- `bad-active/0` — INFO active-with-message finding.
- All other instances — no findings (but their workload states are
  clearly bad in `juju status` — forcing functions for future
  detectors).

## Adding a new mode

1. Choose the §4c clause being violated.
2. Add the mode name to `BAD_BEHAVIOR_MODES` in `src/charm.py`.
3. Add a branch in `_bad_behavior_unit_status()` (for status modes)
   or write a new helper for non-status modes and wire it where the
   misbehaviour belongs.
4. Add a section above documenting the mode, the citation, the
   implementation, the detector status, the observable, and the
   recovery.
5. Add an entry to the `bad-behavior-mode` config description in
   `charmcraft.yaml`.

Keep `none` as the default in every change.
