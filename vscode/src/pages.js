// @ts-check
// A feature's plan, report and e2e results: HTML pages a model wrote, which the hub serves. They
// open in a webview with the hub's sandbox policy (no scripts, no network). E2E results can be
// tens of MB of screenshots, so pages are read again only on Refresh, not after every change.
"use strict";

const vscode = require("vscode");

const HEAD_RE = /<head[^>]*>/i;

class Pages {
  constructor(/** @type {import("./review").Review} */ review) {
    this.review = review;
    /** @type {Map<string, vscode.WebviewPanel>} */
    this.panels = new Map();
  }

  /** Read every open page again. */
  refresh() {
    return Promise.all([...this.panels].map(([url, panel]) => this.fill(panel, url)));
  }

  async open(/** @type {import("./model").Part} */ part) {
    const feature = this.review.data?.feature;
    if (!feature) return;
    const open = this.panels.get(part.url);
    if (open) return open.reveal();
    const panel = vscode.window.createWebviewPanel(
      "devHubReview.page",
      `${part.label}: ${feature.title}`,
      vscode.ViewColumn.Active,
      { enableScripts: false, enableFindWidget: true, localResourceRoots: [] },
    );
    this.panels.set(part.url, panel);
    panel.onDidDispose(() => this.panels.delete(part.url));
    await this.fill(panel, part.url);
  }

  async fill(/** @type {vscode.WebviewPanel} */ panel, /** @type {string} */ url) {
    const policy = this.review.data?.feature?.content_policy ?? "default-src 'none'";
    const meta = `<meta http-equiv="Content-Security-Policy" content="${policy.replace(/"/g, "&quot;")}">`;
    let html;
    try {
      html = await this.review.hub.page(url);
    } catch (error) {
      html = `<p>${String(error instanceof Error ? error.message : error).replace(/</g, "&lt;")}</p>`;
    }
    panel.webview.html = HEAD_RE.test(html) ? html.replace(HEAD_RE, m => m + meta) : meta + html;
  }
}

module.exports = { Pages };
