/**
 * Harness 流式聊天客户端
 * - 优先 EventSource SSE
 * - 不支持时降级为 POST /api/chat
 * - HTML 转义防 XSS；停止按钮仅流式模式显示
 */
(function (global) {
  "use strict";

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function supportsEventSource() {
    return typeof global.EventSource === "function";
  }

  /**
   * @param {object} opts
   * @param {HTMLElement} opts.chatEl
   * @param {HTMLElement} opts.progressEl
   * @param {HTMLElement} opts.statusEl
   * @param {HTMLInputElement} opts.inputEl
   * @param {HTMLButtonElement} opts.sendBtn
   * @param {HTMLButtonElement} opts.stopBtn
   * @param {string} opts.csrfToken
   * @param {string} opts.streamUrl  e.g. /stream/chat
   * @param {string} opts.cancelUrl  e.g. /cancel
   * @param {string} opts.syncUrl    e.g. /api/chat
   * @param {number|null} opts.characterId
   * @param {string|null} opts.sessionId  cancel 用的 user token，如 user:1
   */
  function createStreamChat(opts) {
    var chat = opts.chatEl;
    var progress = opts.progressEl;
    var statusEl = opts.statusEl;
    var input = opts.inputEl;
    var sendBtn = opts.sendBtn;
    var stopBtn = opts.stopBtn;
    var csrfToken = opts.csrfToken;
    var streamUrl = opts.streamUrl;
    var cancelUrl = opts.cancelUrl;
    var syncUrl = opts.syncUrl;
    var characterId = opts.characterId || null;
    var sessionId = opts.sessionId || null;

    var es = null;
    var streaming = false;
    var useStream = supportsEventSource();

    if (stopBtn) {
      stopBtn.style.display = useStream ? "" : "none";
      stopBtn.disabled = true;
    }

    function addMsg(role, text) {
      var div = document.createElement("div");
      div.className = "msg " + role;
      div.textContent = text; // textContent 自动转义，防 XSS
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
      return div;
    }

    function setStreamingUi(active) {
      streaming = active;
      sendBtn.disabled = active;
      if (stopBtn) {
        if (useStream) {
          stopBtn.disabled = !active;
          stopBtn.style.display = "";
        } else {
          // 同步降级：始终隐藏停止按钮
          stopBtn.style.display = "none";
          stopBtn.disabled = true;
        }
      }
      if (!active && progress) progress.textContent = "";
    }

    function closeEventSource() {
      if (es) {
        try {
          es.close();
        } catch (e) {}
        es = null;
      }
    }

    function appendFacts(reply, data) {
      var out = reply || "";
      if (data.new_facts && data.new_facts.length) {
        out += "\n\n[新记忆] " + data.new_facts.join(" | ");
      }
      if (data.arc_changes && data.arc_changes.length) {
        out += "\n\n[弧光] " + data.arc_changes.join(" | ");
      }
      return out;
    }

    async function sendSync(text) {
      if (progress) progress.textContent = "正在生成回复…";
      setStreamingUi(true);
      try {
        var res = await fetch(syncUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ message: text }),
        });
        var data = await res.json();
        if (data.error && !data.response) {
          addMsg("bot", data.error);
        } else {
          addMsg("bot", appendFacts(data.response || "", data));
          if (data.status && statusEl) statusEl.textContent = data.status;
        }
      } catch (e) {
        addMsg("bot", "[网络错误] " + e.message);
      }
      setStreamingUi(false);
    }

    function sendStream(text) {
      if (progress) progress.textContent = "正在流式生成…";
      setStreamingUi(true);
      closeEventSource();

      var botDiv = addMsg("bot", "");
      var accumulated = "";

      var params = new URLSearchParams();
      params.set("message", text);
      if (characterId != null) params.set("character_id", String(characterId));

      var url = streamUrl + (streamUrl.indexOf("?") >= 0 ? "&" : "?") + params.toString();
      es = new EventSource(url);

      function finishPartial(label) {
        if (!accumulated) botDiv.textContent = label || "";
        else botDiv.textContent = accumulated;
        closeEventSource();
        setStreamingUi(false);
      }

      es.addEventListener("message", function (ev) {
        try {
          var data = JSON.parse(ev.data);
          var token = data.token || "";
          if (token) {
            accumulated += token;
            botDiv.textContent = accumulated;
            chat.scrollTop = chat.scrollHeight;
          }
        } catch (e) {}
      });

      es.addEventListener("done", function (ev) {
        try {
          var data = JSON.parse(ev.data);
          accumulated = data.response != null ? data.response : accumulated;
          botDiv.textContent = appendFacts(accumulated, data);
          if (data.status && statusEl) statusEl.textContent = data.status;
        } catch (e) {
          botDiv.textContent = accumulated;
        }
        closeEventSource();
        setStreamingUi(false);
      });

      es.addEventListener("cancelled", function (ev) {
        try {
          var data = JSON.parse(ev.data);
          if (data.response) accumulated = data.response;
        } catch (e) {}
        finishPartial(accumulated || "（已停止）");
      });

      es.addEventListener("error", function (ev) {
        var msg = "连接错误";
        try {
          if (ev.data) {
            var data = JSON.parse(ev.data);
            msg = data.message || msg;
          }
        } catch (e) {}
        if (!accumulated) botDiv.textContent = "[错误] " + msg;
        else botDiv.textContent = accumulated;
        closeEventSource();
        setStreamingUi(false);
      });

      es.onerror = function () {
        if (!es) return;
        if (!accumulated) botDiv.textContent = "[错误] 流式连接中断";
        closeEventSource();
        setStreamingUi(false);
      };
    }

    async function cancel() {
      if (!useStream || !streaming) return;
      try {
        await fetch(cancelUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ session_id: sessionId }),
        });
      } catch (e) {}
      closeEventSource();
    }

    function send() {
      var text = (input.value || "").trim();
      if (!text || streaming) return;
      input.value = "";
      addMsg("user", text);
      if (useStream) sendStream(text);
      else sendSync(text);
    }

    sendBtn.addEventListener("click", send);
    if (stopBtn) stopBtn.addEventListener("click", cancel);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") send();
    });

    return {
      send: send,
      cancel: cancel,
      escapeHtml: escapeHtml,
      supportsStream: useStream,
    };
  }

  global.HarnessStreamChat = {
    create: createStreamChat,
    escapeHtml: escapeHtml,
    supportsEventSource: supportsEventSource,
  };
})(typeof window !== "undefined" ? window : this);
