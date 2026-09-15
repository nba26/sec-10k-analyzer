"""Stylesheet and the landing hero, kept out of app.py so the app reads clean."""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');

:root {
  --ink:      #0B0F14;
  --surface:  #131A24;
  --raised:   #18212D;
  --line:     rgba(232,177,76,0.16);
  --hair:     rgba(230,237,243,0.09);
  --gold:     #E8B14C;
  --text:     #E6EDF3;
  --muted:    #7D8B99;
  --serif:    'Instrument Serif', Georgia, serif;
  --sans:     'Inter', -apple-system, system-ui, sans-serif;
  --mono:     'IBM Plex Mono', ui-monospace, Menlo, monospace;
}

html, body, [class*="css"] { font-family: var(--sans); }

.block-container { padding-top: 2.2rem; padding-bottom: 8rem; max-width: 62rem; }
#MainMenu, footer, header { visibility: hidden; }

h1, h2, h3 { font-family: var(--serif) !important; font-weight: 400 !important;
             letter-spacing: -0.01em; }

/* ---------- shared bits ---------- */
.eyebrow {
  font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--gold); opacity: 0.9;
  margin-bottom: 0.9rem;
}
.rule { height: 1px; background: var(--hair); margin: 2.2rem 0 1.8rem 0; }

.chip {
  display: inline-block; font-family: var(--mono); font-size: 0.7rem;
  padding: 4px 11px; margin: 0 6px 6px 0; border-radius: 3px;
  border: 1px solid var(--line); color: var(--gold); background: rgba(232,177,76,0.05);
}

/* ---------- landing hero ---------- */
.hero h1 {
  font-family: var(--serif); font-size: 4.1rem; line-height: 0.98;
  margin: 0 0 1.1rem 0; color: var(--text); letter-spacing: -0.02em;
}
.hero h1 em { font-style: italic; color: var(--gold); }
.hero p.lede {
  font-size: 1.06rem; line-height: 1.6; color: var(--muted);
  max-width: 34rem; margin: 0;
}

.steps { display: flex; gap: 0.9rem; margin: 0.4rem 0 0 0; flex-wrap: wrap; }
.step {
  flex: 1 1 0; min-width: 12rem; background: var(--surface);
  border: 1px solid var(--hair); border-radius: 10px; padding: 1.15rem 1.2rem;
}
.step .n {
  font-family: var(--mono); font-size: 0.68rem; color: var(--gold);
  letter-spacing: 0.14em; margin-bottom: 0.55rem;
}
.step .t { font-size: 0.95rem; font-weight: 600; color: var(--text);
           margin-bottom: 0.3rem; }
.step .d { font-size: 0.83rem; line-height: 1.5; color: var(--muted); }

.pullquote {
  border-left: 2px solid var(--gold); padding: 0.1rem 0 0.1rem 1rem;
  font-family: var(--serif); font-size: 1.15rem; font-style: italic;
  color: var(--text); opacity: 0.9; margin: 0;
}

/* ---------- company header ---------- */
.topline { display: flex; align-items: baseline; gap: 0.8rem; flex-wrap: wrap; }
.topline h2 { font-size: 2.1rem; margin: 0; color: var(--text); }
.tick {
  font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.1em;
  padding: 4px 10px; border-radius: 3px; border: 1px solid var(--line);
  color: var(--gold);
}
.docket {
  display: flex; gap: 2.1rem; flex-wrap: wrap; margin: 1rem 0 1.5rem 0;
  padding: 0.85rem 0; border-top: 1px solid var(--hair);
  border-bottom: 1px solid var(--hair);
}
.dk { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.16em;
      text-transform: uppercase; color: var(--muted); }
.dv { font-family: var(--mono); font-size: 1.02rem; color: var(--text);
      margin-top: 0.2rem; }

.section-note {
  font-family: var(--mono); font-size: 0.72rem; color: var(--muted);
  margin: 0.6rem 0 1rem 0; padding-left: 0.75rem;
  border-left: 2px solid var(--line);
}
.section-note code { color: var(--gold); background: transparent; font-size: 0.72rem; }

