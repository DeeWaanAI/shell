# Layer 6 — Shell design sketch

**Status:** design only, after the frozen pre-flight demo passed.  
**Contracts:** Qafiya v1.1/v1.3, dvr/1.1 with literal and evidence addenda, action record v0.1, memory binding v1.0, model routing policy v1.1.  
**Evidence base:** `preflight/output/frozen/summary.json` (12/12 checks), `preflight/spine-result.json` (PASS), and `preflight/MANIFEST.json`.

## 1. Product shape

The shell is one surface with a stable frame and a generated workspace.

- **One prompt box.** The user states intent once. The shell does not make the user choose a model, a data store, or an action adapter before asking.
- **Generated workspace.** L2 renders the answer as a table, list, tree, or deck. Every data-bearing node resolves through its binding; check state and coverage remain visible.
- **Actionable results.** An editable cell produces a DVR edit binding and writes through qafiya-core. An action node emits an approve/reject intent; only L3's deterministic gate can execute it.
- **Inspectable memory.** The user can ask what the system remembers, open the evidence for a memory item, and trace it to source turns. Corrections and deletions remain L4 protocols, not shell-side edits.
- **Visible routing.** A route indicator shows the selected connection, local/cloud locus, decision reference, declared cost, warnings, and refusal reason where applicable. The full gate trace is available through the L5 decision evidence.
- **Local-first, user-owned connections.** The shell presents the user's L5 connect list. It does not invent provider prices, enumerate providers during routing, or turn a desktop-app subscription into API access.

The shell never treats generated text as proof. A number comes from a binding, an action result comes from an action record, a memory statement comes from a memory record, and a route comes from a decision record.

## 2. Interaction principles

1. **Prompt to artifact, not prompt to prose alone.** Each successful request yields a rendered view plus references to the records that support it.
2. **Direct manipulation without re-prompting.** Cell edits and action choices happen in the generated view. Their effects return to the same journey and audit log.
3. **Authority stays below the display.** DVR emits user intent. Qafiya owns data write-back, L3 owns action execution, L4 owns memory protocols, and L5 owns model selection.
4. **Evidence is one interaction away.** Claims, action records, and memory values expose their source records and check state through the L2 evidence path.
5. **Negative states are first-class.** UNRESOLVED, FAIL, PENDING, refusal, unavailable connections, and partial coverage remain visible. No spinner or generic error may replace a typed outcome.
6. **Every journey is replayable.** A session id joins the prompt, routing decision, recalled memories, views, edits, actions, and resulting memory records.
7. **Audit does not mean indiscriminate content logging.** The shell logs every transition and reference, but secrets never enter records. Prompt/response text follows the active L5 logging policy; L4 writes go only through its binding.

## 3. Runtime kernel loop

### 3.1 Named states

| State | Required work | Principal output |
|---|---|---|
| `RECEIVED` | Accept the exact user prompt and attachments; create/join `s_*` and `req_*`. | request record |
| `ROUTED` | Call L5 `route(request)`; persist its decision reference, chosen connection or typed refusal. | `dec_*`, `b_*` |
| `RECALLED` | Read only through L4's memory binding; record the emitted memory ids/context hash. | memory context refs |
| `COMPOSED` | Produce the intended answer/view/action plan using the routed answer and recalled context. | composition record |
| `VIEW_VALIDATED` | Validate the emitted spec and every binding reference against frozen dvr/1.1. | `v_*` |
| `RENDERED` | Render through L2 and expose coverage, badges, and evidence. | HTML + view refs |
| `AWAITING_USER` | Pause when a cell edit, action approval, correction, or deletion requires user intent. | pending interaction ref |
| `WRITE_BACK` | For a cell edit, call DVR `edits.apply`; invalidate, re-prove, and re-render. | edit `b_*`, history ref |
| `ACTION_GATED` | For an action choice, pass the intent to L3. L3 checks grant, preconditions, undo, and confirmation. | `a_*` |
| `EXECUTED` | Record DONE, REFUSED, FAILED, or IRREVERSIBLE_DONE exactly as returned by L3. | outcome + execution refs |
| `REMEMBERED` | Append session turns and any derived note through L4, with source/derivation links. | `m_*` |
| `CLOSED` | Append the terminal audit event and expose the complete journey for inspection. | terminal `r_*` |

`REFUSED`, `FAILED`, and `UNRESOLVED` are terminal or recoverable states with records, not invisible exceptions. A routing refusal skips model composition but still reaches `CLOSED`. An action rejection is logged and produces no execution. An edit that cannot re-prove remains visibly pending or failed; it is not presented as clean.

### 3.2 Main sequence

```text
RECEIVED → ROUTED → RECALLED → COMPOSED → VIEW_VALIDATED → RENDERED
                                                       ├─→ WRITE_BACK → VIEW_VALIDATED
                                                       ├─→ AWAITING_USER → ACTION_GATED → EXECUTED
                                                       └─→ REMEMBERED → CLOSED
```

The pre-flight artifact is the initial concrete instance: prompt → expense view → bound edit and re-render → confirmed file-create action → L4 journey note → inspectable memory view.

### 3.3 Audit log: `ds:shell_audit`

The shell owns one Qafiya-conformant append-only dataset:

```text
datasets/shell_audit/
  schema.json  data.jsonl  history.jsonl  bindings.jsonl  SUPERSEDED.json
```

Each `r_*` event contains:

