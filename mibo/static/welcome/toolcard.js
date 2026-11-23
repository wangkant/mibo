"use strict";
// A form one of the person's MCP servers asks them to fill in during a call (mcp_hub.py, mcp_schema.ask_fields),
// under the typing row while the reply waits on it: what the server asks, a labelled field each, and its two
// buttons. What they fill in is sent with its button (POST /api/mcp/card), to the server alone. Every other
// question a server's step waits on is said in the chat and answered there (chat.js, cardwait.py).
(() => {
  const { el, fill, pressHeaders } = window.paKit;
  let shown = null;

  // One labelled input per field; returns the node and a reader of the values that marks a required field left
  // empty and gives null then.
  function form(fields, t) {
    const node = el("div", "ask-form");
    const reads = [];
    for (const field of fields) {
      const row = el("label", "ask-field");
      const name = el("span", "ask-field-name", field.title);
      if (field.required) name.append(el("span", "ask-field-meta", ` · ${t.required}`));
      row.append(name);
      let input;
      if (field.kind === "choice") {
        input = el("select", "pa-select");
        if (!field.required) input.append(el("option", "", ""));
        for (const option of field.options) {
          const item = el("option", "", option.label);
          item.value = option.value;
          input.append(item);
        }
        input.value = field.default ?? (field.required ? field.options[0]?.value : "");
        reads.push(() => [field, input, input.value]);
      } else if (field.kind === "choices") {
        input = el("span", "ask-field-choices");
        const boxes = field.options.map((option) => {
          const box = el("input", "pa-check");
          box.type = "checkbox";
          box.value = option.value;
          box.checked = (field.default || []).includes(option.value);
          const one = el("label", "ask-field-choice");
          one.append(box, el("span", "", option.label));
          input.append(one);
          return box;
        });
        reads.push(() => [field, input, boxes.filter((b) => b.checked).map((b) => b.value)]);
      } else if (field.kind === "boolean") {
        input = el("input", "pa-check");
        input.type = "checkbox";
        input.checked = field.default === true;
        row.classList.add("ask-field-check");
        reads.push(() => [field, input, input.checked]);
      } else {
        input = el("input", "pa-input");
        const numeric = field.kind === "number" || field.kind === "integer";
        input.type = numeric ? "number"
          : { email: "email", uri: "url", date: "date", "date-time": "datetime-local" }[field.format] || "text";
        if (numeric) {
          if (field.minimum !== undefined) input.min = field.minimum;
          if (field.maximum !== undefined) input.max = field.maximum;
          input.step = field.kind === "integer" ? "1" : "any";
        }
        if (field.default !== undefined) input.value = field.default;
        reads.push(() => [field, input,
          input.value.trim() === "" ? "" : numeric ? Number(input.value) : input.value.trim()]);
      }
      row.append(input);
      if (field.description) row.append(el("span", "ask-field-meta", field.description));
      node.append(row);
    }
    const values = () => {
      const out = {};
      let whole = true;
      for (const read of reads) {
        const [field, input, value] = read();
        const empty = value === "" || (Array.isArray(value) && !value.length);
        input.setAttribute("aria-invalid", String(field.required && empty));
        if (field.required && empty) whole = false;
        if (!empty) out[field.name] = value;
      }
      return whole ? out : null;
    };
    return [node, values];
  }

  // `card` from GET /api/mcp/card (a form: typed false) shown under the waiting row; null takes an unanswered one
  // away.
  function show(waiting, card, keepEnd = () => {}) {
    const t = paI18n.words("toolcard");
    if (shown && (!card || shown.dataset.id !== card.id)) {
      if (!shown.classList.contains("answered")) shown.remove();
      shown = null;
    }
    if (!card || shown || !waiting) return;
    const node = el("div", "ask-card mcp-form");
    node.dataset.id = card.id;
    node.append(el("p", "ask-card-text", fill(t.askTitle, card)), el("p", "ask-card-meta", fill(t.askMeta, card)));
    if (card.message) node.append(el("p", "ask-card-quote", card.message));
    const [fields, values] = form(card.fields, t);
    node.append(fields, el("p", "ask-card-meta", fill(t.askNote, card)));
    const answer = async (value) => {
      const filled = value === "once" ? values() : undefined;
      if (filled === null) return;
      for (const b of node.querySelectorAll("button, input")) b.disabled = true;
      node.classList.add("answered");
      const told = el("p", "ask-card-told", t[value === "once" ? "askOnce" : "askNo"]);
      node.querySelector(".ask-card-told")?.remove();
      node.append(told);
      try {
        const response = await fetch("/api/mcp/card", {
          method: "POST",
          credentials: "same-origin",
          headers: pressHeaders(),
          body: JSON.stringify({ id: card.id, answer: value, values: filled }),
        });
        const said = await response.json().catch(() => ({}));
        if (said.problem) {
          // The server's form wants something else: it stays up to be corrected.
          told.textContent = t.fix;
          node.classList.remove("answered");
          for (const b of node.querySelectorAll("button, input")) b.disabled = false;
        } else if (!said.ok) told.textContent = t.gone;
      } catch {
        told.textContent = t.gone;
      }
    };
    const buttons = el("div", "ask-card-buttons");
    for (const [cls, text, value] of [["pa-btn-primary", t.submit, "once"], ["pa-btn-secondary", t.decline, "no"]]) {
      const b = el("button", `pa-btn ${cls} pa-btn-sm`, text);
      b.type = "button";
      b.addEventListener("click", () => answer(value));
      buttons.append(b);
    }
    node.append(buttons);
    waiting.after(node);
    shown = node;
    const label = waiting.querySelector(".doing");
    if (label) label.textContent = t.waiting;
    keepEnd();
  }

  window.paToolCard = { show };
})();
