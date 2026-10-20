/** Messages between the page and WizardBar, the Windows app that shows it in a WebView2 panel. In a normal browser
 * there is no host and every call does nothing. */
export type ToHost =
  | {type: 'busy'; busy: boolean}
  | {type: 'finished'; runId: string; question: string; ok: boolean}
  | {type: 'hide'}
  | {type: 'update'}
  /** What the wizard acts out on the page (wizard.ts), so the button at the top of the screen acts out the same. */
  | {type: 'activity'; animation: string};
/** A file dropped on the button (or on this page, through dropToHost): WizardBar has allowed Wizard to read it where
 * it is, and the page attaches it like "From this PC". `error` says why a file cannot be attached. */
export interface DroppedFile { path: string; name: string; error?: string }
export type FromHost = {type: 'focus'} | {type: 'open-settings'} | {type: 'attach'; files: DroppedFile[]};

interface WebViewBridge {
  postMessage(message: unknown): void;
  postMessageWithAdditionalObjects?(message: unknown, additionalObjects: ArrayLike<unknown>): void;
  addEventListener(type: 'message', listener: (event: MessageEvent) => void): void;
  removeEventListener(type: 'message', listener: (event: MessageEvent) => void): void;
}

function bridge(): WebViewBridge | null {
  return (window as unknown as {chrome?: {webview?: WebViewBridge}}).chrome?.webview ?? null;
}

export function inHost(): boolean {
  return bridge() !== null;
}

export function toHost(message: ToHost): void {
  bridge()?.postMessage(message);
}

/** Files dropped on the page, handed to WizardBar with their place on disk (WebView2 gives the host the path), so
 * Wizard reads the original as From this PC does: protected files open only there. False outside WizardBar, or in a
 * WebView2 too old for it: then the page uploads the files instead. */
export function dropToHost(files: File[]): boolean {
  const host = bridge();
  if (!host?.postMessageWithAdditionalObjects || !files.length) return false;
  try {
    host.postMessageWithAdditionalObjects({type: 'drop'}, files);
    return true;
  } catch {
    return false;
  }
}

function dropped(value: unknown): DroppedFile[] {
  if (!Array.isArray(value)) return [];
  return value.filter((f): f is DroppedFile => !!f && typeof f === 'object' && typeof (f as DroppedFile).path === 'string'
    && typeof (f as DroppedFile).name === 'string').slice(0, 5);
}

/** Listen for host messages; returns the unsubscribe function. */
export function onHost(listener: (message: FromHost) => void): () => void {
  const host = bridge();
  if (!host) return () => undefined;
  const handler = (event: MessageEvent) => {
    const data = event.data as {type?: unknown; files?: unknown} | null;
    if (data && (data.type === 'focus' || data.type === 'open-settings')) listener({type: data.type});
    if (data?.type === 'attach') listener({type: 'attach', files: dropped(data.files)});
  };
  host.addEventListener('message', handler);
  return () => host.removeEventListener('message', handler);
}