/* ---------- chat ---------- */
[data-testid="stChatMessage"] { background: transparent; padding: 0.15rem 0;
                                gap: 0.75rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  flex-direction: row-reverse; margin: 1.4rem 0 0.4rem auto;
  max-width: 76%; width: fit-content;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
  [data-testid="stChatMessageContent"] {
  background: var(--raised); border: 1px solid var(--hair);
  border-radius: 14px 14px 3px 14px; padding: 0.6rem 1rem;
}
[data-testid="stChatMessageAvatarUser"] { display: none; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  margin: 0.2rem 0 1.6rem 0;
}
[data-testid="stChatMessageAvatarAssistant"] {
  background: transparent; border: 1px solid var(--line); color: var(--gold);
}

.cites { margin-top: 0.6rem; }
.cite {
  display: inline-block; font-family: var(--mono); font-size: 0.66rem;
  padding: 2px 8px; margin: 0 5px 5px 0; border-radius: 3px;
  border: 1px solid var(--line); color: var(--gold); opacity: 0.85;
}
.nosrc { font-family: var(--mono); font-size: 0.68rem; color: var(--muted);
         opacity: 0.6; margin-top: 0.55rem; }

/* ---------- controls ---------- */
.stButton > button { border-radius: 7px; font-weight: 500; }
div[data-testid="column"] .stButton > button {
  min-height: 3.1rem; white-space: normal; line-height: 1.3; font-size: 0.85rem;
  background: var(--surface); border: 1px solid var(--hair); color: var(--text);
}
div[data-testid="column"] .stButton > button:hover {
  border-color: var(--line); color: var(--gold);
}
section[data-testid="stSidebar"] { border-right: 1px solid var(--hair); }
section[data-testid="stSidebar"] .stButton > button {
  text-align: left; justify-content: flex-start; font-size: 0.82rem;
  padding: 0.32rem 0.6rem; min-height: 0;
}
section[data-testid="stSidebar"] hr { margin: 0.9rem 0; border-color: var(--hair); }
.sidelabel {
  font-family: var(--mono); font-size: 0.64rem; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 0.55rem;
}
[data-testid="stExpander"] { border: 1px solid var(--hair); border-radius: 10px; }
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid var(--hair); }
.stTabs [data-baseweb="tab"] { font-size: 0.88rem; font-weight: 500;
                               padding: 8px 18px 10px 18px; }
[data-testid="stChatInput"] { border-color: var(--hair); }
</style>
"""

HERO = """
<div class="hero">
  <div class="eyebrow">Form 10-K &nbsp;·&nbsp; Annual Report</div>
  <h1>Read the filing,<br><em>not the press release.</em></h1>
  <p class="lede">Pulls a company's most recent annual report straight from SEC
  EDGAR, splits it along the lines Regulation S-K already draws, and answers
  questions using only what the document actually says.</p>
</div>

<div class="rule"></div>

<div class="steps">
  <div class="step">
    <div class="n">01 &nbsp;FETCH</div>
    <div class="t">Straight from EDGAR</div>
    <div class="d">Any filer, by ticker, name or CIK. The filing is downloaded
    and cached, so the second visit is instant.</div>
  </div>
  <div class="step">
    <div class="n">02 &nbsp;SEGMENT</div>
    <div class="t">Split by statutory item</div>
    <div class="d">Item numbers and titles are fixed by regulation. Matching both
    separates a real heading from a cross-reference.</div>
  </div>
  <div class="step">
    <div class="n">03 &nbsp;GROUND</div>
    <div class="t">Cited, or refused</div>
    <div class="d">Every answer names the item it came from. When the filing
    doesn't cover something, it says so.</div>
  </div>
</div>

<div class="rule"></div>

<div class="eyebrow">Items parsed</div>
<div>
  <span class="chip">Item 1 · Business</span>
  <span class="chip">Item 1A · Risk Factors</span>
  <span class="chip">Item 7 · MD&amp;A</span>
  <span class="chip">Item 8 · Financial Statements</span>
</div>

<div style="height:1.8rem"></div>
<p class="pullquote">Pick a filer in the sidebar to begin.</p>
"""