// collector.js: gathers the signals the VA can't see and posts them to the
// detection service. Loaded on the demo page before the Netomi widget.
//
// What it sends:
// - one "load" event as soon as the page opens, with environment flags;
// - on every message send, a batch of everything since the previous send:
//   each key down/up, any paste, one mouse summary, and the "send" event.
//
// Batching at send time keeps the service to two requests per turn, and the
// whole batch arrives before the VA's check_session call for that turn.

(function () {
  "use strict";

  const SERVICE_URL = "http://localhost:8000/telemetry";
  const WIDGET_IFRAME_ID = "netomiChatWindow";
  const MESSAGE_BOX_SELECTOR = "textarea.custom-textarea";
  const SEND_BUTTON_SELECTOR = "button.chat-input-box-btn";
  // The widget builds its iframe after the page loads, so keep looking for it.
  const ATTACH_POLL_MS = 500;

  const sessionId = crypto.randomUUID();
  window.detectSessionId = sessionId;

  // ?label=human marks a recorded human baseline session.
  const pageParams = new URLSearchParams(window.location.search);
  const label = pageParams.get("label");

  let pendingEvents = [];
  let mouseMoves = 0;
  let mouseDistancePx = 0;
  let lastMouseX = null;
  let lastMouseY = null;

  function nowMs() {
    return Math.round(performance.now());
  }

  function makeEvent(kind, detail) {
    return { session_id: sessionId, kind: kind, t_ms: nowMs(), detail: detail };
  }

  function postEvents(events) {
    // keepalive lets the request finish even if the page is closing.
    fetch(SERVICE_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: events }),
      keepalive: true,
    }).catch(function (error) {
      console.warn("collector: telemetry post failed", error);
    });
  }

  function environmentFlags() {
    return {
      label: label,
      webdriver: navigator.webdriver === true,
      user_agent: navigator.userAgent,
      plugins_count: navigator.plugins.length,
      languages: Array.from(navigator.languages || []),
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
    };
  }

  // Only the kind of key is kept, never the character itself: timing and
  // corrections are what the checks need, and testers' text stays private.
  function keyCategory(key) {
    if (key === "Backspace" || key === "Delete" || key === "Enter") {
      return key;
    }
    if (key.length === 1) {
      return "char";
    }
    return "other";
  }

  // Elements inside the iframe come from the iframe's own window, so
  // `instanceof Element` (this page's Element) is false for them.
  // nodeType works across windows.
  function isElement(target) {
    return target !== null && target.nodeType === Node.ELEMENT_NODE;
  }

  function isMessageBox(target) {
    return isElement(target) && target.matches(MESSAGE_BOX_SELECTOR);
  }

  function onMouseMove(event) {
    // Movement inside the iframe is in the iframe's coordinates, so a jump
    // between the page and the widget adds one large step; that's harmless
    // for a rough "did the mouse move before sending" summary.
    if (lastMouseX !== null) {
      const dx = event.screenX - lastMouseX;
      const dy = event.screenY - lastMouseY;
      mouseDistancePx = mouseDistancePx + Math.sqrt(dx * dx + dy * dy);
    }
    lastMouseX = event.screenX;
    lastMouseY = event.screenY;
    mouseMoves = mouseMoves + 1;
  }

  function recordSend(messageBox, via) {
    const messageLength = messageBox.value.trim().length;
    if (messageLength === 0) {
      return;
    }
    const mouseSummary = {
      moves: mouseMoves,
      distance_px: Math.round(mouseDistancePx),
    };
    pendingEvents.push(makeEvent("mouse", mouseSummary));
    pendingEvents.push(makeEvent("send", { length: messageLength, via: via }));

    postEvents(pendingEvents);
    pendingEvents = [];
    mouseMoves = 0;
    mouseDistancePx = 0;
  }

  function onKeyDown(event) {
    if (!isMessageBox(event.target)) {
      return;
    }
    const category = keyCategory(event.key);
    pendingEvents.push(makeEvent("key", { type: "down", key: category, repeat: event.repeat }));
    // Enter without Shift sends the message; the box still holds the text here.
    if (category === "Enter" && !event.shiftKey) {
      recordSend(event.target, "enter");
    }
  }

  function onKeyUp(event) {
    if (!isMessageBox(event.target)) {
      return;
    }
    pendingEvents.push(makeEvent("key", { type: "up", key: keyCategory(event.key) }));
  }

  function onPaste(event) {
    if (!isMessageBox(event.target)) {
      return;
    }
    const pastedText = event.clipboardData ? event.clipboardData.getData("text") : "";
    pendingEvents.push(makeEvent("paste", { length: pastedText.length }));
  }

  function onPointerDown(event) {
    if (!isElement(event.target)) {
      return;
    }
    const sendButton = event.target.closest(SEND_BUTTON_SELECTOR);
    if (sendButton === null) {
      return;
    }
    // Capture phase runs before the widget's own handler clears the box.
    const messageBox = sendButton.ownerDocument.querySelector(MESSAGE_BOX_SELECTOR);
    if (messageBox !== null) {
      recordSend(messageBox, "button");
    }
  }

  // The chat window is a same-origin iframe (no src; the widget writes its
  // document), so its keystrokes never reach this page's document. Listeners
  // go on the iframe's document, and are re-added if the widget replaces it.
  function attachToWidget() {
    const iframe = document.getElementById(WIDGET_IFRAME_ID);
    if (iframe === null) {
      return;
    }
    const widgetDocument = iframe.contentDocument;
    if (widgetDocument === null || widgetDocument.collectorAttached) {
      return;
    }
    widgetDocument.addEventListener("keydown", onKeyDown, true);
    widgetDocument.addEventListener("keyup", onKeyUp, true);
    widgetDocument.addEventListener("paste", onPaste, true);
    widgetDocument.addEventListener("pointerdown", onPointerDown, true);
    widgetDocument.addEventListener("mousemove", onMouseMove, true);
    widgetDocument.collectorAttached = true;
  }

  document.addEventListener("mousemove", onMouseMove, true);
  postEvents([makeEvent("load", environmentFlags())]);
  setInterval(attachToWidget, ATTACH_POLL_MS);
})();
