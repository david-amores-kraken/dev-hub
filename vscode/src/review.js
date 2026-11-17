// @ts-check
// The branch under review and what the hub last said about it. Everything else draws from here
// and redraws when it changes.
"use strict";

const vscode = require("vscode");
const { HubError } = require("./hub");

const BRANCH_KEY = "devHubReview.branch";

class Review {
  constructor(/** @type {import("./hub").Hub} */ hub, /** @type {vscode.Memento} */ state) {
    this.hub = hub;
    this.state = state;
    /** @type {import("./model").Branch | undefined} */
    this.data = undefined;
    /** @type {string | undefined} */
    this.error = undefined;
    /** @type {Promise<void>} */
    this.loading = Promise.resolve();
    this.loadedAt = 0;
    this.changed = new vscode.EventEmitter();
    /** Fires after each reload, whether it worked or not. */
    this.onDidChange = this.changed.event;
  }

  /** @returns {string | undefined} */
  get branch() {
    return this.state.get(BRANCH_KEY);
  }

  async setBranch(/** @type {string} */ branch) {
    await this.state.update(BRANCH_KEY, branch);
    this.data = undefined;
    await this.reload();
  }

  /** Ask the hub again. Calls made while one is running share it. */
  reload() {
    if (!this.pending) {
      this.pending = this.fetch().finally(() => {
        this.pending = undefined;
        this.loadedAt = Date.now();
        this.changed.fire(undefined);
      });
      this.loading = this.pending;
    }
    return this.pending;
  }

  /** Reload unless it was done in the last few seconds, as when the window gets focus. */
  reloadIfStale(/** @type {number} */ ms = 3000) {
    return Date.now() - this.loadedAt > ms ? this.reload() : this.loading;
  }

  async fetch() {
    const branch = this.branch;
    if (!branch) {
      this.data = this.error = undefined;
      return;
    }
    try {
      const data = await this.hub.get("/api/branch", { branch });
      if (branch !== this.branch) return; // another branch was picked meanwhile
      this.data = data;
      this.error = undefined;
    } catch (error) {
      this.error = error instanceof HubError ? error.message : String(error);
    }
  }

  /** Send a change to the hub, then reload so every view shows what it saved. A failure is shown
   * to the user and the views are left as they were. */
  async change(/** @type {string} */ path, /** @type {unknown} */ body = {}) {
    try {
      await this.hub.post(path, body);
      return true;
    } catch (error) {
      vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      await this.reload();
    }
  }
}

module.exports = { Review };
