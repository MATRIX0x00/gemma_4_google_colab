const WS_URL = "ws://127.0.0.1:8765";
let socket = null;
let isConnected = false;
let lastActiveTabInfo = null;
let reconnectTimeout = null;
let reconnectDelay = 1500;
const MIN_RECONNECT_DELAY = 1500;
const MAX_RECONNECT_DELAY = 12000;

function log(...args) {
  console.log("[MatrixCode MCP Bridge]", ...args);
}

function notifyTabChange() {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs && tabs[0]) {
      lastActiveTabInfo = {
        id: tabs[0].id,
        title: tabs[0].title || "",
        url: tabs[0].url || ""
      };
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: "tab_update",
          activeTab: lastActiveTabInfo
        }));
      }
    }
  });
}

function connectWebSocket() {
  if (socket) {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      return;
    }
    try {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    } catch (e) {}
    socket = null;
  }

  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
  }

  try {
    socket = new WebSocket(WS_URL);
  } catch (err) {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    isConnected = true;
    reconnectDelay = MIN_RECONNECT_DELAY;
    log("Connected to MatrixCode Terminal Bridge!");
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs && tabs[0] ? { id: tabs[0].id, title: tabs[0].title, url: tabs[0].url } : null;
      lastActiveTabInfo = activeTab;
      try {
        socket.send(JSON.stringify({
          type: "client_hello",
          activeTab: activeTab
        }));
      } catch (e) {}
    });
  };

  socket.onmessage = async (event) => {
    try {
      const request = JSON.parse(event.data);
      if (request.type === "pong") return;

      log("Received command:", request);
      const result = await handleCommand(request);
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          id: request.id,
          success: true,
          result: result
        }));
      }
    } catch (err) {
      log("Command execution error:", err);
      try {
        const req = JSON.parse(event.data);
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            id: req.id || null,
            success: false,
            error: err.message || String(err)
          }));
        }
      } catch (e) {}
    }
  };

  socket.onclose = () => {
    isConnected = false;
    scheduleReconnect();
  };

  socket.onerror = () => {
    isConnected = false;
    try {
      socket.close();
    } catch (e) {}
  };
}

function scheduleReconnect() {
  if (reconnectTimeout) return;
  reconnectTimeout = setTimeout(() => {
    reconnectTimeout = null;
    reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY);
    connectWebSocket();
  }, reconnectDelay);
}

async function getTargetTab(preferredTabId) {
  if (preferredTabId) {
    try {
      const tab = await chrome.tabs.get(preferredTabId);
      if (tab) return tab;
    } catch (e) {}
  }
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs && tabs[0]) return tabs[0];
  const allTabs = await chrome.tabs.query({});
  return allTabs[0] || null;
}

