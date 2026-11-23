# Layer 6 — Shell / Integration · Design Brief

**Status:** OWNER-CONFIRMED 2026-11-02 — prototype phase OPEN. Build per §9 and `build-instructions-prototype-02-nov-2026-2324.md`; monitor checkpoints apply.  
**Paper title:** *The Agentic OS Shell: One Surface for Prompt, View, Action, and Audit*  
**Design basis:** `sketch.md`, the frozen pre-flight demo, and the monitor's Task 2 review.  
**Frozen contracts:** Qafiya v1.1/v1.3; dvr/1.1 with literal and evidence addenda; action record v0.1 + connection-actions v0.2 (connection.add/retire/privacy_change); memory binding v1.0; model routing policy v1.1.

---

## 1. What we are building

A single user surface that turns a prompt into a bound, interactive artifact and keeps the complete journey auditable. L5 selects the model connection, L4 supplies and stores memory, L2 renders and edits views, and L3 executes approved actions. The shell joins these steps into one session rather than reimplementing any of them.

The contribution is not another chat window or another generative-UI toolkit. It is a runtime in which the user can move from intent to view to action to memory without losing provenance. Every visible result leads back to a record; every effect leads back to user intent and an authority boundary.

The pre-flight has already proved the central integration on real data: one prompt produced a Qafiya view, a qafiya-core cell write-back, an L3-confirmed action, and an inspectable L4 memory note. Its independent spine passes 12/12 journey checks and verifies the frozen artifact set. The prototype will grow that journey rather than start a second architecture.

## 2. Design commitments

1. **One prompt box, generated results.** The user states intent once. The shell returns views and records, not prose detached from evidence.
2. **Authority remains below the display.** DVR emits interaction intent. Qafiya owns data mutation, L3 owns action execution, L4 owns memory protocols, and L5 owns model selection.
3. **Direct interaction without re-prompting.** Cell edits, evidence, action approval/rejection, and memory inspection operate inside the current journey.
4. **Auditability is a runtime property.** Every transition joins a session-addressable event graph. It is not reconstructed later from screenshots or model narration.
5. **Negative outcomes remain visible.** Refusal, failure, unresolved data, low coverage, unavailable connections, and rejected actions are rendered as results.
6. **Local-first without provider paternalism.** The shell uses the user's L5 connections and active routing policy. It neither invents prices nor treats closed GUI subscriptions as API access.
7. **Logging is complete about events, restrained about content.** References and outcomes are always recorded. Secrets never are. Prompt and response content follows the active L5 policy and L4's binding rules.

## 3. User-facing architecture

### 3.1 Stable frame

- prompt input and attachment state;
- session/journey identifier;
- route indicator and evidence link;
- connection-manager entry;
- memory-inspection entry;
- visible terminal and error states.

### 3.2 Generated workspace

L2 renders the current dvr/1.1 view: table, list, tree, or deck. Value, claim, action, label, and structure nodes retain their frozen semantics. Check badges, coverage, edit state, and evidence are not hidden by shell styling.

### 3.3 Route indicator

The indicator distinguishes two quantities that must never be conflated:

- **Declared/estimated cost:** the L5 policy calculation from user-declared connection prices and estimated tokens.
- **Actual metered cost:** the provider usage result after a call. If no metered value exists, the display says “not metered,” not `$0`.

It also shows connection label, local/cloud locus, decision reference, warnings, attempts/escalation, and typed refusal. A local `$0` price remains a user declaration, not a claim that energy or latency was measured.

### 3.4 Native connection manager

Live connection controls remain a native L5-backed settings surface because dvr/1.1 has no service-control role. The first prototype supports list, user-requested provider refresh, add, measured status, privacy declaration, and explicit retirement. It does not silently remove broken entries.

**Every mutating connection operation—add, retire, or privacy change—is also an L3 action record.** The native surface submits intent; L3 permission and confirmation rules govern the effect; the resulting `a_*` reference joins the shell audit graph. Read-only listing and measured status remain L5 operations with their own evidence.

## 4. Runtime kernel

### 4.1 States

| State | Responsibility | Main reference |
|---|---|---|
| `RECEIVED` | Accept prompt and attachments; create/join the session. | `req_*`, `s_*` |
| `ROUTED` | Obtain an L5 answer, plan, or typed refusal. | `dec_*`, `b_*` |
| `RECALLED` | Emit context only through L4's binding. | `m_*`, context hash |
| `COMPOSED` | Form the answer, view, or action plan. | composition record |
| `VIEW_VALIDATED` | Validate dvr/1.1 and binding references. | `v_*` |
| `RENDERED` | Render values, badges, coverage, and evidence. | rendered artifact |
| `AWAITING_USER` | Hold for edit, approval, correction, deletion, or connection intent. | pending interaction |
| `WRITE_BACK` | Apply a DVR edit, invalidate, re-prove, and re-render. | edit `b_*` |
| `ACTION_GATED` | Submit action intent to L3's deterministic gate. | `a_*`, `g_*` |
| `EXECUTED` | Preserve the actual action outcome. | execution/history refs |
| `REMEMBERED` | Append turns/notes through L4 with provenance. | `m_*` |
| `CLOSED` | Close the event graph and expose replay. | terminal `r_*` |

Routing refusal skips composition but still closes with evidence. Action rejection produces no execution. An edit that cannot re-prove is not shown as clean. No state transition is inferred solely from a model's claim that it occurred.