- `session_id`, monotonic `sequence`, `state`, and `created_at`;
- `request_ref`, `decision_ref`, `view_refs`, `edit_refs`, `action_refs`, and `memory_refs` as applicable;
- `input_event_refs` so the event graph is explicit rather than inferred from timestamps;
- artifact hashes and check/coverage outcomes needed to replay the transition;
- a binding id for the event's displayed claim or value;
- no secret values and no content prohibited by the active logging policy.

L3 and L5 histories remain in their owning datasets. The shell audit log joins them; it does not duplicate or rewrite them. A spine must be able to start with a session id, enumerate every event, resolve every reference, and verify all owned chains.

## 4. Screen inventory and DVR fit

The original L2 probe established **4/6** expressible screen classes under dvr/1.0. This sketch does not present that historical result as the current contract. Under dvr/1.1, action confirmation is now demonstrated by the pre-flight, so the design reconciliation is **5/6**, with connection controls as the remaining gap.

| Screen | Shell composition | DVR status and evidence |
|---|---|---|
| Prompt and answer | Stable prompt frame + generated list/claim view | Expressible; original probe and pre-flight |
| Data table and edit | Generated table + editable value nodes | Expressible; real `r_051` write-back passed |
| Claim with evidence | Claim node + live evidence panel | Expressible; 21 Q3 source rows returned |
| Action confirmation and audit | Generated dvr/1.1 `action` node + L3 views | Expressible since dvr/1.1; frozen A40 and live action rendered |
| Memory inspection | Generated list/tree + literal values + evidence | Expressible; L4 note and provenance rendered |
| Connection manager | **Built-in shell settings surface**, backed by L5 | Live controls remain outside dvr/1.1 |

### 4.1 Connection-manager decision: documented workaround

For the first shell prototype, the connection manager is a native settings screen, not a generated DVR view. It calls only L5's public connection operations:

- list user-declared connections;
- refresh the provider's model list only when the user asks;
- add a connection with secret environment-variable names, never secret values;
- run measured status checks;
- change endpoint privacy declarations;
- retire broken entries only by explicit user request.

Static connection details and historical health records may also appear in generated, literal-bound views. The live operations—add, connect, retry, status refresh, privacy change, and retire—stay in the native L5-backed surface. This avoids silently treating live service effects as data edits.

If a later requirement demands model-generated connection-management views, it needs a separate versioned DVR proposal for service status and service-effect nodes. That is not part of this prototype and is not widened by L6.

## 5. Prior art and differentiation

- **AIOS and semantic file systems.** AIOS frames the LLM as an operating-system kernel and agents as applications [6]. *From Commands to Prompts* places semantic file access inside that agent OS [1]. L6 adopts the unified intent surface but differs in its proof substrate: displayed values, edits, actions, memories, and routes retain explicit provenance.
- **Generative UI.** Generative interfaces and UI-DSL work show that useful interfaces can be produced just in time [32–35]. L6 does not claim that generating UI is new. Its distinction is durable binding: the generated component resolves live data, writes through a governed edit path, and exposes evidence after the generating interaction has ended.
- **Software as content.** Dynamic applications as the human–agent interaction layer motivate treating the interface itself as generated content [38]. L6 narrows that idea to a closed, validated grammar with explicit non-goals. Native surfaces remain where the grammar has no authority-safe semantics, as with connection controls.

The contribution is therefore the integration: one auditable journey across prompt, route, recall, view, action, and memory—not a new claim that prompts, routers, or generated interfaces independently exist.

## 6. Prototype boundary

The first prototype should grow the frozen pre-flight, not start a second shell architecture. It must demonstrate:

1. one visible journey with stable session and audit references;
2. L5 route display using a real or dry-run decision record;
3. L2 rendering, edit write-back, evidence, and re-proof;
4. L3 approve and reject paths with no execution on rejection;
5. L4 inspection plus correction/deletion through their existing protocols;
6. the native L5 connection screen, including measured failure and explicit retirement;
7. a shell spine that replays the audit graph and reports refusals, failures, and coverage.

No deployment, provider addition, paid model call, shell-side secret store, or new DVR role is implied by this sketch.

## 7. References

Reference numbers follow Layer 1's verified literature review.

1. Shi, Z., Mei, K., Jin, M., et al. (2024). *From Commands to Prompts: LLM-based Semantic File System for AIOS.* https://doi.org/10.48550/arXiv.2410.11843
6. Mei, K., Zhu, X., Xu, W., et al. (2024). *AIOS: LLM Agent Operating System.* https://doi.org/10.48550/arXiv.2403.16971
32. Chen, J., Zhang, Y., Zhang, Y., et al. (2025). *Generative Interfaces for Language Models.* https://doi.org/10.48550/arXiv.2508.19227
33. Lee, K. (2025). *Towards a Working Definition of Designing Generative User Interfaces.* https://doi.org/10.1145/3715668.3736365
34. Peng, Y.-H., Bigham, J. P., Wu, J. (2026). *Efficient Personalization of Generative User Interfaces.* https://doi.org/10.48550/arXiv.2604.09876
35. Zhou, Y., Yuan, M., Xu, H., et al. (2026). *LEGOUI: Designing with UI-DSL Bricks to Balance Transparency and Controllability.* https://doi.org/10.48550/arXiv.2608.04293
38. Xie, M., Xie, Y. (2026). *Software as Content: Dynamic Applications as the Human-Agent Interaction Layer.* https://doi.org/10.48550/arXiv.2603.21334
