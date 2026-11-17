// @ts-check
// Talk to the dev hub. It does all the work: this only sends requests and reads the answers.
"use strict";

const TIMEOUT_MS = 20_000;

/** The hub isn't running, or it answered with an error. `message` says which, for the user. */
class HubError extends Error {}

class Hub {
  /** @param {() => string} url  the hub's address, read each time so a settings change applies */
  constructor(url) {
    this.url = url;
  }

  /** @returns {Promise<any>} */
  get(/** @type {string} */ path, /** @type {Record<string, string>} */ params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.send(query ? `${path}?${query}` : path, {}, "json");
  }

  /** A change, sent as the hub's own pages send it: JSON, from the hub's own origin. The hub
   * refuses any other POST, so a web page can't make one. @returns {Promise<any>} */
  post(/** @type {string} */ path, /** @type {unknown} */ body = {}) {
    return this.send(
      path,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: new URL(this.url()).origin },
        body: JSON.stringify(body),
      },
      "json",
    );
  }

  /** A page, such as a plan. @returns {Promise<string>} */
  page(/** @type {string} */ path) {
    return this.send(path, {}, "text");
  }

  /** The address of one of the hub's pages, to open in the browser. */
  link(/** @type {string} */ path) {
    return new URL(path, this.url()).toString();
  }

  async send(/** @type {string} */ path, /** @type {RequestInit} */ init, /** @type {"json" | "text"} */ as) {
    const url = this.link(path);
    let response;
    try {
      response = await fetch(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
    } catch {
      throw new HubError(`Can't reach the dev hub at ${this.url()}. Is it running?`);
    }
    if (!response.ok) {
      const error = await response
        .json()
        .then(body => body?.error)
        .catch(() => undefined);
      throw new HubError(`The dev hub said ${response.status}${error ? `: ${error}` : ""} (${init.method ?? "GET"} ${path}).`);
    }
    return as === "json" ? response.json() : response.text();
  }
}

module.exports = { Hub, HubError };
