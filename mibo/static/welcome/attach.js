"use strict";
// What rides on the next message of a chat: pictures and text files picked with +, pasted or dropped on the chat,
// and pages from the app's browser, shown in a tray above the text until sent. A file that cannot go says why in
// one line. The chat (chat.js) makes one of these per chat view.
window.paAttach = (() => {
  const { I, el, svg, iconButton } = window.paKit;
  // What a message can carry (welcome.py checks it again): at most `most` things. A picture of at
  // most `picked` bytes, sent as picked when it is within `side` pixels and `picture` bytes, else
  // drawn smaller as WebP until it is; a text file of at most `file` bytes, by its extension.
  const ATTACH = { most: 4, picked: 20 * 1024 * 1024, picture: 1000000, side: 1600, file: 512 * 1024 };
  const PICTURE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
  const TEXT_KINDS = new Set(
    ("txt text md markdown rst csv tsv json jsonl yaml yml toml ini cfg conf log xml html htm " +
      "css scss js mjs cjs ts tsx jsx vue py ipynb java kt kts scala go rs c h cc cpp hpp cs m mm " +
      "swift rb php pl lua r sql sh bash zsh ps1 bat cmd tex bib srt vtt diff patch").split(" "),
  );
  // What the file picker offers.
  const ACCEPT = [...PICTURE_TYPES, ...[...TEXT_KINDS].map((kind) => `.${kind}`)].join(",");

  const extOf = (name) => (/\.([^.]+)$/.exec(name)?.[1] || "").toLowerCase();
  function sizeOf(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    return bytes < 1048576 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  }
  const base64Of = (blob) =>
    new Promise((done, fail) => {
      const reader = new FileReader();
      reader.onload = () => done(String(reader.result).split(",")[1] || "");
      reader.onerror = () => fail(reader.error);
      reader.readAsDataURL(blob);
    });
  // A picture as it is sent: as picked when small enough, else drawn smaller as WebP.
  async function sendable(file) {
    const bitmap = await createImageBitmap(file);
    try {
      let scale = Math.min(1, ATTACH.side / Math.max(bitmap.width, bitmap.height));
      if (scale === 1 && file.size <= ATTACH.picture) return file;
      for (;;) {
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise((done) => canvas.toBlob(done, "image/webp", 0.85));
        if (blob.size <= ATTACH.picture) return blob;
        scale *= 0.75;
      }
    } finally {
      bitmap.close();
    }
  }
  // Whether a file's bytes read as text, as welcome.py reads them: UTF-8, UTF-16 with its mark, or GB18030.
  function readsAsText(buffer) {
    const bytes = new Uint8Array(buffer);
    if ((bytes[0] === 0xff && bytes[1] === 0xfe) || (bytes[0] === 0xfe && bytes[1] === 0xff)) return true;
    for (const label of ["utf-8", "gb18030"]) {
      try {
        return !new TextDecoder(label, { fatal: true }).decode(bytes).includes("\0");
      } catch {
        // Not this one: the next.
      }
    }
    return false;
  }
  // A file's icon, name and size, as the tray and a sent message show it.
  function fileWords(item, say) {
    const icon = el("span", "att-icon");
    icon.append(svg(I.file));
    const words = el("span", "att-words");
    const size = el("span", "att-size", sizeOf(item.size));
    if (item.clipped) {
      size.textContent += ` · ${say("clipped")}`;
      size.title = say("clippedTip");
    }
    words.append(el("span", "att-name", item.file), size);
    const frag = document.createDocumentFragment();
    frag.append(icon, words);
    return frag;
  }

  // `env`: the tray, the composer's form, the line for a refusal and the text box; say(key) in the chat's words;
  // configured() whether the chat can send; changed() when what is attached or ready changed.
  function create(env) {
    const { say } = env;
    // { key, kind, file, size, url, data } each, data once it is ready.
    let items = [];
    let lastKey = 0;

    function add(files) {
      if (!env.configured() || !files.length) return;
      refuse("");
      for (const file of files) {
        if (items.length >= ATTACH.most) {
          refuse(say("refusedMany"));
          break;
        }
        const kind = PICTURE_TYPES.has(file.type) ? "picture" : "file";
        const item = { key: ++lastKey, kind, file: file.name || "image.png", size: file.size, url: "", data: "" };
        const why =
          kind === "picture"
            ? file.size > ATTACH.picked && "refusedPictureSize"
            : !TEXT_KINDS.has(extOf(item.file))
              ? "refusedType"
              : file.size > ATTACH.file && "refusedFileSize";
        if (why) {
          refuse(say(why).replace("{file}", item.file));
          continue;
        }
        items.push(item);
        (async () => {
          if (kind === "file") {
            if (!readsAsText(await file.arrayBuffer())) throw new Error("unreadable");
            item.data = await base64Of(file);
            return;
          }
          const picture = await sendable(file);
          item.size = picture.size;
          item.data = await base64Of(picture);
          item.url = URL.createObjectURL(picture);
        })()
          .catch(() => {
            remove(item);
            refuse(say(kind === "picture" ? "refusedPicture" : "refusedUnreadable").replace("{file}", item.file));
          })
          .finally(paint);
      }
      paint();
      env.input.focus();
    }
    function remove(item) {
      items = items.filter((other) => other !== item);
      if (item.url && item.kind !== "page") URL.revokeObjectURL(item.url);
      paint();
    }
    // Something "+" adds that is no file: a page from the app's browser ({ kind: "page", url, title }).
    function addItem(item) {
      refuse("");
      if (items.length >= ATTACH.most) return refuse(say("refusedMany"));
      items.push({ ...item, key: ++lastKey, file: item.title || item.url, data: item.kind });
      paint();
      env.input.focus();
    }
    function paint() {
      env.tray.hidden = !items.length;
      env.form.classList.toggle("has-tray", items.length > 0);
      const chips = items.map((item) => {
        const chip = el("div", `att att-${item.kind}${item.data ? "" : " pa-shimmer"}`);
        chip.title = item.file;
        if (item.kind === "picture") {
          if (item.url) {
            const image = el("img");
            image.alt = item.file;
            image.src = item.url;
            chip.append(image);
          }
        } else if (item.kind === "page") {
          chip.className = "att att-file att-page";
          chip.append(...window.paPlus.pageChip(item).childNodes);
        } else chip.append(fileWords(item, say));
        chip.append(iconButton("att-x", I.x, say("remove").replace("{file}", item.file), () => {
          remove(item);
          env.input.focus();
        }));
        return chip;
      });
      const row = el("div", "chat-tray-row");
      row.append(...chips);
      env.tray.replaceChildren(row);
      env.changed();
    }
    function refuse(text) {
      env.refused.hidden = !text;
      env.refused.replaceChildren();
      if (text)
        env.refused.append(svg(I.alert), el("span", "chat-refused-text", text),
          iconButton("chat-quote-x", I.x, say("dismiss"), () => refuse("")));
    }

    return {
      add,
      addItem,
      refuse,
      paint,
      get count() {
        return items.length;
      },
      // Every one read and ready to go.
      ready: () => items.every((item) => item.data),
      // What goes with the message being sent; the tray empties.
      take() {
        const taken = items;
        items = [];
        refuse("");
        paint();
        return taken;
      },
      drop() {
        for (const item of items) if (item.url) URL.revokeObjectURL(item.url);
      },
    };
  }

  return { create, fileWords, ACCEPT };
})();
