/** Messages between the page and WizardBar, the Windows app that shows it in a WebView2 panel. In a normal browser
 * there is no host and every call does nothing. */
export type ToHost =
  | {type: 'busy'; busy: boolean}
  | {type: 'finished'; runId: string; question: string; ok: boolean}
  | {type: 'hide'}
  | {type: 'update'};
export type FromHost = {type: 'focus'} | {type: 'open-settings'};

interface WebViewBridge {
  postMessage(message: unknown): void;
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

/** Listen for host messages; returns the unsubscribe function. */
export function onHost(listener: (message: FromHost) => void): () => void {
  const host = bridge();
  if (!host) return () => undefined;
  const handler = (event: MessageEvent) => {
    const data = event.data as {type?: unknown} | null;
    if (data && (data.type === 'focus' || data.type === 'open-settings')) listener({type: data.type});
  };
  host.addEventListener('message', handler);
  return () => host.removeEventListener('message', handler);
}
