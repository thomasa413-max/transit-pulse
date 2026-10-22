// Worker unit tests: node --test tests/worker.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickLang, signToken, verifyToken, timingSafeEqual, bucketOf, summariseVitals, validComment, clean, refererHost } from "../src/worker.js";

const req = (headers) => new Request("https://x.test/", { headers });
const SECRET = "s".repeat(40);

test("language: cookie first, then browser, then French", () => {
  assert.equal(pickLang(req({ Cookie: "a=1; lang=it" })), "it");
  assert.equal(pickLang(req({ Cookie: "lang=xx", "Accept-Language": "de-CH,de;q=0.9,en;q=0.8" })), "de");
  assert.equal(pickLang(req({ "Accept-Language": "es-ES,en;q=0.5" })), "en");
  assert.equal(pickLang(req({ "Accept-Language": "ja" })), "fr");
  assert.equal(pickLang(req({})), "fr");
});

test("signed tokens: valid, expired, tampered, wrong context, weak secret", async () => {
  const tok = await signToken(SECRET, "admin", 60);
  assert.equal(await verifyToken(SECRET, "admin", tok), true);
  assert.equal(await verifyToken(SECRET, "human", tok), false, "purpose is bound");
  assert.equal(await verifyToken(SECRET, "admin", tok.replace(/.$/, (c) => (c === "0" ? "1" : "0"))), false);
  const old = await signToken(SECRET, "admin", 60, "", Date.now() - 3600_000);
  assert.equal(await verifyToken(SECRET, "admin", old), false, "expired");
  const bound = await signToken(SECRET, "human", 60, "ipA");
  assert.equal(await verifyToken(SECRET, "human", bound, "ipA"), true);
  assert.equal(await verifyToken(SECRET, "human", bound, "ipB"), false, "bound to the visitor");
  assert.equal(await verifyToken("short", "admin", await signToken("short", "admin", 60)), false, "weak secret refused");
  assert.equal(await verifyToken(SECRET, "admin", "garbage"), false);
  assert.equal(await verifyToken(SECRET, "admin", undefined), false);
});

test("constant-time compare", () => {
  assert.equal(timingSafeEqual("abc", "abc"), true);
  assert.equal(timingSafeEqual("abc", "abd"), false);
  assert.equal(timingSafeEqual("abc", "abcd"), false);
});

test("comment validation and cleaning", () => {
  assert.equal(validComment("A", "assez long pour passer le contrôle"), "name");
  assert.equal(validComment("Anna", "trop court"), "empty");
  assert.equal(validComment("Anna", "aaaaaaaaaaaaaaaaaaaaaaaaa"), "empty");
  assert.equal(validComment("Anna", "La ligne 7 était vraiment en retard ce soir."), null);
  assert.equal(validComment("Anna", "voir https://a.x https://b.x https://c.x pour plus de détails"), "links");
  assert.equal(clean("a‮b\u0000c\r\n\n\n\nd ", 100), "abc\n\nd");
  assert.equal(clean("x".repeat(50), 10).length, 10);
});

test("referrer host", () => {
  assert.equal(refererHost("", "site.ch"), "direct");
  assert.equal(refererHost("https://www.google.com/search?q=x", "site.ch"), "google.com");
  assert.equal(refererHost("https://site.ch/fr/", "site.ch"), null);
  assert.equal(refererHost("not a url", "site.ch"), "direct");
});

test("vitals buckets and p75", () => {
  assert.equal(bucketOf("LCP", 400), 0);
  assert.equal(bucketOf("LCP", 2500), 4);
  assert.equal(bucketOf("LCP", 99999), 10);
  const rows = [
    { metric: "LCP", device: "mobile", bucket: 2, n: 70 },  // ≤ 1.5 s
    { metric: "LCP", device: "mobile", bucket: 6, n: 20 },  // ≤ 4 s
    { metric: "LCP", device: "mobile", bucket: 8, n: 10 },  // ≤ 7 s
  ];
  const s = summariseVitals(rows)["LCP.mobile"];
  assert.equal(s.samples, 100);
  assert.equal(s.p75, 4000);
  assert.equal(s.good, 0.7);
  assert.equal(s.poor, 0.1);
});