async function handleCommand(request) {
  const { action, params = {} } = request;
  let tab = await getTargetTab(params.tabId);

  switch (action) {
    case "status": {
      const allTabs = await chrome.tabs.query({});
      return {
        connected: true,
        activeTab: tab ? { id: tab.id, title: tab.title, url: tab.url } : null,
        tabCount: allTabs.length
      };
    }

    case "navigate": {
      let targetUrl = (params.url || "").trim().replace(/^<|>$/g, "");
      if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://") && !targetUrl.startsWith("file://")) {
        targetUrl = "https://" + targetUrl;
      }
      if (tab) {
        await chrome.tabs.update(tab.id, { url: targetUrl });
      } else {
        tab = await chrome.tabs.create({ url: targetUrl });
      }

      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 4000);
        function onUpdated(updatedTabId, changeInfo) {
          if (updatedTabId === tab.id && changeInfo.status === "complete") {
            chrome.tabs.onUpdated.removeListener(onUpdated);
            clearTimeout(timer);
            setTimeout(resolve, 600);
          }
        }
        chrome.tabs.onUpdated.addListener(onUpdated);
      });

      const currentTab = await chrome.tabs.get(tab.id).catch(() => tab);
      notifyTabChange();
      return {
        message: `Navigated to ${targetUrl}`,
        title: currentTab?.title || "",
        url: currentTab?.url || targetUrl
      };
    }

    case "new_tab": {
      let targetUrl = (params.url || "https://google.com").trim().replace(/^<|>$/g, "");
      if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://") && !targetUrl.startsWith("file://")) {
        targetUrl = "https://" + targetUrl;
      }
      const createdTab = await chrome.tabs.create({ url: targetUrl });
      notifyTabChange();
      return {
        message: `Created tab ${createdTab.id}`,
        tabId: createdTab.id,
        url: targetUrl
      };
    }

    case "close_tab": {
      const targetTabId = params.tabId || (tab ? tab.id : null);
      if (!targetTabId) throw new Error("No tab specified to close");
      await chrome.tabs.remove(targetTabId);
      notifyTabChange();
      return { message: `Closed tab ${targetTabId}` };
    }

    case "switch_tab": {
      const targetTabId = Number(params.tabId);
      if (!targetTabId) throw new Error("tabId is required for switch_tab");
      const switchedTab = await chrome.tabs.update(targetTabId, { active: true });
      notifyTabChange();
      return { message: `Switched to tab ${targetTabId}`, title: switchedTab.title, url: switchedTab.url };
    }

    case "reload": {
      if (!tab) throw new Error("No active browser tab found");
      await chrome.tabs.reload(tab.id);
      return { message: "Tab reloaded", tabId: tab.id };
    }

    case "back": {
      if (!tab) throw new Error("No active browser tab found");
      await chrome.tabs.goBack(tab.id);
      return { message: "Navigated back", tabId: tab.id };
    }

    case "forward": {
      if (!tab) throw new Error("No active browser tab found");
      await chrome.tabs.goForward(tab.id);
      return { message: "Navigated forward", tabId: tab.id };
    }

    case "get_content": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector || "body";
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel) || document.body;
          return {
            url: window.location.href,
            title: document.title,
            innerText: el ? el.innerText.slice(0, 30000) : "",
            innerHTML: el ? el.innerHTML.slice(0, 45000) : ""
          };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "get_forms": {
      if (!tab) throw new Error("No active browser tab found");
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          function inspectInputs(root) {
            const fields = [];
            const elements = root.querySelectorAll("input, textarea, select, [contenteditable='true'], [role='textbox'], [role='combobox']");
            elements.forEach(node => {
              const rect = node.getBoundingClientRect();
              const visible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(node).visibility !== "hidden";
              let selector = "";
              if (node.id) selector = `#${node.id}`;
              else if (node.name) selector = `${node.tagName.toLowerCase()}[name='${node.name}']`;
              else if (node.placeholder) selector = `${node.tagName.toLowerCase()}[placeholder='${node.placeholder}']`;
              else if (node.className && typeof node.className === 'string') {
                const firstClass = node.className.trim().split(/\s+/)[0];
                if (firstClass) selector = `${node.tagName.toLowerCase()}.${firstClass}`;
              }
              if (!selector) selector = node.tagName.toLowerCase();

              let label = "";
              if (node.id) {
                const labelEl = document.querySelector(`label[for='${node.id}']`);
                if (labelEl) label = labelEl.innerText.trim();
              }
              if (!label && node.closest("label")) {
                label = node.closest("label").innerText.trim();
              }

              fields.push({
                tag: node.tagName.toLowerCase(),
                type: node.type || (node.isContentEditable ? "contenteditable" : "text"),
                name: node.name || null,
                id: node.id || null,
                label: label || null,
                placeholder: node.placeholder || null,
                value: node.value !== undefined ? String(node.value).slice(0, 100) : (node.innerText ? node.innerText.slice(0, 100) : ""),
                selector: selector,
                required: Boolean(node.required),
                disabled: Boolean(node.disabled),
                visible: visible,
                bounds: { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }
              });
            });
            return fields;
          }

          const forms = [];
          const formNodes = Array.from(document.querySelectorAll("form"));
          if (formNodes.length > 0) {
            formNodes.forEach((form, idx) => {
              const formId = form.id ? `#${form.id}` : (form.name ? `form[name='${form.name}']` : `form:nth-of-type(${idx + 1})`);
              const submits = Array.from(form.querySelectorAll("button, input[type='submit'], input[type='button'], [role='button']")).map(b => ({
                text: (b.innerText || b.value || "").trim(),
                selector: b.id ? `#${b.id}` : (b.name ? `[name='${b.name}']` : formId + " " + b.tagName.toLowerCase())
              }));
              forms.push({
                index: idx,
                id: form.id || null,
                name: form.name || null,
                action: form.action || window.location.href,
                method: (form.method || "GET").toUpperCase(),
                selector: formId,
                fields: inspectInputs(form),
                submitButtons: submits
              });
            });
          }

          const orphanedInputs = Array.from(document.querySelectorAll("input:not(form input), textarea:not(form textarea), select:not(form select)"));
          if (orphanedInputs.length > 0) {
            const standaloneFields = orphanedInputs.map(node => {
              const rect = node.getBoundingClientRect();
              let selector = node.id ? `#${node.id}` : (node.name ? `${node.tagName.toLowerCase()}[name='${node.name}']` : node.tagName.toLowerCase());
              return {
                tag: node.tagName.toLowerCase(),
                type: node.type || "text",
                name: node.name || null,
                id: node.id || null,
                placeholder: node.placeholder || null,
                value: node.value || "",
                selector: selector,
                bounds: { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }
              };
            });
            forms.push({
              index: forms.length,
              id: "standalone_fields",
              name: "inputs_without_form_tag",
              action: window.location.href,
              method: "AJAX/FETCH",
              selector: "body",
              fields: standaloneFields,
              submitButtons: []
            });
          }

          return {
            url: window.location.href,
            formCount: forms.length,
            forms: forms
          };
        }
      });
      return results[0]?.result || {};
    }

    case "get_elements": {
      if (!tab) throw new Error("No active browser tab found");
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const items = [];
          const nodes = Array.from(document.querySelectorAll("button, a, input, textarea, select, [role='button'], [role='link'], [role='textbox'], [role='combobox'], [role='checkbox'], form, [contenteditable='true'], [onclick]"));
          let idx = 0;
          nodes.forEach(node => {
            if (idx > 180) return;
            const rect = node.getBoundingClientRect();
            const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(node).visibility !== "hidden";
            if (!isVisible) return;

            let selector = "";
            if (node.id) selector = `#${node.id}`;
            else if (node.name) selector = `${node.tagName.toLowerCase()}[name='${node.name}']`;
            else if (node.placeholder) selector = `${node.tagName.toLowerCase()}[placeholder='${node.placeholder}']`;
            else if (node.className && typeof node.className === 'string') {
              const firstClass = node.className.trim().split(/\s+/)[0];
              if (firstClass && !firstClass.includes(":")) selector = `${node.tagName.toLowerCase()}.${firstClass}`;
            }
            if (!selector) selector = node.tagName.toLowerCase();

            items.push({
              index: idx++,
              tag: node.tagName.toLowerCase(),
              type: node.type || (node.isContentEditable ? 'contenteditable' : null),
              name: node.name || null,
              id: node.id || null,
              text: (node.innerText || node.value || node.placeholder || "").trim().slice(0, 100),
              selector: selector,
              coords: {
                x: Math.round(rect.left + rect.width / 2),
                y: Math.round(rect.top + rect.height / 2),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
              },
              href: node.href || null
            });
          });
          return {
            url: window.location.href,
            title: document.title,
            count: items.length,
            elements: items
          };
        }
      });
      return results[0]?.result || {};
    }

    case "screenshot": {
      if (!tab) throw new Error("No active browser tab found");
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      return {
        message: "Screenshot captured successfully",
        url: tab.url,
        dataUrl: dataUrl
      };
    }

    case "scroll": {
      if (!tab) throw new Error("No active browser tab found");
      const target = params.target || "down";
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (tgt) => {
          if (tgt === "top") {
            window.scrollTo({ top: 0, behavior: "smooth" });
          } else if (tgt === "bottom") {
            window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
          } else if (tgt === "up") {
            window.scrollBy({ top: -window.innerHeight * 0.75, behavior: "smooth" });
          } else if (tgt === "down" || !tgt) {
            window.scrollBy({ top: window.innerHeight * 0.75, behavior: "smooth" });
          } else {
            const el = document.querySelector(tgt);
            if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
          }
          return { scrollY: window.scrollY, scrollHeight: document.body.scrollHeight };
        },
        args: [target]
      });
      return results[0]?.result || {};
    }

    case "click": {
      if (!tab) throw new Error("No active browser tab found");
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (p) => {
          let elem = null;
          let clickX = null;
          let clickY = null;

          if (p.x !== undefined && p.y !== undefined && !isNaN(Number(p.x)) && !isNaN(Number(p.y))) {
            clickX = Number(p.x);
            clickY = Number(p.y);
            elem = document.elementFromPoint(clickX, clickY);
          }

          const sel = (p.selector || "").trim();
          if (!elem && sel) {
            const coordMatch = sel.match(/^(\d+)\s*,?\s*(\d+)$/);
            if (coordMatch) {
              clickX = parseInt(coordMatch[1], 10);
              clickY = parseInt(coordMatch[2], 10);
              elem = document.elementFromPoint(clickX, clickY);
            }
          }

          function queryDeep(s, root = document) {
            let f = null;
            try { f = root.querySelector(s); } catch (e) {}
            if (f) return f;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null, false);
            let node;
            while (node = walker.nextNode()) {
              if (node.shadowRoot) {
                const inner = queryDeep(s, node.shadowRoot);
                if (inner) return inner;
              }
              if (node.tagName === 'IFRAME' || node.tagName === 'FRAME') {
                try {
                  const doc = node.contentDocument || node.contentWindow?.document;
                  if (doc) {
                    const ifr = queryDeep(s, doc);
                    if (ifr) return ifr;
                  }
                } catch (e) {}
              }
            }
            return null;
          }

          function findByText(text) {
            const targetText = text.toLowerCase().trim();
            const all = Array.from(document.querySelectorAll("button, a, input[type='submit'], input[type='button'], [role='button'], span, div, p, label"));
            for (const el of all) {
              const txt = (el.innerText || el.value || "").toLowerCase().trim();
              if (txt === targetText || (txt.length > 0 && txt.includes(targetText) && txt.length < targetText.length + 30)) {
                return el;
              }
            }
            return null;
          }

          if (!elem && sel) {
            if (sel.startsWith("text=") || sel.startsWith("text:")) {
              elem = findByText(sel.slice(5).trim().replace(/^['"]|['"]$/g, ''));
            } else if (sel.startsWith("//") || sel.startsWith("(")) {
              try {
                const xpathRes = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                elem = xpathRes.singleNodeValue;
              } catch (e) {}
            }
            if (!elem) elem = queryDeep(sel);
            if (!elem) elem = findByText(sel);
          }

          if (!elem && clickX === null && clickY === null) {
            return { found: false, error: `Element or coordinates not found: ${sel}` };
          }

          const targetNode = elem || document.body;
          const rect = targetNode.getBoundingClientRect();
          const finalX = clickX !== null ? clickX : Math.round(rect.left + rect.width / 2);
          const finalY = clickY !== null ? clickY : Math.round(rect.top + rect.height / 2);

          if (elem && typeof elem.scrollIntoView === "function") {
            elem.scrollIntoView({ behavior: "instant", block: "center" });
          }
          if (elem && typeof elem.focus === "function") {
            elem.focus();
          }

          const eventOpts = {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: finalX,
            clientY: finalY,
            screenX: finalX,
            screenY: finalY,
            pointerId: 1,
            pointerType: "mouse",
            isPrimary: true
          };

          targetNode.dispatchEvent(new PointerEvent("pointerover", eventOpts));
          targetNode.dispatchEvent(new PointerEvent("pointerenter", eventOpts));
          targetNode.dispatchEvent(new MouseEvent("mouseover", eventOpts));
          targetNode.dispatchEvent(new MouseEvent("mouseenter", eventOpts));
          targetNode.dispatchEvent(new PointerEvent("pointerdown", eventOpts));
          targetNode.dispatchEvent(new MouseEvent("mousedown", eventOpts));
          targetNode.dispatchEvent(new PointerEvent("pointerup", eventOpts));
          targetNode.dispatchEvent(new MouseEvent("mouseup", eventOpts));
          targetNode.dispatchEvent(new MouseEvent("click", eventOpts));
          if (typeof targetNode.click === "function") {
            targetNode.click();
          }

          return {
            found: true,
            clicked: true,
            x: finalX,
            y: finalY,
            tagName: targetNode.tagName,
            id: targetNode.id || null,
            text: (targetNode.innerText || targetNode.value || "").slice(0, 60)
          };
        },
        args: [params]
      });
      return results[0]?.result || {};
    }

    case "type": {
      if (!tab) throw new Error("No active browser tab found");
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (p) => {
          const sel = (p.selector || "").trim();
          const textVal = p.text !== undefined ? String(p.text) : (p.value !== undefined ? String(p.value) : "");

          function queryDeep(s, root = document) {
            let f = null;
            try { f = root.querySelector(s); } catch (e) {}
            if (f) return f;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null, false);
            let node;
            while (node = walker.nextNode()) {
              if (node.shadowRoot) {
                const inner = queryDeep(s, node.shadowRoot);
                if (inner) return inner;
              }
              if (node.tagName === 'IFRAME' || node.tagName === 'FRAME') {
                try {
                  const doc = node.contentDocument || node.contentWindow?.document;
                  if (doc) {
                    const ifr = queryDeep(s, doc);
                    if (ifr) return ifr;
                  }
                } catch (e) {}
              }
            }
            return null;
          }

          function findInputAnywhere(query) {
            if (!query) return null;
            let el = queryDeep(query);
            if (el) return el;
            el = queryDeep(`input[name='${query}'], textarea[name='${query}'], select[name='${query}']`);
            if (el) return el;
            el = queryDeep(`input[placeholder*='${query}' i], textarea[placeholder*='${query}' i]`);
            if (el) return el;
            el = queryDeep(`[aria-label*='${query}' i]`);
            if (el) return el;
            const labels = Array.from(document.querySelectorAll("label"));
            for (const lbl of labels) {
              if (lbl.innerText.toLowerCase().includes(query.toLowerCase())) {
                if (lbl.htmlFor) {
                  const byId = document.getElementById(lbl.htmlFor);
                  if (byId) return byId;
                }
                const nested = lbl.querySelector("input, textarea, select");
                if (nested) return nested;
              }
            }
            return null;
          }

          let target = null;
          if (p.x !== undefined && p.y !== undefined) {
            target = document.elementFromPoint(Number(p.x), Number(p.y));
          }
          if (!target && sel) {
            target = findInputAnywhere(sel);
          }
          if (!target) {
            target = document.activeElement;
          }
          if (!target || target === document.body) {
            target = document.querySelector("input:not([type='hidden']), textarea, [contenteditable='true']");
          }

          if (!target) {
            return { found: false, error: `No editable element located for selector/target: ${sel}` };
          }

          if (typeof target.scrollIntoView === "function") {
            target.scrollIntoView({ behavior: "instant", block: "center" });
          }
          target.focus();

          if (p.clear) {
            if (target.isContentEditable) {
              target.innerText = "";
            } else if ("value" in target) {
              target.value = "";
            }
          }

          if (target.isContentEditable) {
            target.focus();
            try {
              document.execCommand("insertText", false, textVal);
            } catch (e) {
              target.innerText = (target.innerText || "") + textVal;
            }
            target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: textVal }));
            target.dispatchEvent(new Event("change", { bubbles: true }));
            return { found: true, typed: textVal, mode: "contenteditable" };
          }

          const isInput = target.tagName === "INPUT";
          const isTextArea = target.tagName === "TEXTAREA";

          if (isInput || isTextArea) {
            const proto = isInput ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, "value");
            const currentVal = target.value || "";
            const nextVal = p.append ? (currentVal + textVal) : textVal;
            if (desc && desc.set) {
              desc.set.call(target, nextVal);
            } else {
              target.value = nextVal;
            }
          } else {
            target.value = textVal;
          }

          target.dispatchEvent(new Event("focus", { bubbles: true }));
          target.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, inputType: "insertText", data: textVal }));
          target.dispatchEvent(new Event("input", { bubbles: true }));
          target.dispatchEvent(new Event("change", { bubbles: true }));
          target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: textVal.slice(-1) || "Enter" }));
          target.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: textVal.slice(-1) || "Enter" }));

          return {
            found: true,
            typed: textVal,
            tagName: target.tagName,
            name: target.name || null,
            id: target.id || null,
            currentValue: target.value || target.innerText || ""
          };
        },
        args: [params]
      });
      return results[0]?.result || {};
    }

    case "fill_form": {
      if (!tab) throw new Error("No active browser tab found");
      const fields = params.fields || {};
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (fieldMap) => {
          const filled = [];
          const errors = [];

          function findInputAnywhere(query) {
            if (!query) return null;
            let el = document.querySelector(query);
            if (el) return el;
            el = document.querySelector(`input[name='${query}'], textarea[name='${query}'], select[name='${query}']`);
            if (el) return el;
            el = document.querySelector(`#${query}`);
            if (el) return el;
            el = document.querySelector(`[placeholder='${query}'], [placeholder*='${query}' i]`);
            if (el) return el;
            el = document.querySelector(`[aria-label*='${query}' i]`);
            if (el) return el;
            const labels = Array.from(document.querySelectorAll("label"));
            for (const lbl of labels) {
              if (lbl.innerText.toLowerCase().includes(query.toLowerCase())) {
                if (lbl.htmlFor) {
                  const byId = document.getElementById(lbl.htmlFor);
                  if (byId) return byId;
                }
                const nested = lbl.querySelector("input, textarea, select");
                if (nested) return nested;
              }
            }
            return null;
          }

          for (const [key, value] of Object.entries(fieldMap)) {
            let target = findInputAnywhere(key);
            if (!target) {
              errors.push(`Field '${key}' not found on page`);
              continue;
            }

            target.scrollIntoView({ behavior: "instant", block: "center" });
            target.focus();

            if (target.type === "checkbox" || target.type === "radio") {
              const shouldCheck = Boolean(value) && value !== "false" && value !== "0";
              if (target.checked !== shouldCheck) {
                target.checked = shouldCheck;
                target.dispatchEvent(new Event("change", { bubbles: true }));
                target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
              }
              filled.push({ field: key, checked: target.checked });
            } else if (target.tagName === "SELECT") {
              let matched = false;
              for (const opt of target.options) {
                if (opt.value === value || opt.text.trim().toLowerCase() === String(value).trim().toLowerCase()) {
                  opt.selected = true;
                  matched = true;
                  break;
                }
              }
              target.dispatchEvent(new Event("change", { bubbles: true }));
              filled.push({ field: key, value: target.value, matched: matched });
            } else if (target.isContentEditable) {
              target.innerText = value;
              target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
              target.dispatchEvent(new Event("change", { bubbles: true }));
              filled.push({ field: key, value: value });
            } else {
              const isInput = target.tagName === "INPUT";
              const proto = isInput ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
              const desc = Object.getOwnPropertyDescriptor(proto, "value");
              if (desc && desc.set) {
                desc.set.call(target, value);
              } else {
                target.value = value;
              }
              target.dispatchEvent(new Event("input", { bubbles: true }));
              target.dispatchEvent(new Event("change", { bubbles: true }));
              filled.push({ field: key, value: value });
            }
          }
          return { success: errors.length === 0, filled: filled, errors: errors };
        },
        args: [fields]
      });
      return results[0]?.result || {};
    }

    case "submit": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector || "form";
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          let formEl = document.querySelector(sel);
          if (formEl && formEl.tagName !== "FORM") {
            formEl = formEl.closest("form");
          }
          if (formEl && typeof formEl.requestSubmit === "function") {
            formEl.requestSubmit();
            return { submitted: true, method: formEl.method, action: formEl.action };
          } else if (formEl && typeof formEl.submit === "function") {
            formEl.submit();
            return { submitted: true, method: formEl.method, action: formEl.action };
          }
          const submitBtn = document.querySelector(`${sel} [type='submit'], ${sel} button, [type='submit']`);
          if (submitBtn) {
            submitBtn.click();
            return { submitted: true, via: "button_click" };
          }
          return { submitted: false, error: `No submittable form found for selector: ${sel}` };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "check": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel);
          if (!el) return { error: `Checkbox/radio '${sel}' not found` };
          el.focus();
          el.checked = true;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          return { success: true, checked: true };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "uncheck": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel);
          if (!el) return { error: `Checkbox '${sel}' not found` };
          el.focus();
          el.checked = false;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          return { success: true, checked: false };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "press": {
      if (!tab) throw new Error("No active browser tab found");
      const { selector, key = "Enter" } = params;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, k) => {
          const targetNode = sel ? document.querySelector(sel) : document.activeElement;
          if (!targetNode) return { success: false, error: "Target node not found" };
          targetNode.focus();
          targetNode.dispatchEvent(new KeyboardEvent("keydown", { key: k, code: k, bubbles: true }));
          targetNode.dispatchEvent(new KeyboardEvent("keypress", { key: k, code: k, bubbles: true }));
          targetNode.dispatchEvent(new KeyboardEvent("keyup", { key: k, code: k, bubbles: true }));
          if (k.toLowerCase() === "enter" && targetNode.form) {
            if (typeof targetNode.form.requestSubmit === "function") {
              targetNode.form.requestSubmit();
            } else {
              targetNode.form.submit();
            }
          }
          return { success: true, key: k, activeElement: targetNode.tagName };
        },
        args: [selector || null, key]
      });
      return results[0]?.result || {};
    }

    case "hover": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel);
          if (!el) return { success: false, error: `Element not found: ${sel}` };
          el.scrollIntoView({ behavior: "instant", block: "center" });
          el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
          el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
          return { success: true, selector: sel };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "highlight": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel);
          if (!el) return { success: false, error: `Element not found: ${sel}` };
          el.scrollIntoView({ behavior: "instant", block: "center" });
          el.style.outline = "3px solid #f59e0b";
          el.style.backgroundColor = "rgba(245, 158, 11, 0.2)";
          return { success: true, selector: sel };
        },
        args: [selector]
      });
      return results[0]?.result || {};
    }

    case "select": {
      if (!tab) throw new Error("No active browser tab found");
      const { selector, value } = params;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, val) => {
          const el = document.querySelector(sel);
          if (!el) return { success: false, error: `Select element not found: ${sel}` };
          el.focus();
          let selected = false;
          for (const opt of el.options) {
            if (opt.value === val || opt.text.trim() === String(val).trim()) {
              opt.selected = true;
              selected = true;
              break;
            }
          }
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return { success: selected, value: el.value };
        },
        args: [selector, value]
      });
      return results[0]?.result || {};
    }

    case "wait": {
      if (!tab) throw new Error("No active browser tab found");
      const selector = params.selector;
      const timeoutMs = (params.timeout || 10) * 1000;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: async (sel, timeout) => {
          const startTime = Date.now();
          while (Date.now() - startTime < timeout) {
            const el = document.querySelector(sel);
            if (el) return { found: true, selector: sel, text: el.innerText ? el.innerText.slice(0, 100) : "" };
            await new Promise(r => setTimeout(r, 200));
          }
          return { found: false, error: `Timed out waiting for ${sel}` };
        },
        args: [selector, timeoutMs]
      });
      return results[0]?.result || {};
    }

    case "eval": {
      if (!tab) throw new Error("No active browser tab found");
      const code = params.code;
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: "MAIN",
        func: (scriptCode) => {
          try {
            const evalResult = window.eval(scriptCode);
            return { value: evalResult !== undefined ? String(evalResult) : "undefined" };
          } catch (e) {
            return { error: e.message };
          }
        },
        args: [code]
      });
      return results[0]?.result || {};
    }

    case "get_cookies": {
      if (!tab) throw new Error("No active browser tab found");
      const cookies = await chrome.cookies.getAll({ url: tab.url });
      return cookies.map(c => ({ name: c.name, value: c.value, domain: c.domain, path: c.path, httpOnly: c.httpOnly }));
    }

    case "clear_cookies": {
      if (!tab) throw new Error("No active browser tab found");
      const cookies = await chrome.cookies.getAll({ url: tab.url });
      for (const c of cookies) {
        const prefix = c.secure ? "https://" : "http://";
        await chrome.cookies.remove({ url: prefix + c.domain.replace(/^\./, "") + c.path, name: c.name });
      }
      return { cleared: cookies.length };
    }

    case "get_tabs": {
      const tabs = await chrome.tabs.query({});
      return tabs.map(t => ({ id: t.id, title: t.title, url: t.url, active: t.active }));
    }

    default:
      throw new Error(`Unknown action: ${action}`);
  }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getStatus") {
    sendResponse({
      connected: isConnected,
      activeTab: lastActiveTabInfo
    });
  } else if (request.action === "reconnect") {
    connectWebSocket();
    sendResponse({ reconnecting: true });
  }
  return true;
});

chrome.tabs.onActivated.addListener(() => notifyTabChange());
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active) notifyTabChange();
});

chrome.alarms.create("keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive") {
    if (!isConnected || !socket || socket.readyState !== WebSocket.OPEN) {
      connectWebSocket();
    } else {
      try {
        socket.send(JSON.stringify({ type: "ping" }));
      } catch (e) {}
    }
  }
});

connectWebSocket();
