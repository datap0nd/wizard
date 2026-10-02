/** Turn Gemini's plain-text references into renderable markers before Markdown parsing:
 *  - a line that is only "[V1]" becomes a fenced block rendered as that visual
 *  - inline "[E3]" / "[V1]" become anchors (#evidence-E3 / #visual-V1) rendered as chips.
 *  Raw HTML in model output is never rendered (react-markdown escapes it). */
export function prepareAnswer(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let fenced = false;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) { fenced = !fenced; out.push(line); continue; }
    if (fenced) { out.push(line); continue; }
    const visual = line.trim().match(/^\[(V\d{1,4})\]$/);
    if (visual) { out.push('', '```wizard-visual', visual[1], '```', ''); continue; }
    out.push(line.replace(/\[(E\d{1,4}|V\d{1,4})\](?!\()/g, (_, id: string) => `[${id}](#${id.startsWith('E') ? 'evidence' : 'visual'}-${id})`));
  }
  return out.join('\n');
}

export function placedVisuals(markdown: string): Set<string> {
  return new Set(Array.from(markdown.matchAll(/^\s*\[(V\d{1,4})\]\s*$/gm), m => m[1]));
}

export function citedEvidence(markdown: string): string[] {
  return Array.from(new Set(Array.from(markdown.matchAll(/\[(E\d{1,4})\]/g), m => m[1])));
}
