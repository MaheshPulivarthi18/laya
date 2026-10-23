Evidence for aayushch/laya issue #6: persist tool-call references in chat
==========================================================================

Tested: 2026-10-23, macOS 26.5.2, Apple M4
Code:   branch feat/6-persist-tool-calls on top of laya main e5f1610
How:    engine (`python -m laya.main`) + UI (`npm run dev`) in a browser, the
        documented "Engine + UI in a plain browser" dev mode, with a fresh home
        directory. Chat model: openrouter/anthropic/claude-haiku-5.5, key passed to
        the engine process as OPENROUTER_API_KEY only (never stored).

BEFORE (laya main e5f1610, same question, same setup; all model roles on OpenRouter)
  BEFORE-01  the answer uses card data but shows no sign of which tools were used
  BEFORE-02  the database row has tool_calls_json (get_card_stats, ...), but the
             /chat/history response has no tool_calls field, so the UI can't show it

AFTER (this branch)
  AFTER-00  question sent: "Search my cards and give me card stats: what is open right now?"
  AFTER-01  finished answer shows "Get card stats · Search cards" above the reply
  AFTER-02  close-up of the labels
  AFTER-03  after reloading the page and reopening the conversation: labels still there
      (loaded from the DB via the history API, not from the live stream)
  AFTER-04  engine API /chat/history: assistant message has
      tool_calls = [get_card_stats, search_cards x4]; the UI shows each tool once.

Automated checks: engine pytest 1514 passed (4 new); UI vitest 290 passed (4 new);
svelte-check 0 errors 0 warnings.
