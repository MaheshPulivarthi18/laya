# Research: can NandhaKishorM/laya (the decision model) be Laya's router stage?

*Research report, 2026-09-28. Status: for discussion; nothing has been implemented.*

To avoid mixing up the two projects with the same name, this report calls the external model **LDM** (Laya Decision Model, https://github.com/NandhaKishorM/laya, weights at `huggingface.co/convaiinnovations/laya`) and our app **Laya**.

## Context

LDM is an open-source "decision model" that does much the same job as our router: it takes content and puts it into categories. This report checks whether LDM could replace or add to `pipeline/router.py`. It covers context length and the other scenarios that affect the answer. The facts about LDM were checked against its repo, its Hugging Face configs and benchmarks, and its GitHub issues as of 2026-09-28. The project changes quickly, so re-check them before acting.

---

## 1. TL;DR verdict

**LDM cannot replace the router one-for-one, and it should not be tried zero-shot.** There are two ways it could still be useful:

1. **A first-tier classifier in a two-tier setup.** LDM would be fine-tuned (distilled) on our own LLM router's past outputs. It answers the persona, priority, category and research questions. When it is unsure, the event goes up to the LLM. This is more attractive for **local-model users**, where the router is currently our weakest stage.
2. **Other stages that suit it better than the router does**, such as a noise and actionability gate, retrieval relevance filtering, and choosing which chat tools to include. See §7.

Before we invest in LDM, we have to compare it with a cheaper option: a small classifier on the **nomic embeddings we already compute**, trained on the same router history. It needs no new model, no torch in the app bundle, and no name clash. See §8.

---

## 2. What LDM actually is (verified facts)

**Model**
- It is an encoder, not an LLM. The body is ModernBERT-large (about 421M parameters) or mmBERT-base (322M, multilingual).
- On top sits a small 2-layer transformer head that scores the answer options you give it, plus a separate "act or escalate" head.
- It produces no text: no explanation, no extracted items, no plans.

**Inputs and outputs**
- The input is a `state` (any text) and a set of named questions. Each question is one of three kinds:
  - `choice`: pick one label.
  - `score`: pick a level on an ordered scale.
  - `noul`: a yes/no probability.
- **You write the labels and their descriptions at the time you ask.** Nothing is fixed in advance.
- Each answer comes back with probabilities, a confidence value, and `act_probability`.

**Checkpoints**

| checkpoint | trained at |
|---|---|
| `laya` (English) | 512 tokens |
| `laya-multilingual` | 1024 tokens |
| `laya-typed-decisions` (fine-tuned) | 1024 tokens |

**Speed**
- On a T4 GPU: about 33–40 ms for 1 question and about 160 ms for 10.
- On a CPU: 190–900 ms for 1 question.
- Each question runs as its own row, so the cost grows roughly in proportion to the number of questions.
- Apple Silicon runs it through MPS (Apple's GPU backend).

**Accuracy**
- Out of the box, the base checkpoints are **close to random** on realistic workflows that ask several questions: 0.36 accuracy against 0.32 for random guessing and 0.46 for always picking the most common label.
- The 0.766 headline figure needs fine-tuning on that same benchmark's training split.
- The repo itself says to treat it as *"a fast base to specialise, not a zero-shot decision engine."*

**Known failure modes (from its GitHub issues)**
- **Ignores negation.** "do NOT cancel" came back as `cancel` with 0.9998 confidence (#377).
- **Reacts to label wording instead of content.** `noul` follows the true/false label text (#156), and yes/no label names skew answers.
- **Position bias.** The multilingual model never chose the first score option (0 of 290, #131).
- **Overconfident as shipped.** Mean calibration error (ECE) is 0.47 before re-fitting and about 0.08 after.
- **Degrades with many options.** Past about 20 options the shared budget for option text runs out.

**Maturity and packaging**

| Aspect | Finding |
|---|---|
| License | Apache-2.0, fine for us |
| Age and churn | 10 days old, 20+ releases in a week |
| Base training data and code | Not released |
| Popularity signals | 26.5k stars in 10 days, but Hugging Face reports 0 downloads, so the numbers are suspect |
| Headline table | Mixes results from three different checkpoints |
| Weights | Published as safetensors, so there is no pickle risk |
| ONNX / GGUF | No official ONNX; GGUF only from third parties |

---

## 3. What our router actually produces, and what LDM can cover

`RouterOutput` (`engine/laya/models/classification.py:43-58`) has 9 fields. The table shows which ones LDM could fill.

| Field | Who reads it downstream | Can LDM fill it? |
|---|---|---|
| `persona` (6 values) | picks the worker (`workers.py`), card, processing rules | ✅ `choice` |
| `secondary_persona` (6 values or none) | runs a second worker | ✅ `choice` with a "none" option; weak |
| `priority` (LOW to CRITICAL) | card, feed sort, processing rules | ✅ `score`, which fits ordered levels well |
| `category` (5 values) | card, stager fallback | ✅ `choice` |
| `requires_research` | picks worker path or simple path (`queue.py:362`) | ✅ `noul` |
| `confidence` | stored; processing-rule conditions | ⚠️ derived; must be recalibrated or rules misfire |
| `entities[]` | `entity_refs` → context grouping, entity resolution, engineer repo lookup, stager | ❌ it cannot extract text |
| `research_plan[]` | engineer and stager prompts, `workspace_api` | ❌ it cannot generate text |
| `reasoning` | only logged | ❌ (no loss) |

**LDM can therefore cover at most 5 of the 9 fields.** If we used it, the other fields would need new homes:
- **`entities`**
  - Much of it can be filled directly from data we already have: repo, PR or issue number, Jira key, participants, subject id and URL. That matches our memory note *hydrate from DB, not LLM*.
  - The remaining meaningful entities (project or customer names) would move into the **stager's schema**, since the stager already reads the event with an LLM.
  - Risk: less entity recall means worse context grouping. We would need to measure this.
- **`research_plan`**: would move into the worker prompt. It is only needed when `requires_research` is true, and a worker LLM runs in that case anyway.

The router is also **not** where noise gets dropped; `rules.py` handles that. Every event that reaches the router becomes a card.

---

## 4. The context-length question: is 8192 enough?

**The question is aimed at the wrong limit.** There are three separate budgets:

1. **8192 is not a trained length.**
   - It is the base encoder's positional ceiling. The English checkpoint was trained at 512 and the others at 1024.
   - The authors' own long-context test used just 20 requests per length. It got 16–18 of 20 right up to about 4k tokens, then 8–17 of 20 beyond that, taking about 1.7 s per 4k-token request on an Apple GPU.
   - The dependable range is **≤1024 tokens**, or ≤512 for the English model.
2. **The budget for questions and options is the real constraint: 192–256 tokens, with each option cut at 48 tokens.**
   - Our router's instructions run about **1,080–1,660 tokens** (`llm/prompts/router.py`):
     - persona definitions and tie-break rules
     - priority guidelines
     - Jira/Linear lifecycle rules
     - PR lifecycle rules
     - an explanation of the actor-relationship labels
   - None of that can be passed as instructions. It would have to shrink to about 48-token label descriptions, and the **conditional logic** would be lost. Examples: "a PR that is merged or declined → LOW", or "a status change to Done → LOW unless a manager is involved".
   - An encoder does not follow rules like these. It could only learn them from training data, and the negation failure (#377) is evidence of that weakness.
3. **Our input (the state) is unbounded.** The engine **never truncates `content.body`** (`api/events.py:36-72`), and the router prints every metadata key.

   | Platform | Typical body | Fits in 512 / 1024? |
   |---|---|---|
   | Slack | a single message | ✅ nearly always |
   | GitHub / Bitbucket | issue or PR description (no diffs) | ✅ mostly; long PR descriptions get cut |
   | Jira / Linear | description + field changes + latest comment | ⚠️ often fine; long descriptions get cut |
   | Calendar | description + **full attendee list** | ⚠️ attendee lists overflow; they should be summarized as a count plus the user's role |
   | Gmail / Outlook | `text or html` of one message, **including quoted history and raw HTML** | ❌ often overflows; HTML is especially wasteful |

   Useful signal tends to sit at the **top** of the body: newest reply first, then the quoted history. Keeping the first N tokens after stripping HTML and quoted text would therefore lose little. LDM's `predict_long` sliding window would cost one pass per window and pick the most confident one. That adds latency and does not reliably help classification.

**Also lost:** the feedback section injected into the user message, which holds up to 20 classification rules, 15 recent corrections and 10 approval patterns (`pipeline/feedback.py:140-230`). An encoder cannot use natural-language rules as instructions. As a result, **the whole learned-rules loop (`learn.py`) would stop affecting LDM's decisions.** Corrections would have to become (a) **training data** for fine-tuning, or (b) deterministic overrides (processing-rule `set_priority` already exists).

**Verdict on length:** 1024 tokens is enough for the *event* once we normalize and trim it. It is **not** enough to carry the router's *instructions and rules*. That second part is the real blocker to using it zero-shot.

---

## 5. Other scenarios

**Accuracy and semantics**
- **Laya-specific label meanings.**
  - Our persona tie-breaks, such as COMMS vs OPS or who counts as SALES, are specific to our product. LDM's zero-shot results on custom multi-question setups are close to chance.
  - Realistically, **zero-shot would be worse than Haiku or a local 7B LLM.** Fine-tuning is required.
- **Time and relative dates.** The LLM router gets the current date and time prepended (`client.py:444-474`) and reasons about "due tomorrow" or "meeting in 30 min". An encoder cannot do date arithmetic, which hurts calendar priority and deadline mentions. Mitigation: compute features in code (for example "starts in 25 min") and add them to the state text.
- **Actor relationship** (manager, external, bot) matters a lot for priority. It can go into the state as text ("From: your manager"), and a fine-tuned model can learn from it.
- **Negation and hedged language** ("no action needed", "don't merge yet", "ignore previous email") are common in work messages, and this is a documented LDM weakness.
- **Multilingual users.** The English checkpoint is weak outside English: 0.23 macro accuracy across 51 languages with badly overconfident scores. The multilingual checkpoint does better at 0.45.

**Confidence and calibration**
- The shipped models are overconfident. Our `confidence` field feeds processing-rule conditions, so uncalibrated values would fire rules wrongly.
- Temperature-fitting is mandatory, and we would redo it on our own validation data.

**Cost and latency**
- The default router is `claude-haiku-4-5` (`client.py:263-287`). Replacing it saves **1 of at least 2 LLM calls per event**: router plus stager, with workers on top when research is needed.
  - The router call is a fat one: about 1–1.7k system tokens plus the body plus the feedback sections.
  - Expect a meaningful but not dominant cut in per-event tokens. `audit_log` has the real numbers to quantify this.
- **For local-LLM users the gain is larger.** Our memory notes record a string of local-router failures:
  - reasoning models truncating output
  - Gemma padding output with newlines
  - the concurrency flood
  - batch routing turned off for local models via the circuit breaker (`queue.py:870-876`)

  A tens-of-milliseconds MPS classifier would remove the router's load on LM Studio entirely.
- **Memory pressure.**

  | Precision | RAM needed |
  |---|---|
  | fp32 | ~1.7 GB |
  | fp16 | ~0.85 GB |

  That comes on top of the nomic embedder and, for local users, an LLM that may already be filling RAM. The users who gain most are the ones who can least spare the memory.

**Packaging and engineering**
- **Name clash.** The PyPI package is called `laya`, the same as our engine package `engine/laya/`. `pip install laya` would shadow our imports or be shadowed by them.
  - We would need to **vendor the small inference core** (`DecisionModel` in `laya/common.py` plus the sequence builder) under another name, or run it as a separate process.
  - Vendoring also shields us from the upstream churn of 20 releases a week.
- **Dependency weight.**
  - It needs `torch` and `transformers>=4.48`. We already have an optional ML extra (`engine/requirements-ml.txt`), so there is a precedent for an opt-in tier.
  - Putting torch in the Tauri bundle by default would be a big size hit. Windows ARM (our #14) has shaky torch support.
  - Exporting to ONNX ourselves (`laya-ts/scripts/export_onnx.py`) and running `onnxruntime` is lighter, with optional int8.
- **Dependency pin risk.** LDM's `mcp` extra requires `mcp>=2.2`, and our #15/#16 incident came from an mcp 2.x rename. We must never install LDM's extras. This is another reason to vendor.
- **Weight download.** 0.65–0.85 GB on first use. We need a download-with-progress step, like the embedding model, and should pin a Hugging Face revision hash.

**Batching**
- `predict_batch` handles many events at once. That fits `_consumer_loop`'s 3 s / 10-event batching better than the LLM batch router, which needs index matching and has a partial-result circuit breaker.

**Retries and fallback**
- If the router fails, the event currently retries and is eventually marked dead. An LDM tier fails in a different way: it gives a quiet wrong answer rather than an error.
- The escalation path (§6) and correction-rate telemetry therefore become required. **We have no router accuracy metric today**, only correction counts.

**Security**
- An encoder is less open to instruction-following prompt injection, because "ignore previous instructions" does nothing to a scorer.
- Adversarial wording can still move its scores, so there is a modest net gain.

---

## 6. The architecture that would work: two tiers with escalation

```
event → rules → [LDM, fine-tuned] ── confident on all fields ─→ RouterOutput
                     │                  (entities filled directly from event
                     │                   data; research_plan left to the worker)
                     └─ unsure / escalation flag / long body ─→ existing LLM run_router
```

**Where it plugs in**
- `run_router` / `run_batch_router` (`pipeline/router.py:70, 167`) can return a `RouterOutput` before calling the LLM.
- `process_event` already accepts a precomputed `RouterOutput` (`queue.py:307-317`).
- `briefing.py:245` already builds one without an LLM, so there is precedent.

**Training data (distillation from our own router)**
- Every event stores its LLM `router_output` (`events.router_output`), which acts as the teacher.
- User corrections (`PATCH /cards/{id}/classification`) are the gold labels.
- The typed-decisions checkpoint was built with the same teacher-student method.
- **Limitation:** the student can at best match the teacher. The gain is cost and latency, not accuracy.
- **Privacy:** local-first means no central training on user data. The options are:
  - (a) ship a checkpoint fine-tuned on **synthetic or public** events with our label definitions, then
  - (b) optionally fine-tune per user on the device (head only) from their router history and corrections.
- Full fine-tuning took about 4–5 hours on 2×T4 for about 30k questions. Head-only tuning on hundreds to thousands of local examples would be much cheaper, but it is unverified.

**Escalation**
- Use LDM's own `act_probability` (its "escalate" head, which is built for this) and/or calibrated confidence thresholds for each field.
- Always escalate when the body was truncated heavily or the language is not English.

**Learned rules**
- These keep working only on the escalated LLM path.
- On the LDM path, corrections become periodic re-training data plus deterministic overrides.
- This is a real product change, because users would see rule learning behave differently. It needs a decision.

---

## 7. Other places LDM could fit (possibly better than the router)

1. **Noise and actionability gate before routing.**
   - Every event becomes a card today, and static `rules.json` is the only filter.
   - A single `noul` question, "does this need the user's attention or action?", run at high-confidence thresholds, could send FYI or bot noise to a cheap path: a LOW card with no stager call.
   - It is tolerant of mistakes because only confident "no" answers are acted on. Of all these ideas it probably has the best cost-saving-to-risk ratio.
2. **Retrieval relevance filter or reranker.**
   - RAG relevance was **in LDM's training mix**, so its zero-shot results there are more trustworthy.
   - Candidates: chat hybrid retrieval, trace filter (`prompts/trace_filter`), and the pending "Phase 3 reranking" for contextual retrieval.
3. **Chat tool-group selection.** `select_chat_tools()` currently picks tool groups by keyword. One `noul` question per group would make it multi-label and semantic, at millisecond cost.
4. **Natural-language processing-rule conditions.** For example, "if the email is a customer complaint" could be evaluated as a `noul`. It is zero-shot and cheap, but the label-bias issue (#156) needs care.
5. **Context-grouping pre-screen.** A cheap pass that proposes which card pairs belong together, before the LLM grouping step. Its value is lower, because each comparison is long and pairwise.

---

## 8. The competing option: do we need LDM at all?

We already compute **nomic-embed-text-v1.5** embeddings per card (ChromaDB). A logistic-regression or kNN head on those embeddings would:
- train on the same `router_output` history plus corrections, which is the same distillation benefit, and
- need no new model, no torch in the bundle, no naming problem, and no upstream churn.

It also has natural "unsure → send to the LLM" behaviour through neighbour agreement.

LDM's advantages over it:
- label definitions at the time you ask (zero-shot flexibility)
- ordinal priority scoring
- a built-in escalation head

**If distillation is going to happen either way, the embedding head is the cheaper baseline to beat.**

---

## 9. Proposed next step (only if we decide to explore): offline evaluation spike

This follows the "data-first, investigate before designing" feedback. No production code changes.

1. **Measure inputs.** Use a read-only script over `~/.laya/data` SQLite (`events`, `action_cards`, `audit_log`):
   - body token distribution per platform, before and after HTML and quoted-text stripping
   - router token and cost share of all per-event calls
   - correction rate per field
2. **Build the eval set.** Take N events with their stored `router_output`. Use corrected cards as gold, split by platform.
3. **Run candidates against the LLM router and against corrections**, for each field (persona, priority, category, requires_research):
   - (a) LDM zero-shot, with 48-token label descriptions
   - (b) LDM head fine-tuned on router history
   - (c) nomic-embedding logistic regression or kNN
   - Measure agreement, per-class F1, ordinal error for priority, and calibration (ECE) after temperature fitting.
   - Also measure how many events would escalate at a given error target.
4. **Measure cost:** latency on MPS and CPU, RAM use, bundle size of torch vs ONNX.
5. **Decide:** replace, two-tier, gate only (§7.1), embedding head instead, or drop the idea.

Scripts would live in the scratchpad or `engine/scripts/` as a spike. Nothing goes into the pipeline until step 5.

## 10. Questions to discuss

- Is the goal **cost**, **local-mode reliability**, or **latency**? The answer changes the recommendation. Local-mode reliability favours LDM or an embedding head most.
- Would it be acceptable to move **entity extraction** into the stager and fill part of it directly from event data?
- Is it acceptable that learned NL classification rules only apply on the escalated path?
- Are we open to a torch/onnxruntime ML tier in the shipped app, or should this stay opt-in like `requirements-ml.txt`?
- Should we look at the noise gate (§7.1) first, since it is lower risk and higher return?
