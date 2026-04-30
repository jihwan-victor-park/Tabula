"use strict";

/**
 * WhatsApp Bridge — port 8007 (same as the clawbot it replaces).
 *
 * Exposes:
 *   POST /message/send   { recipient, message }  →  { sent, error }
 *   GET  /health                                  →  { ok }
 *
 * Also listens for inbound WhatsApp messages from WATCH_NUMBERS and
 * POSTs them to UNIVERSAL_AGENT_URL as:
 *   { message, business_name, location, recipient }
 *
 * Usage:
 *   WATCH_NUMBERS=+18584019272 \
 *   BUSINESS_NAME="Your Store" \
 *   node server.js
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const express = require("express");
const http = require("http");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const PORT = parseInt(process.env.PORT || "8007", 10);
const UNIVERSAL_AGENT_URL =
  process.env.UNIVERSAL_AGENT_URL || "http://localhost:8006/ask";
const BUSINESS_NAME = process.env.BUSINESS_NAME || "My Store";
const BUSINESS_LOCATION = process.env.BUSINESS_LOCATION || "US";
const WATCH_NUMBERS = (process.env.WATCH_NUMBERS || "")
  .split(",")
  .map((n) => n.trim())
  .filter(Boolean)
  .map(normalizeNumber);

function normalizeNumber(n) {
  return n.replace(/\D/g, "").slice(-10);
}

function toWhatsAppId(recipient) {
  // Accept "+18584019272", "18584019272", or already "18584019272@c.us"
  if (recipient.endsWith("@c.us")) return recipient;
  return recipient.replace(/\D/g, "") + "@c.us";
}

function senderMatchesWatched(from) {
  if (WATCH_NUMBERS.length === 0) return true; // watch everyone if unfiltered
  const norm = normalizeNumber(from.replace("@c.us", ""));
  return WATCH_NUMBERS.some((w) => norm === w || norm.endsWith(w) || w.endsWith(norm));
}

// ---------------------------------------------------------------------------
// WhatsApp client
// ---------------------------------------------------------------------------
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: { args: ["--no-sandbox"] },
});

client.on("qr", (qr) => {
  console.log("\nScan this QR code with WhatsApp on your phone:\n");
  qrcode.generate(qr, { small: true });
});

client.on("ready", () => {
  console.log("[whatsapp] Client ready. Watching:", WATCH_NUMBERS);
});

client.on("auth_failure", (msg) => {
  console.error("[whatsapp] Auth failure:", msg);
});

client.on("message", async (msg) => {
  if (msg.fromMe) return; // ignore our own outbound messages
  const sender = msg.from; // e.g. "18584019272@c.us"
  const text = msg.body;

  if (!senderMatchesWatched(sender)) return;

  console.log(`[inbox] ${sender}: ${text}`);

  const payload = JSON.stringify({
    message: text,
    business_name: BUSINESS_NAME,
    location: BUSINESS_LOCATION,
    recipient: sender,
  });

  const url = new URL(UNIVERSAL_AGENT_URL);
  const options = {
    hostname: url.hostname,
    port: url.port || 80,
    path: url.pathname,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(payload),
    },
  };

  const req = http.request(options, (res) => {
    console.log(`[inbox] Forwarded → ${res.statusCode}`);
  });
  req.on("error", (e) => console.error("[inbox] Forward failed:", e.message));
  req.write(payload);
  req.end();
});

client.initialize();

// ---------------------------------------------------------------------------
// HTTP API
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({ ok: true }));

app.post("/message/send", async (req, res) => {
  const { recipient, message } = req.body || {};
  if (!recipient || !message) {
    return res.status(400).json({ sent: false, error: "recipient and message required" });
  }
  try {
    const chatId = toWhatsAppId(recipient);
    await client.sendMessage(chatId, message);
    console.log(`[send] → ${chatId}: ${message.slice(0, 60)}`);
    res.json({ sent: true, error: null });
  } catch (err) {
    console.error("[send] Failed:", err.message);
    res.status(500).json({ sent: false, error: err.message });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`WhatsApp bridge listening on http://127.0.0.1:${PORT}`);
});
