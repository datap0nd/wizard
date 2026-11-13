# 2026-11-13 — Wizard makes presentations: the person chooses the story, Wizard makes the deck

**Owner:** project owner. **Status:** decided (13 November 2026).

**Context.** The owner: "Wizard should be able to make complete powerpoint presentations, start to finish. Check what's
the best possible implementation of this … I digested all our presentations and created a design.md", then
"powerpoints are all about storyline. Storyline should be a question that wizard asks so that people can tell what
story they want to tell … make it so that the output can be analysis, powerpoint … something they can toggle after they
click on output type at the bottom … if they finish an analysis, asking to turn this into a powerpoint will do that",
and "after doing the first powerpoint, any changes can be requested in the chat easily". Until now a visual could be
downloaded as one PowerPoint slide ([decision](2026-11-09-heatmaps-and-visual-exports.md)); nothing made a deck.

**Options weighed.**
- *PowerPoint itself, through COM, filling the company template.* The truest look on the work PC, but only there:
  nothing to preview in the page, nothing to test in CI, and the template's layouts would decide what a slide can hold.
- *python-pptx on the service.* A good library, but it brings native modules (lxml, Pillow) that Application Control
  may block on the work PCs (decision 2026-10-02-dependencies), and the page would still need its own preview.
- *Gemini writes the slides as code.* Fast to start, but every deck would look different and none would be checked.
- **Chosen: Gemini plans the deck as structured slides; Wizard lays them out once and draws that layout twice** — in
  the page as the preview, and into the .pptx with pptxgenjs (already used for single-slide exports): native text,
  tables and editable charts whose data opens in Excel. What the person sees is what they download.

**Decision.**
- **Output** at the bottom of the composer: *Analysis* (the answer in the chat) or *PowerPoint*. It is kept per
  conversation like the systems picker and sent with the question (`output`); the request then tells Gemini to make a
  deck. Asking for a deck, slides or a PowerPoint in words ("turn this into a PowerPoint") does the same, and
  **Make a PowerPoint** under a finished analysis asks it with one click.
- **The storyline is the person's.** Before the deck, Gemini proposes two to four storylines the evidence supports, each
  a message and its arc (`wizard_propose_storylines`). They are a card under the answer; the one clicked, or a story the
  person writes, is the next question. It ends the turn and counts as Gemini's one question of the request, so it is
  never offered where nobody waits (a task, a mapping round, Check my data, the prompt queue: there Gemini chooses and
  says so). A deck from an analysis already in the conversation proposes its storylines from that analysis, without new
  reads.
- **The deck** (`wizard_make_presentation`) is slides of twelve kinds — cover, agenda, section, executive summary, key
  figures, numbered cards, chart, table, two panels, a grid of two to four panels, text, closing — that show the conversation's visuals by id and
  cite its evidence. The tool refuses what the page cannot draw (an unknown visual, a table shown as a chart, a stacked
  chart of one series, highlights on cells that do not exist, empty slides) and warns about what the company's slides
  avoid (long titles, too many bullets, too many shaded cells, figures without evidence). A deck keeps copies of the
  visuals it shows and the names of the sources it cites, so every slide states its unit and its source line, and a
  SYNTHETIC deck says so on every slide. The agenda lists the section slides with their pages by itself.
- **Dense slides, no empty space** (owner, the same day, on the first sample: "so minimalistic and have so much empty
  space … against empty space"). Points with a bold lead-in become a grid of rows (the lead in a label column, the
  detail beside it, rules between rows) that fills the slide down to the footer, and the text grows up to 30% where
  room is left; a chart or table with points gets a full-height **Key takeaways** column; cards and tables reach the
  bottom; figures sit above their analysis; a **grid** slide puts two to four panels (a chart and/or points each) on one
  slide. The tool warns about every thin slide — a chart or table with fewer than three takeaways, a text or closing
  slide under four points, a summary under three, figures without analysis, cards under three bullets, a panel under
  three points, a section divider in a deck of twelve slides or fewer — and the prompt tells Gemini to fix them and to
  prefer fewer, fuller slides.
- **Changes in the chat.** `wizard_change_presentation` updates, inserts, deletes or moves slides, or retitles the deck,
  and keeps the result as a new version (D2 revises D1); `wizard_read_presentation` returns slides in full. Each later
  request lists the conversation's decks slide by slide, so "make slide 4 a table" finds its slide.
- **The company's look comes from the knowledge base, never from this repository.** `presentation-look` carries it as
  design tokens (fonts, colors, point sizes, slide size, cover, footer label; knowledge standard section 12), written by
  the presentation-guide task from the company's decks or a written guide such as the owner's design.md, and read each
  time a deck is made. Without them Wizard draws its own neutral design and says so on the deck. A wrong value is left
  out with a reason; the deck is still made.
- **In the file.** One .pptx per deck, 16:9 unless the tokens say otherwise; titles, text and the East Asian font as
  the tokens say (also in the theme, so Korean text and new slides use them); charts native and editable (columns,
  stacked, 100% stacked, bars, lines with markers, scatter), tables native with their shading; speaker notes with what
  to say and the sources. **Download PowerPoint** saves it in Downloads where Wizard runs on the person's PC (then
  **Open**), as other exports do; elsewhere the browser downloads it.
- **What does not change.** A deck writes nothing to a company system and reads nothing new: it is built from the
  evidence and visuals Gemini already has, with the same data labels. No template or company value is committed here.

**Evidence.** `tests/unit/test_presentations.py` (the tools' checks and warnings, versions, the design tokens and their
problems, the storyline asked once and only where someone waits, the Output reaching the prompt, the deck listed in
later prompts, run events and the API); `apps/web/src/deck/deck.test.ts` (every slide kind inside the slide, sources
and data label, the agenda's pages, highlights, chart styles, and the .pptx: native stacked chart, table shading, notes,
the East Asian font, one set of paragraph settings per paragraph, 16:9 and 4:3);
`apps/web/src/components/DeckCard.test.tsx` (preview, moving between slides, Download and Open, storylines, the Output
picker). A sample deck was opened in LibreOffice and rendered slide by slide; the first real deck in PowerPoint is on
the work PC.