### 4.2 Audit event graph

The shell owns `ds:shell_audit`, with the full Qafiya fileset and chained history. Each append-only `r_*` event records:

- session, monotonic sequence, state, and timestamp;
- request, decision, view, edit, action, memory, and connection-action references as applicable;
- `input_event_refs`, making causal order explicit;
- artifact hashes, check states, coverage, declared cost, and actual metered cost where applicable;
- binding references for values or claims shown to the user;
- content only when the active policy permits it.

Lower-layer records remain in their owning stores. The shell graph joins them without rewriting or merging their bindings. Replay starts from a session id and resolves the complete graph.

## 5. Contract boundaries

| Layer | Shell consumes | Shell must not do |
|---|---|---|
| Qafiya | records, bindings, write-back, invalidation, chained history | mutate JSON directly or bypass checks |
| L2 | dvr/1.1 validation, rendering, edits, evidence | add roles/kinds or merge bindings locally |
| L3 | action records, grants, confirmation, execution, undo | treat button rendering as execution authority |
| L4 | memory read/write, inspection, correction/deletion protocols | edit active memory or history directly |
| L5 | route decisions, user connection list, health and cost records | select models, infer prices, or store secrets |

If an integration does not fit these contracts, development stops and the mismatch goes to the monitor. The three pre-flight clearance cycles are the operating precedent, not an invitation to add adapters.

## 6. Prototype structure

```text
shell/
  kernel.py          # named transitions; no lower-layer authority
  audit.py           # ds:shell_audit append and graph queries
  session.py         # request/session references
  views.py           # L2 validation/render/evidence calls
  interactions.py    # edit and action intent dispatch
  routing.py         # L5 route result and cost presentation
  connections.py     # native L5 surface; mutations submitted to L3
  memory.py          # L4 binding calls only
experiments/
  ...                # frozen journeys, raw artifacts, spine.py
```

This is a module plan, not permission to implement. Existing pre-flight code remains the integration fixture and regression baseline.

## 7. Test and experiment plan

### 7.1 Functional gates

| # | Gate | Pass criterion |
|---|---|---|
| F1 | Kernel transitions | Every allowed transition emits exactly one ordered audit event; illegal transitions fail loudly |
| F2 | Route presentation | Decision, locus, declared cost, actual cost, warnings, and refusal match the L5 record |
| F3 | View/edit round trip | Rendered values recompute; edits create history and visible invalidation before re-proof |
| F4 | Action authority | Approval executes only through L3; rejection and refusal produce no effect |
| F5 | Memory provenance | Inspection returns exactly active memory; evidence and source refs resolve |
| F6 | Connection governance | Add/retire/privacy changes produce L3 records; secrets are absent; retirement requires intent |
| F7 | Audit replay | Every event reference resolves; sequences are complete; all owned chains verify |
| F8 | Failure honesty | Routed refusal, L3 failure, unresolved view, and unavailable connection retain typed visible states |

### 7.2 Frozen experiments

| # | Experiment | Frozen inputs | Headline result recomputed by spine |
|---|---|---|---|
| E1 | End-to-end user journey | Pre-flight corpus + scripted prompt/edit/action/memory | Completion by state; binding/reference coverage; edited values; action and memory outcomes |
| E2 | Auditability walkthrough | Approve, reject, refuse, failure, and unresolved variants | Replay success; missing-reference count; chain verification; visibility of each negative outcome |
| E3 | Routing and cost audit | L5 dry-run and recorded metered decisions | Declared-vs-actual values kept distinct; unmetered cases; route/evidence coverage |
| E4 | Connection governance | Local fake endpoint + user connect-list fixture | L3 records for all mutations; no secret material; status failures visible; no implicit retirement |
| E5 | Shell limits | DVR screen requests and tamper/absence probes | Expressibility ceiling, unrepresentable controls, tamper detection, and uncatchable classes reported as results |

No paid model call is required for the core experiment plan. Any live provider run requires separate owner approval and a declared spend cap. Frozen inputs precede runs; every headline number is recomputed from raw artifacts; if the spine fails, the claim is withdrawn.

## 8. Honesty boundaries

The shell can prove integration and audit trails. It cannot prove that the model understood the user's intent, that generated prose is true, or that a routed answer is optimal. L5's default `trust_user` mode does not classify sensitivity for the user. L3 gates normalized actions, not the correctness of normalization. L4 cannot retract information absorbed into model weights. Hash chains detect modification, not an attacker who rewrites the store and recomputes every hash. Closed GUI applications remain outside routing unless they expose a supported endpoint.

The native connection manager is a documented workaround, not evidence that dvr/1.1 expresses live service controls. The design remains 5/6 for the six original screen classes.

## 9. Deliverable order

1. This brief.
2. **Owner confirmation.**
3. Shell prototype integrating L2–L5 and growing the pre-flight.
4. Functional gates and frozen experiments with an independent spine.
5. Capstone paper draft citing all five layer papers and demonstrating one end-to-end journey on the Linux distro.

## 10. Exclusions

No deployment, external push, provider onboarding, paid run, shell secret store, new DVR role, direct lower-layer data edit, multi-user collaboration, mobile shell, or GUI automation is authorized by this brief.

---

**Awaiting owner confirmation. Prototype work remains stopped.**
