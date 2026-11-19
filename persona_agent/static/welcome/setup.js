"use strict";
// The app's settings: connect a model, shape the character, choose the pet's
// figure. It takes over setup from the earlier page, which stays one link away
// at the bottom for what has not moved yet.
(() => {
  const WORDS = {
    zh: {
      title: "设置",
      intro: "让角色开口说话，再给它起个名字、定个性格。",
      modelTitle: "模型",
      modelHint: "角色靠它来思考和说话。",
      noneTitle: "还没有连接模型",
      noneHint: "选下面任意一种方式连上，角色就能回复你了。",
      answers: "能正常回复",
      answersNow: "刚刚检查过，能正常回复",
      notAnswering: "最近一次没有回应",
      checking: "正在检查…",
      check: "检查一下",
      change: "更换模型",
      changeClose: "收起",
      recommended: "推荐",
      signinTitle: "用 OpenRouter 登录",
      signinText: "在浏览器里登录 OpenRouter 账号，就能用免费模型，不用复制密钥。",
      signinButton: "用 OpenRouter 登录",
      signinOpening: "正在打开浏览器…",
      signinPending: "正在等待批准…",
      signinWaiting: "请在浏览器里批准登录，批准后这里会自动接上。",
      signinCodeWaiting: "请打开 OpenRouter 页面并批准，再把页面上显示的代码粘贴到这里。",
      signinOpenPage: "打开 OpenRouter 页面",
      signinCodeLabel: "OpenRouter 显示的代码",
      signinCodeUse: "使用此代码",
      signinVerifying: "已批准，正在验证密钥…",
      signinHint:
        "OpenRouter 会为 personagent 创建一个密钥，保存在本机。在 openrouter.ai/keys 删除它之前，它可以使用你的 OpenRouter 账户余额；免费模型无需余额，每天限 50 次请求。",
      cancel: "取消",
      or: "或者",
      localFound: "这台电脑上正在运行 {name}",
      localHint: "不需要密钥，聊天内容不会离开这台电脑。",
      localModel: "用哪个模型",
      useLocal: "使用 {name}",
      envFound: "环境变量 {variable} 里有 {provider} 的密钥",
      envHint: "直接拿来用，密钥不会出现在页面上。",
      useEnv: "使用此密钥",
      keyTitle: "粘贴密钥",
      keyText: "已经有某个模型服务的 API 密钥？选好服务、粘贴进来，检查通过就保存。",
      service: "模型服务",
      key: "API 密钥",
      keyPlaceholder: "粘贴密钥，例如 sk-…",
      keyKeep: "留空则保留已保存的密钥",
      keyNone: "{name} 在本机运行，不需要密钥。",
      show: "显示",
      hide: "隐藏",
      showKey: "显示密钥",
      hideKey: "隐藏密钥",
      getKey: "去 {name} 获取密钥",
      keyStays: "密钥只保存在这台电脑上。",
      advanced: "模型名称与服务地址",
      modelName: "模型名称",
      modelNameHelp: "不改就用这个服务推荐的模型。",
      free: "免费",
      address: "服务地址",
      addressHelp: "兼容 OpenAI 的接口地址，通常以 /v1 结尾。",
      freeNote: "OpenRouter 免费模型：每天限 50 次请求；每次用到的模型可能不同，部分免费服务商会保留收到的内容。",
      connect: "检查并保存",
      connecting: "正在检查…",
      checkingKey: "正在给 {name} 发一条很短的消息，确认能用。最多需要 20 秒。",
      doneTitle: "连好了",
      doneText: "{name}已经能回复你了，去和它聊聊吧。",
      it: "角色",
      toChat: "去聊天",
      characterTitle: "角色",
      characterHint: "它叫什么，是什么样的性格。",
      name: "名字",
      namePlaceholder: "例如 小满",
      nameHelp: "它会用这个名字称呼自己。",
      startFrom: "从现成的性格开始",
      own: "我自己写",
      persona: "它是什么样的",
      personaHelp: "写它是谁、怎么说话、在意什么。保存后马上生效，它学到的东西都会保留。",
      replaceNote: "保存后，它会换成「{title}」{line}",
      replaceOwn: "你原来写的人设会另存为 personagent 文件夹里的 persona.txt.bak。",
      backToOwn: "还是用我写的",
      saveCharacter: "保存",
      savingCharacter: "正在保存…",
      savedCharacter: "已保存，角色已按新的设定重新启动。",
      needModel: "名字和性格会在连接模型时一起保存。",
      figureTitle: "桌面形象",
      figureHint: "桌面上的它长这个样子。点一下就换，桌面上的它随即跟着变。",
      figureNow: "正在使用",
      computerTitle: "这台电脑",
      computerTitleHost: "运行它的电脑",
      startTitle: "开机自动启动",
      startText: "登录这台电脑后，它会自己出现在桌面上。",
      startOther: "现在开机启动的是另一份 personagent。",
      startMine: "改成启动这一份",
      startUvx: "用 uvx 临时运行的这一份没法开机启动。",
      startUnread: "现在读不到开机启动的设置，过一会儿再打开设置看看。",
      quietTitle: "全屏或打游戏时自动隐藏",
      quietText: "游戏、全屏视频或演示在前台时，桌宠会隐藏，后台阅读也会暂停。",
      quietNow: { game: "现在正隐藏着：在玩游戏。", presentation: "现在正隐藏着：在演示。", fullscreen: "现在正隐藏着：有全屏窗口。" },
      remarksTitle: "角色会留意你在做什么",
      remarksText:
        "它会看你最前面的程序和窗口标题，只在这台电脑上；发给模型的只有活动的种类（写作业、写代码、看视频……）。开着麦克风时它不说话。",
      ignoreLabel: "不看这些程序",
      ignoreHelp: "填程序名，比如 微信、Chrome、VS Code（任务管理器“详细信息”里的名字，不带 .exe）；Mac 上填应用名。",
      ignoreAdd: "加一个程序",
      ignoreRemove: (name) => `去掉 ${name}`,
      privateTitle: "允许角色读邮件和私信内容",
      privateWhere: (s) => (s.local ? `这台电脑上的模型 ${s.model}（${s.host}）` : `${s.host} 上的模型 ${s.model}`),
      privateOff: (where) =>
        `关着：邮件和私信写了什么不会发给模型，也不会拿来推荐；角色只在这台电脑上说一声来了几封、谁发来的。打开后，会发给${where}。`,
      privateOn: (where) =>
        `开着：每封新邮件和每段私信的发件人、标题和一小段正文会发给${where}；邮箱、电话、长串数字、验证码和链接后半段会先遮掉。`,
      privateAsk: (where, local) =>
        `打开后，每封新邮件和每段私信的发件人、标题和最多 200 字的正文摘录会发给${where}，模型要读到它们才能回答${local ? "；它在这台电脑上，内容不会离开这台电脑" : "；路上是 https 加密的"}。邮箱地址、电话、卡号和账号、验证码、链接的参数会先遮掉，整段对话和附件不会发。`,
      privateYes: "确定打开",
      privateNo: "先不打开",
      privateUnsafe: (host) =>
        `打不开：你的模型服务 ${host} 用的是没有加密的 http。邮件和私信只发给 https 的模型服务，或者这台电脑上的模型。`,
      privateNoModel: "先连好模型，才能打开这个开关。",
      connectTitle: "连接",
      connectHint: "公开的网页它会自己去逛。在这里还可以让它读读你自己的地方。",
      moreTitle: "更多",
      moreText: "连接聊天平台、工具和其他高级设置，暂时还在旧版设置页里。",
      moreLink: "打开高级设置",
      ago: { now: "刚刚", m: (n) => `${n} 分钟前`, h: (n) => `${n} 小时前`, d: (n) => `${n} 天前` },

      whereTitle: "网站和语言",
      whereHint: "它按这些决定去哪些网站找东西、推荐哪些语言的内容。看得不对就改过来。",
      reads: (names) => `读 ${names}`,
      listSep: "、",
      platform: { up: "能连上", down: "连不上", unknown: "还没查过" },
      canRead: "我能读",

      knowTitle: "它对你的了解",
      knowHint: "它记下的关于你的事。你改过或加上的行会被钉住，它整理时原样保留。",
      owner: "关于你",
      ownerHelp: "喜好、习惯、最近在忙什么。",
      learned: "它从你这儿喜欢上的",
      learnedHelp: "最多三行。",
      learnedOver: "只会留下前三行。",
      pinnedLine: "钉住的行",
      unpin: (line) => `取消钉住：${line}`,
      saveKnow: "保存",
      savingKnow: "正在保存…",
      rewriting: "它正在重新整理对你的了解，可能要半分钟。",
      savedKnow: "已保存，它重新整理了一遍。",
      savedPlain: "已保存。连上模型后它会据此整理。",
      savedLater: "已保存。这次没整理成功，下次整理时会用上。",
      leans: "来源偏好",
      leansHelp: "往右多看一些，往左少看一些。",
      leansOpen: (n, all) => (n ? `调整各个来源 · 已调整 ${n} 个` : `调整各个来源（共 ${all} 个）`),
      less: "少一些",
      more: "多一些",
      noSources: "现在还没有它能读的公开来源。",
      leansFind: "按名字找来源",
      leansLeft: (n) => `还有 ${n} 个，输入名字找。`,
      words: "它出门时搜的词",
      wordsHelp: "最多 5 个，按回车加上。",
      wordAdd: "加一个词",
      wordRemove: (word) => `去掉 ${word}`,
      rules: "不想看的",
      rulesEmpty: "还没有。在「关于你」里写下不想看什么，它整理时会变成一条规则。",
      ruleSource: (name) => `来源：${name}`,
      ruleTopic: (topic) => `话题：${topic}`,
      ruleRemove: (what) => `删掉「${what}」`,
      ruleSure: "再点一次删掉",
      rulesHelp: "从「关于你」里的话来的规则，下次整理时会再出现，要一起改掉那一行。",
      tell: (name) => `告诉${name}你喜欢什么，或者最近在忙什么`,
      tellPlaceholder: "比如：最近在准备考试，喜欢看讲数学的长视频，不想看明星八卦。",
      tellSend: "告诉它",
      tellWaiting: "它在想…",
      tellDone: "记下了，它重新整理了对你的了解。",
      tellKept: "记下了。连上模型后它会据此整理。",
      tellLater: "记下了。这次没整理成功，下次整理时会用上。",
      callsMonth: (n, judge, profile, pick, tokens) =>
        `这个月为你调用了 ${n} 次模型（判断 ${judge} 次，整理 ${profile} 次，挑推荐 ${pick} 次），共 ${tokens} tokens。`,
      callsNone: "这个月还没有为这些调用过模型。",

      recsTitle: "推荐",
      recsHint: "它带回来的东西怎么排。",
      model: "按你的口味学习",
      modelText: "从你打开、喜欢和跳过的内容里学你的口味，每 20 条里还会放一两条它自己挑的。",
      modelOff: "关着：按简单的规则排序，也不会有它自己挑的。",
      numbers: "这周的数字",
      numbersOff: "排序模型关着，下面是之前记下的。",
      surface: { list: "列表", card: "桌面卡片", chat: "聊天", other: "其他" },
      where: "在哪儿",
      shown: "展示",
      opened: "打开",
      liked: "喜欢",
      skipped: "跳过",
      noShown: "这周还没有给你看过什么。",
      played: "在应用里播放",
      top5: "列表里的打开，来自前 5 条",
      top5Value: (share, n) => `${share}（共 ${n} 次）`,
      pickLiked: "它挑的，喜欢率",
      modelLiked: "按口味排的，喜欢率",
      ofN: (rate, n) => `${rate}（${n} 条）`,
      slots: "它自己挑的",
      slotsValue: (k) => `每 20 条里 ${k} 条`,
      gated: "这周从连不上的网站推荐的",
      fitted: "上次学习",
      fittedValue: (when, n) => `${when} · 基于 ${n} 条`,
      notFitted: "还没有",
      weights: "它学到的",
      weightsHelp: "排序时这几点各占多少分量。圆点越靠右越加分；浅色横条是它还拿不准的范围。",
      weight: { char_fits: "它说合适的", char_love: "它有多喜欢", judged: "它看过的" },
      weightSays: { up: "加分", down: "减分", flat: "几乎不影响", unsure: "还拿不准", sure: "比较确定" },
      judgeMonth: "本月判断",
      judgeValue: (n, tokens) => `${n} 次，约 ${tokens} 个 token`,
      seconds: (n) => `${n} 秒`,
      minutes: (n) => `${n} 分钟`,
      hours: (h, m) => (m ? `${h} 小时 ${m} 分钟` : `${h} 小时`),
      errors: {
        key_required: "请粘贴 API 密钥。",
        key_again: "换了模型服务或服务地址后，需要重新粘贴这个服务的 API 密钥。",
        key_rejected: "密钥没有通过验证。请检查密钥是否完整，以及是否属于所选的服务。",
        key_malformed: "密钥里混进了其他文字或空格。请只粘贴密钥本身。",
        model_limited:
          "服务商提示请求过多或额度已用完。OpenRouter 免费模型每天限 50 次请求，于 UTC 零点重置。请稍后再试，或换一个服务。",
        model_unreachable: "暂时连不上这个模型。请检查网络、模型名称和服务地址后再试。",
        model_required: "请填写模型名称。",
        invalid_url: "请填写完整的服务地址。",
        https_required: "远程模型服务必须使用 https:// 开头的地址。",
        invalid_provider: "请从列表里选一个模型服务。",
        invalid_character: "请检查名字：不能超过 64 个字。",
        name_required: "请给它起个名字。",
        invalid_persona: "人设不能为空，也不能超过 16000 字。",
        invalid_figure: "没有这个形象，请从上面选一个。",
        busy: "还有一项操作在进行，请等它完成。",
        signin_denied: "没有在 OpenRouter 上批准。可以重新登录，或改用粘贴密钥。",
        signin_timeout: "登录没有在十分钟内完成，已失效。请重新开始。",
        signin_code_rejected: "OpenRouter 没有接受登录代码，代码可能已过期。请重新登录。",
        signin_code_invalid: "这不像 OpenRouter 给的代码。请按页面上显示的内容完整复制。",
        signin_link_invalid: "这次登录已结束，或被新的登录取代。请重新登录。",
        signin_exchange_failed: "OpenRouter 没有返回密钥。请重新登录，或改用粘贴密钥。",
        signin_unreachable: "personagent 连不上 OpenRouter 来取回密钥。请检查网络后再试。",
        signin_key_rejected: "OpenRouter 创建了密钥，但它没有通过保存前的检查。请重新登录，或改用粘贴密钥。",
        signin_provider: "只有 OpenRouter 支持账号登录。",
        desk_unsupported: "这台电脑上不支持开机自动启动。",
        desk_uvx: "用 uvx 临时运行的 personagent 没法开机启动，先正式安装它。",
        desk_shortcut_failed: "没能改好开机启动，再试一次。",
        offline: "连不上 personagent 了。请关掉它再重新打开。",
        situation_invalid: "这个值没有被接受，请从列表里选。",
        profile_invalid: "没能保存：这段内容没有被接受，改一改再试。",
        feed_action: "这一步没有被接受，刷新一下再试。",
        local_only: "这一项只能在运行 personagent 的那台电脑上改。",
        quiet_invalid: "这个开关没有改成，刷新一下再试。",
        remarks_invalid: "没能保存：刷新一下再试。",
        privacy_invalid: "没能保存：刷新一下再试。",
        privacy_unsafe: "模型服务没有加密（不是 https），不能打开。",
        privacy_no_model: "先连好模型，才能打开这个开关。",
        generic: "没有成功，请再试一次。",
      },
    },
    en: {
      title: "Settings",
      intro: "Give the character a voice, then a name and a personality.",
      modelTitle: "Model",
      modelHint: "The character thinks and talks through it.",
      noneTitle: "No model connected yet",
      noneHint: "Connect one in any of the ways below and the character can answer you.",
      answers: "Answers normally",
      answersNow: "Just checked: answers normally",
      notAnswering: "Did not answer last time",
      checking: "Checking…",
      check: "Check",
      change: "Change model",
      changeClose: "Close",
      recommended: "Recommended",
      signinTitle: "Sign in with OpenRouter",
      signinText: "Sign in to an OpenRouter account in the browser and use its free models. No key to copy.",
      signinButton: "Sign in with OpenRouter",
      signinOpening: "Opening the browser…",
      signinPending: "Waiting for approval…",
      signinWaiting: "Approve the sign-in in the browser. This page picks it up on its own.",
      signinCodeWaiting: "Open the OpenRouter page, approve there, then paste the code it shows here.",
      signinOpenPage: "Open the OpenRouter page",
      signinCodeLabel: "Code from OpenRouter",
      signinCodeUse: "Use this code",
      signinVerifying: "Approved. Checking the key…",
      signinHint:
        "OpenRouter creates a key for personagent, kept on this computer. Until you remove it at openrouter.ai/keys it can spend your OpenRouter credit; the free models need none and allow 50 requests a day.",
      cancel: "Cancel",
      or: "or",
      localFound: "{name} is running on this computer",
      localHint: "No key needed, and the chats never leave this computer.",
      localModel: "Model to use",
      useLocal: "Use {name}",
      envFound: "A {provider} key is set in {variable}",
      envHint: "Use it as it is. The key never shows on this page.",
      useEnv: "Use this key",
      keyTitle: "Paste a key",
      keyText: "Have an API key from a model service? Pick the service, paste it, and it is saved once it checks out.",
      service: "Model service",
      key: "API key",
      keyPlaceholder: "Paste the key, like sk-…",
      keyKeep: "Leave blank to keep the saved key",
      keyNone: "{name} runs on this computer and needs no key.",
      show: "Show",
      hide: "Hide",
      showKey: "Show the key",
      hideKey: "Hide the key",
      getKey: "Get a key from {name}",
      keyStays: "The key stays on this computer.",
      advanced: "Model name and address",
      modelName: "Model name",
      modelNameHelp: "Leave it to use the service's suggested model.",
      free: "free",
      address: "API address",
      addressHelp: "An OpenAI-compatible address, usually ending in /v1.",
      freeNote: "OpenRouter's free models: 50 requests a day; the model can change between requests, and some free providers keep what they receive.",
      connect: "Check and save",
      connecting: "Checking…",
      checkingKey: "Sending {name} one very short message to see that it works. This takes up to 20 seconds.",
      doneTitle: "Connected",
      doneText: "{name} can answer you now. Go and say hello.",
      it: "The character",
      toChat: "Go to Chat",
      characterTitle: "Character",
      characterHint: "What it is called and what it is like.",
      name: "Name",
      namePlaceholder: "Like Mira",
      nameHelp: "It calls itself by this name.",
      startFrom: "Start from a ready personality",
      own: "Write my own",
      persona: "What it is like",
      personaHelp: "Who it is, how it talks, what it cares about. Saving applies it at once and keeps what it has learned.",
      replaceNote: "Once saved, it becomes {title}{line}",
      replaceOwn: "What you wrote is kept as persona.txt.bak in the personagent folder.",
      backToOwn: "Keep what I wrote",
      saveCharacter: "Save",
      savingCharacter: "Saving…",
      savedCharacter: "Saved. The character restarted with it.",
      needModel: "The name and personality are saved together with the model.",
      figureTitle: "On the desktop",
      figureHint: "How it looks on your desktop. Pick one and the one on the desktop changes with it.",
      figureNow: "In use",
      computerTitle: "This computer",
      computerTitleHost: "The computer it runs on",
      startTitle: "Start when I sign in",
      startText: "When you sign in to this computer, it comes up on the desktop by itself.",
      startOther: "Another copy of personagent starts at sign-in now.",
      startMine: "Start this one instead",
      startUvx: "A copy run through uvx is temporary, so it cannot start at sign-in.",
      startUnread: "Starting at sign-in cannot be read right now. Open Settings again in a little while.",
      quietTitle: "Hide during games and fullscreen",
      quietText: "While a game, a fullscreen video or a presentation is in front, the pet hides and reading in the background pauses.",
      quietNow: { game: "Hidden now: a game is in front.", presentation: "Hidden now: a presentation is on.", fullscreen: "Hidden now: a window is fullscreen." },
      remarksTitle: "Notices what you are doing",
      remarksText:
        "It looks at the app in front and its window title, only on this computer; only the kind of activity (homework, coding, video…) is sent to your model. It stays quiet while your microphone is on.",
      ignoreLabel: "Apps never to look at",
      ignoreHelp: "The program's name, e.g. WeChat, Chrome, VS Code (as in Task Manager › Details, without .exe); on a Mac, the app's name.",
      ignoreAdd: "Add an app",
      ignoreRemove: (name) => `Remove ${name}`,
      privateTitle: "Let the character read what mail and messages say",
      privateWhere: (s) => (s.local ? `the model ${s.model} on this computer (${s.host})` : `the model ${s.model} at ${s.host}`),
      privateOff: (where) =>
        `Off: what your mail and private messages say is never sent to a model or used for recommendations; the character only tells you, on this computer, how many came and from whom. On, it would go to ${where}.`,
      privateOn: (where) =>
        `On: the sender, subject and a short excerpt of each new mail and message go to ${where}, with addresses, phone numbers, long numbers, codes and the end of links masked first.`,
      privateAsk: (where, local) =>
        `Once on, the sender, subject and up to 200 characters of each new mail and private message go to ${where}, which has to read them to answer${local ? "; it runs on this computer, so nothing leaves it" : "; the way there is encrypted with https"}. E-mail addresses, phone, card and account numbers, codes and the parameters of links are masked first; whole threads and attachments are never sent.`,
      privateYes: "Turn it on",
      privateNo: "Not now",
      privateUnsafe: (host) =>
        `It cannot be turned on: your model service ${host} uses plain http, without encryption. Mail and messages go only to a model service over https, or to a model on this computer.`,
      privateNoModel: "Connect a model first, then this can be turned on.",
      connectTitle: "Connect",
      connectHint: "The public web it wanders on its own. Here you can let it read your own places too.",
      moreTitle: "More",
      moreText: "Connecting chat apps, tools and the other advanced settings are still on the earlier settings page.",
      moreLink: "Open advanced settings",
      ago: { now: "just now", m: (n) => `${n} min ago`, h: (n) => `${n} h ago`, d: (n) => `${n} d ago` },

      whereTitle: "Sites and languages",
      whereHint: "It goes by these to choose which sites to look on and which languages to bring. Correct anything it got wrong.",
      reads: (names) => `reads ${names}`,
      listSep: ", ",
      platform: { up: "reachable", down: "unreachable", unknown: "not checked yet" },
      canRead: "I read",

      knowTitle: "What it knows about you",
      knowHint: "What it has noted about you. Lines you change or add are pinned and kept word for word when it rewrites.",
      owner: "About you",
      ownerHelp: "What you like, your habits, what you are busy with.",
      learned: "What it came to like through you",
      learnedHelp: "Three lines at most.",
      learnedOver: "Only the first three lines are kept.",
      pinnedLine: "Pinned lines",
      unpin: (line) => `Unpin: ${line}`,
      saveKnow: "Save",
      savingKnow: "Saving…",
      rewriting: "It is rewriting what it knows about you. This can take half a minute.",
      savedKnow: "Saved. It rewrote its notes once.",
      savedPlain: "Saved. Once a model is connected it works this in.",
      savedLater: "Saved. The rewrite did not go through this time; it will use this next time.",
      leans: "Sources",
      leansHelp: "Right for more of a source, left for less.",
      leansOpen: (n, all) => (n ? `Adjust each source · ${n} adjusted` : `Adjust each source (${all})`),
      less: "Less",
      more: "More",
      noSources: "There are no public sources it can read yet.",
      leansFind: "Find a source by name",
      leansLeft: (n) => `${n} more. Type a name to find one.`,
      words: "What it searches for on its walks",
      wordsHelp: "Up to 5. Press Enter to add one.",
      wordAdd: "Add a word",
      wordRemove: (word) => `Remove ${word}`,
      rules: "Never show",
      rulesEmpty: "Nothing yet. Write what you do not want under About you and it becomes a rule when it rewrites.",
      ruleSource: (name) => `Source: ${name}`,
      ruleTopic: (topic) => `Topic: ${topic}`,
      ruleRemove: (what) => `Remove "${what}"`,
      ruleSure: "Click again to remove",
      rulesHelp: "A rule that came from a line under About you comes back at the next rewrite unless that line changes too.",
      tell: (name) => `Tell ${name} what you like or what you are up to`,
      tellPlaceholder: "Like: studying for exams, into long videos that explain maths, no celebrity gossip.",
      tellSend: "Tell it",
      tellWaiting: "Thinking it over…",
      tellDone: "Noted. It rewrote what it knows about you.",
      tellKept: "Noted. Once a model is connected it works this in.",
      tellLater: "Noted. The rewrite did not go through this time; it will use this next time.",
      callsMonth: (n, judge, profile, pick, tokens) =>
        `This month: ${n} model calls for you (${judge} judging, ${profile} rewriting, ${pick} picking what to bring), ${tokens} tokens.`,
      callsNone: "No model calls for this yet this month.",

      recsTitle: "Recommendations",
      recsHint: "How the things it brings back are ordered.",
      model: "Learn my taste",
      modelText: "It learns from what you open, like and skip, and puts one or two of its own picks in every 20.",
      modelOff: "Off: a simple ranking orders things, with none of its own picks.",
      numbers: "This week in numbers",
      numbersOff: "The ranking model is off. These are from before.",
      surface: { list: "List", card: "Desktop card", chat: "Chat", other: "Other" },
      where: "Where",
      shown: "Shown",
      opened: "Opened",
      liked: "Liked",
      skipped: "Skipped",
      noShown: "Nothing was shown to you this week.",
      played: "Played in the app",
      top5: "List opens from the top 5",
      top5Value: (share, n) => `${share} (of ${n})`,
      pickLiked: "Its picks, liked",
      modelLiked: "Taste-ranked, liked",
      ofN: (rate, n) => `${rate} (${n})`,
      slots: "Its own picks",
      slotsValue: (k) => `${k} in every 20`,
      gated: "Recommended from sites it could not reach (this week)",
      fitted: "Last learned",
      fittedValue: (when, n) => `${when} · from ${n}`,
      notFitted: "Not yet",
      weights: "What it learned",
      weightsHelp: "How much each of these counts when it orders things. Further right counts for more; the light bar is how unsure it still is.",
      weight: { char_fits: "It said it fits", char_love: "How much it loved it", judged: "It looked at it" },
      weightSays: { up: "counts for", down: "counts against", flat: "hardly matters", unsure: "still unsure", sure: "fairly sure" },
      judgeMonth: "Judging this month",
      judgeValue: (n, tokens) => `${n} ${n === 1 ? "time" : "times"}, about ${tokens} tokens`,
      seconds: (n) => `${n} s`,
      minutes: (n) => `${n} min`,
      hours: (h, m) => (m ? `${h} h ${m} min` : `${h} h`),
      errors: {
        key_required: "Paste an API key.",
        key_again: "A different service or address needs its own API key. Paste the key again.",
        key_rejected: "The key was not accepted. Check that it is complete and belongs to the chosen service.",
        key_malformed: "The key holds other characters or spaces. Paste only the key itself.",
        model_limited:
          "The service reports too many requests or an exhausted quota. OpenRouter's free models allow 50 requests a day, reset at midnight UTC. Try again later or choose another service.",
        model_unreachable: "The model could not be reached. Check the network, the model name and the address, then try again.",
        model_required: "Enter a model name.",
        invalid_url: "Enter a complete API address.",
        https_required: "A remote model service needs an address starting with https://.",
        invalid_provider: "Choose a model service from the list.",
        invalid_character: "Check the name: at most 64 characters.",
        name_required: "Give it a name.",
        invalid_persona: "The persona cannot be empty or longer than 16,000 characters.",
        invalid_figure: "There is no such figure. Pick one above.",
        busy: "Something else is still running. Wait for it to finish.",
        signin_denied: "Access was not approved on OpenRouter. Sign in again or paste a key.",
        signin_timeout: "The sign-in was not finished within ten minutes and has expired. Start it again.",
        signin_code_rejected: "OpenRouter did not accept the sign-in code; it may have expired. Sign in again.",
        signin_code_invalid: "That does not look like a code from OpenRouter. Copy it as the page shows it.",
        signin_link_invalid: "This sign-in has ended or was replaced. Sign in again.",
        signin_exchange_failed: "OpenRouter did not return a key. Sign in again, or paste a key.",
        signin_unreachable: "personagent could not reach OpenRouter to collect the key. Check the network and try again.",
        signin_key_rejected: "OpenRouter created a key, but it did not pass the check before saving. Sign in again, or paste a key.",
        signin_provider: "Signing in works with OpenRouter only.",
        desk_unsupported: "Starting at sign-in is not supported on this computer.",
        desk_uvx: "A personagent run through uvx cannot start at sign-in. Install it first.",
        desk_shortcut_failed: "Starting at sign-in could not be changed. Try again.",
        offline: "personagent cannot be reached. Close it and open it again.",
        situation_invalid: "That value was not accepted. Pick one from the list.",
        profile_invalid: "Not saved: that text was not accepted. Change it and try again.",
        feed_action: "That step was not accepted. Refresh and try again.",
        local_only: "This can only be changed on the computer personagent runs on.",
        quiet_invalid: "The switch was not changed. Refresh and try again.",
        remarks_invalid: "Not saved. Refresh and try again.",
        privacy_invalid: "Not saved. Refresh and try again.",
        privacy_unsafe: "The model service is not encrypted (not https), so this cannot be turned on.",
        privacy_no_model: "Connect a model first, then this can be turned on.",
        generic: "That did not work. Try once more.",
      },
    },
  };
  // How often a sign-in waiting in the browser is asked after.
  const SIGNIN_POLL_MS = 1500;
  const SVG = "http://www.w3.org/2000/svg";
  const ICONS = {
    check: "M5 12.5l4.2 4.2L19 7",
    eye: "M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z",
    eyeOff: "M3.5 3.5l17 17M10.6 5.6A10 10 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.9 3.7M6.4 6.9C3.9 8.6 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9.6 9.6 0 0 0 4.3-1M9.9 9.9a2.8 2.8 0 0 0 4.2 4.2",
    out: "M14 4.5h5.5V10M19.5 4.5L11 13M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10",
    arrow: "M5 12h14M13 6l6 6-6 6",
    chevron: "M9 6l6 6-6 6",
    chip: "M8 3.5v3M16 3.5v3M8 17.5v3M16 17.5v3M3.5 8h3M3.5 16h3M17.5 8h3M17.5 16h3M7.5 6.5h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z",
    key: "M14.5 9.5a4.5 4.5 0 1 1-1.3-3.2 4.5 4.5 0 0 1 1.3 3.2zM12.7 12.7L20 20M17 17l2-2M15 15l2-2",
    pen: "M4.5 19.5l1-4.2L15.8 5a2 2 0 0 1 2.9 0l.3.3a2 2 0 0 1 0 2.9L8.7 18.5zM13.5 7.3l3.2 3.2",
    spark: "M12 3.5l1.9 5.6 5.6 1.9-5.6 1.9L12 18.5l-1.9-5.6-5.6-1.9 5.6-1.9z",
    cross: "M6.5 6.5l11 11M17.5 6.5l-11 11",
    question: "M9.3 9.2a2.8 2.8 0 1 1 3.8 2.6c-.7.3-1.1.9-1.1 1.6v.3M12 17h.01",
    dots: "M5.5 12h.01M12 12h.01M18.5 12h.01",
    refresh: "M19.5 11A7.6 7.6 0 0 0 5.6 7.4M5 4v3.8h3.8M4.5 13a7.6 7.6 0 0 0 13.9 3.6M19 20v-3.8h-3.8",
    pin: "M12 16.5v5M9 4h6M10 4v5.2l-3 3.3v1.5h10v-1.5l-3-3.3V4",
    lock: "M6.5 10.5h11a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1zM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5",
    ban: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM6 6l12 12",
    tag: "M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1.4 1.4 0 0 1 0 2l-6.2 6.2a1.4 1.4 0 0 1-2 0zM8 8h.01",
  };

  let ctx, t, lang;
  let state = null;
  let catalog = null;
  let root;
  // The parts, each a section of the page.
  const parts = {};

  // ------------------------------------------------------------- helpers --

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(name, cls = "setup-icon") {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls);
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", ICONS[name]);
    svg.append(path);
    return svg;
  }
  function fill(text, values = {}) {
    return text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
  }
  // A failed fetch has no code of its own: the app itself is gone.
  function say(error) {
    const code = error instanceof TypeError ? "offline" : error?.message || error;
    return t.errors[code] || t.errors.generic;
  }
  function button(cls, text, onClick) {
    const node = el("button", `setup-button ${cls}`);
    node.type = "button";
    const label = el("span", "setup-button-label", text);
    node.append(label);
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }
  function relabel(node, text) {
    node.querySelector(".setup-button-label").textContent = text;
  }
  // Busy: the button keeps its size, shows a spinner and its new words, and takes no clicks.
  function busy(node, on, text) {
    node.disabled = on;
    node.classList.toggle("setup-busy", on);
    node.setAttribute("aria-busy", String(on));
    if (text !== undefined) relabel(node, text);
  }
  let fieldCount = 0;
  // A label above the control, help under it, and the error under that, tied by aria.
  function field(label, control, help = "") {
    const id = `setup-field-${++fieldCount}`;
    const wrap = el("div", "setup-field");
    const head = el("div", "setup-label-row");
    const name = el("label", "setup-label", label);
    name.htmlFor = id;
    head.append(name);
    control.id = id;
    const helpLine = el("p", "setup-help", help);
    helpLine.id = `${id}-help`;
    helpLine.hidden = !help;
    const error = el("p", "setup-error");
    error.id = `${id}-error`;
    error.hidden = true;
    error.setAttribute("role", "alert");
    wrap.append(head, control, helpLine, error);
    const described = () =>
      [!helpLine.hidden && helpLine.id, !error.hidden && error.id].filter(Boolean).join(" ");
    const target = control.matches("input, textarea, select") ? control : control.querySelector("input, textarea, select");
    target.setAttribute("aria-describedby", described());
    return {
      wrap,
      head,
      label: name,
      control: target,
      help(text) {
        helpLine.replaceChildren();
        if (typeof text === "string") helpLine.textContent = text;
        else if (text) helpLine.append(...text);
        helpLine.hidden = !text || (typeof text === "string" && !text);
        target.setAttribute("aria-describedby", described());
      },
      error(text) {
        error.textContent = text || "";
        error.hidden = !text;
        target.setAttribute("aria-invalid", String(Boolean(text)));
        target.setAttribute("aria-describedby", described());
      },
    };
  }
  function input(cls = "") {
    const node = el("input", `setup-input ${cls}`.trim());
    node.type = "text";
    node.autocomplete = "off";
    node.spellcheck = false;
    return node;
  }
  function section(key, title, hint) {
    const node = el("section", `setup-section setup-section-${key}`);
    node.dataset.part = key;
    const head = el("header", "setup-section-head");
    const heading = el("h2", "setup-section-title", title);
    heading.id = `setup-title-${key}`;
    heading.tabIndex = -1;
    node.setAttribute("aria-labelledby", heading.id);
    head.append(heading);
    if (hint) head.append(el("p", "setup-section-hint", hint));
    node.append(head);
    return node;
  }
  const pick = (pair) => (lang === "zh" ? pair[1] : pair[0]);
  const providerSpec = (id) => catalog?.providers.find((p) => p.id === id);
  const characterSpec = (id) => catalog?.characters.find((c) => c.id === id);
  function providerName(id) {
    const spec = providerSpec(id);
    if (id === "other" && state?.baseUrl) {
      try {
        return new URL(state.baseUrl).host;
      } catch {
        return state.baseUrl;
      }
    }
    return spec ? pick(spec.name) : id;
  }
  // "Dry-witted friend: deadpan, short replies" -> its title, and what it is like.
  function characterWords(id) {
    const label = characterSpec(id) ? pick(characterSpec(id).name) : "";
    const [title, ...rest] = label.split(/[:：]/);
    return { title: title.trim(), line: rest.join(":").trim() };
  }
  // The character's language: the saved one once set up, else the page's.
  const speaks = () => (state?.configured && state.lang) || lang;

  // The earlier page, with the token and the window's key as the app passes them on.
  function classicUrl() {
    const pass = new URLSearchParams();
    const token = sessionStorage.getItem("personagent-setup-token") || "";
    const frame = sessionStorage.getItem("personagent-frame") || "";
    if (token) pass.set("token", token);
    if (frame) pass.set("frame", frame);
    const hash = pass.toString();
    return hash ? `/classic#${hash}` : "/classic";
  }

  // =============================================================== model ==

  const model = {
    // What the last check found: null before any, else {ok, error, now}.
    checked: null,
    checking: false,
    // Connected during this visit: the page says so and points to Chat.
    done: false,
    open: false,
    working: "",
    signin: { phase: "idle", error: "", url: "", byCode: false, timer: 0 },
    found: null,
  };

  function buildModel() {
    const node = section("model", t.modelTitle, t.modelHint);

    // What is connected now.
    const status = el("div", "setup-status");
    const dot = el("span", "setup-status-dot");
    const words = el("div", "setup-status-words");
    const statusTitle = el("p", "setup-status-title");
    const statusLine = el("p", "setup-status-line");
    statusLine.setAttribute("aria-live", "polite");
    words.append(statusTitle, statusLine);
    const actions = el("div", "setup-status-actions");
    const checkButton = button("setup-button-secondary setup-button-sm", t.check, runCheck);
    const changeButton = button("setup-button-ghost setup-button-sm", t.change, () => {
      model.open = !model.open;
      model.done = false;
      renderModel();
      if (model.open) parts.signinButton.focus();
    });
    changeButton.setAttribute("aria-controls", "setup-ways");
    actions.append(checkButton, changeButton);
    status.append(dot, words, actions);
    const statusWhy = el("p", "setup-error setup-status-why");
    statusWhy.setAttribute("role", "alert");
    statusWhy.hidden = true;

    // Connected during this visit.
    const done = el("div", "setup-done");
    done.setAttribute("role", "status");
    const doneMark = el("span", "setup-done-mark");
    doneMark.append(icon("check"));
    const doneWords = el("div", "setup-done-words");
    const doneTitle = el("p", "setup-done-title", t.doneTitle);
    const doneText = el("p", "setup-done-text");
    doneWords.append(doneTitle, doneText);
    const toChat = button("setup-button-primary", t.toChat, () => ctx.go("chat"));
    toChat.append(icon("arrow"));
    done.append(doneMark, doneWords, toChat);

    const ways = el("div", "setup-ways");
    ways.id = "setup-ways";
    ways.append(buildSignin(), orLine(), buildFound(), buildKey());

    node.append(status, statusWhy, done, ways);
    Object.assign(parts, { status, dot, statusTitle, statusLine, statusWhy, checkButton, changeButton, done, doneText, ways });
    return node;
  }

  function orLine() {
    const line = el("div", "setup-or");
    line.append(el("span", "setup-or-word", t.or));
    return line;
  }

  // ---- (a) Sign in with OpenRouter: the browser approves, the server keeps the key.
  function buildSignin() {
    const box = el("div", "setup-way setup-way-signin");
    const head = el("div", "setup-way-head");
    const mark = el("span", "setup-way-mark");
    mark.append(icon("spark"));
    const titles = el("div", "setup-way-titles");
    const title = el("h3", "setup-way-title", t.signinTitle);
    title.append(el("span", "setup-badge", t.recommended));
    titles.append(title, el("p", "setup-way-text", t.signinText));
    head.append(mark, titles);

    const row = el("div", "setup-way-actions");
    const go = button("setup-button-primary setup-button-lg", t.signinButton, signinClicked);
    const cancel = button("setup-button-secondary", t.cancel, signinCancel);
    row.append(go, cancel);

    const waiting = el("p", "setup-signin-waiting");
    waiting.setAttribute("aria-live", "polite");
    const open = el("a", "setup-link");
    open.target = "_blank";
    open.rel = "noopener noreferrer";
    open.append(el("span", "", t.signinOpenPage), icon("out", "setup-icon setup-icon-sm"));

    // From another device the browser cannot come back here: the person pastes the code.
    const codeForm = el("form", "setup-signin-code");
    codeForm.noValidate = true;
    const codeInput = input();
    const codeField = field(t.signinCodeLabel, codeInput);
    const codeUse = button("setup-button-primary", t.signinCodeUse);
    codeUse.type = "submit";
    const codeRow = el("div", "setup-inline");
    codeRow.append(codeField.wrap, codeUse);
    codeForm.append(codeRow);
    codeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const code = codeInput.value.trim();
      if (!code) return codeInput.focus();
      busy(codeUse, true);
      codeField.error("");
      try {
        signinFollow(await ctx.api("signin/code", { code }));
        codeInput.value = "";
      } catch (error) {
        codeField.error(say(error));
      } finally {
        busy(codeUse, false);
      }
    });

    const error = el("p", "setup-error setup-way-error");
    error.setAttribute("role", "alert");
    const hint = el("p", "setup-fine", t.signinHint);
    box.append(head, row, waiting, open, codeForm, error, hint);
    Object.assign(parts, {
      signinBox: box,
      signinButton: go,
      signinCancel: cancel,
      signinWaiting: waiting,
      signinOpen: open,
      signinCode: codeForm,
      signinError: error,
    });
    return box;
  }

  function renderSignin() {
    const s = model.signin;
    const waiting = s.phase === "waiting";
    const verifying = s.phase === "verifying";
    const opening = s.phase === "opening";
    busy(parts.signinButton, opening || waiting || verifying,
      opening ? t.signinOpening : waiting || verifying ? t.signinPending : t.signinButton);
    // Another way being checked leaves it unclickable, without a spinner of its own.
    if (model.working) parts.signinButton.disabled = true;
    parts.signinCancel.hidden = !waiting;
    parts.signinWaiting.hidden = !(waiting || verifying);
    parts.signinWaiting.textContent = verifying ? t.signinVerifying : s.byCode ? t.signinCodeWaiting : t.signinWaiting;
    parts.signinOpen.hidden = !(waiting && s.url);
    if (waiting && s.url) parts.signinOpen.href = s.url;
    parts.signinCode.hidden = !(waiting && s.byCode);
    parts.signinError.hidden = s.phase !== "failed";
    parts.signinError.textContent = s.phase === "failed" ? say(s.error) : "";
  }

  function signinFollow(value) {
    const s = model.signin;
    s.phase = value.state === "idle" ? (s.phase === "opening" ? "opening" : "idle") : value.state;
    s.error = value.error || "";
    s.url = value.url || "";
    s.byCode = Boolean(value.byCode);
    const polling = s.phase === "waiting" || s.phase === "verifying";
    if (polling && !s.timer) s.timer = setInterval(signinPoll, SIGNIN_POLL_MS);
    if (!polling && s.timer) {
      clearInterval(s.timer);
      s.timer = 0;
    }
    // The server keeps a finished attempt until the page has seen it.
    if (s.phase === "done" || s.phase === "failed") ctx.api("signin/cancel", {}).catch(() => {});
    if (s.phase === "done") return signinDone();
    renderSignin();
  }

  async function signinPoll() {
    try {
      signinFollow(await ctx.api("signin"));
    } catch {
      // The next tick asks again.
    }
  }

  async function signinClicked() {
    model.signin.phase = "opening";
    model.signin.error = "";
    renderSignin();
    const form = characterValues();
    // The model already chosen at OpenRouter stays; otherwise the service's own default.
    if (state?.provider === "openrouter" && state.configured && state.model) form.model = state.model;
    try {
      signinFollow(await ctx.api("signin/start", { provider: "openrouter", form, pageLang: lang }));
    } catch (error) {
      model.signin.phase = "failed";
      model.signin.error = error instanceof TypeError ? "offline" : error.message;
      renderSignin();
    }
  }

  async function signinCancel() {
    busy(parts.signinCancel, true);
    try {
      signinFollow(await ctx.api("signin/cancel", {}));
    } catch {
      // Still waiting: the next poll says so.
    } finally {
      busy(parts.signinCancel, false);
    }
  }

  async function signinDone() {
    model.signin.phase = "idle";
    try {
      state = await ctx.api("state");
    } catch {
      // The next look at the page reads it again.
    }
    await afterConnect();
  }

  // ---- (b) What this computer already has: a local model running, a key in the environment.
  function buildFound() {
    const box = el("div", "setup-found");
    box.hidden = true;
    parts.found = box;
    return box;
  }

  function renderFound() {
    const box = parts.found;
    const found = model.found;
    box.replaceChildren();
    if (!found) {
      box.hidden = true;
      return;
    }
    for (const row of found.local) box.append(localRow(row));
    for (const row of found.keys) box.append(envRow(row));
    box.hidden = !box.children.length;
  }

  function localRow(row) {
    const item = el("div", "setup-way setup-way-found");
    const head = el("div", "setup-way-head");
    const mark = el("span", "setup-way-mark setup-way-mark-quiet");
    mark.append(icon("chip"));
    const titles = el("div", "setup-way-titles");
    titles.append(
      el("h3", "setup-way-title", fill(t.localFound, { name: row.name })),
      el("p", "setup-way-text", t.localHint),
    );
    head.append(mark, titles);
    const actions = el("div", "setup-way-actions setup-way-actions-found");
    let choice = null;
    if (row.models.length > 1) {
      choice = el("select", "setup-input setup-select");
      for (const name of row.models) choice.append(new Option(name, name));
      const pickField = field(t.localModel, choice);
      pickField.wrap.classList.add("setup-field-compact");
      actions.append(pickField.wrap);
    } else {
      actions.append(el("span", "setup-model-tag", row.models[0]));
    }
    const use = button("setup-button-secondary", fill(t.useLocal, { name: row.name }), () =>
      connect(
        {
          provider: row.provider,
          baseUrl: row.baseUrl,
          model: choice ? choice.value : row.models[0],
          // A local server takes any key; the form of another service asks for one.
          apiKey: row.provider === "ollama" ? "" : row.id,
        },
        `local-${row.id}`,
      ),
    );
    use.dataset.way = `local-${row.id}`;
    actions.append(use);
    const error = el("p", "setup-error setup-way-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    error.dataset.way = `local-${row.id}`;
    item.append(head, actions, error);
    return item;
  }

  function envRow(row) {
    const item = el("div", "setup-way setup-way-found");
    const head = el("div", "setup-way-head");
    const mark = el("span", "setup-way-mark setup-way-mark-quiet");
    mark.append(icon("key"));
    const titles = el("div", "setup-way-titles");
    titles.append(
      el("h3", "setup-way-title", fill(t.envFound, { provider: providerName(row.provider), variable: row.variable })),
      el("p", "setup-way-text", t.envHint),
    );
    head.append(mark, titles);
    const actions = el("div", "setup-way-actions");
    const spec = providerSpec(row.provider);
    const use = button("setup-button-secondary", t.useEnv, () =>
      connect(
        { provider: row.provider, apiKey: "", apiKeyFrom: row.variable, baseUrl: spec.baseUrl, model: spec.model },
        `env-${row.variable}`,
      ),
    );
    use.dataset.way = `env-${row.variable}`;
    actions.append(use);
    const error = el("p", "setup-error setup-way-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    error.dataset.way = `env-${row.variable}`;
    item.append(head, actions, error);
    return item;
  }

  // ---- (c) Paste a key: choose the service, paste, check and save.
  function buildKey() {
    const box = el("form", "setup-way setup-way-key");
    box.noValidate = true;
    const head = el("div", "setup-way-head");
    const mark = el("span", "setup-way-mark setup-way-mark-quiet");
    mark.append(icon("key"));
    const titles = el("div", "setup-way-titles");
    titles.append(el("h3", "setup-way-title", t.keyTitle), el("p", "setup-way-text", t.keyText));
    head.append(mark, titles);

    const service = el("select", "setup-input setup-select");
    for (const spec of catalog.providers) service.append(new Option(pick(spec.name), spec.id));
    const serviceField = field(t.service, service);

    const keyBox = el("div", "setup-secret");
    const key = input("setup-secret-input");
    key.type = "password";
    key.placeholder = t.keyPlaceholder;
    const reveal = el("button", "setup-reveal");
    reveal.type = "button";
    reveal.setAttribute("aria-pressed", "false");
    const paintReveal = () => {
      const shown = key.type === "text";
      reveal.replaceChildren(icon(shown ? "eyeOff" : "eye"), el("span", "", shown ? t.hide : t.show));
      reveal.setAttribute("aria-label", shown ? t.hideKey : t.showKey);
      reveal.setAttribute("aria-pressed", String(shown));
    };
    reveal.addEventListener("click", () => {
      key.type = key.type === "password" ? "text" : "password";
      paintReveal();
      key.focus();
    });
    paintReveal();
    keyBox.append(key, reveal);
    const keyField = field(t.key, keyBox);
    const getKey = el("a", "setup-link setup-link-head");
    getKey.target = "_blank";
    getKey.rel = "noopener noreferrer";
    keyField.head.append(getKey);

    const more = el("details", "setup-fold");
    const summary = el("summary", "setup-fold-summary");
    summary.append(icon("chevron", "setup-icon setup-fold-chevron"), el("span", "", t.advanced));
    const modelInput = input();
    const models = el("datalist");
    models.id = "setup-model-list";
    modelInput.setAttribute("list", models.id);
    const modelField = field(t.modelName, modelInput, t.modelNameHelp);
    const base = input();
    base.inputMode = "url";
    const baseField = field(t.address, base, t.addressHelp);
    const foldBody = el("div", "setup-fold-body");
    foldBody.append(modelField.wrap, models, baseField.wrap);
    more.append(summary, foldBody);

    const foot = el("div", "setup-way-actions");
    const save = button("setup-button-primary", t.connect);
    save.type = "submit";
    save.dataset.way = "key";
    const progress = el("p", "setup-progress");
    progress.setAttribute("aria-live", "polite");
    foot.append(save, progress);
    const error = el("p", "setup-error setup-way-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    error.dataset.way = "key";

    box.append(head, serviceField.wrap, keyField.wrap, more, foot, error);

    service.addEventListener("change", () => serviceChanged(true));
    modelInput.addEventListener("input", freeNote);
    key.addEventListener("input", () => keyField.error(""));
    modelInput.addEventListener("input", () => modelField.error(""));
    base.addEventListener("input", () => baseField.error(""));
    box.addEventListener("submit", (event) => {
      event.preventDefault();
      keySubmit();
    });

    Object.assign(parts, {
      keyForm: box,
      service,
      key,
      keyField,
      keyReveal: reveal,
      getKey,
      fold: more,
      modelInput,
      modelField,
      modelList: models,
      base,
      baseField,
      keySave: save,
      keyProgress: progress,
    });
    return box;
  }

  // A new service brings its own address, model and page for keys.
  function serviceChanged(reset) {
    const spec = providerSpec(parts.service.value);
    const saved = state?.configured && parts.service.value === state.provider;
    parts.modelInput.value = reset && !saved ? spec.model : state?.model || spec.model;
    parts.base.value = reset && !saved ? spec.baseUrl : state?.baseUrl || spec.baseUrl;
    parts.base.placeholder = spec.id === "other" ? "https://…/v1" : "";
    const local = spec.id === "ollama";
    parts.key.disabled = local;
    parts.key.value = "";
    parts.key.placeholder = local ? "" : saved ? t.keyKeep : t.keyPlaceholder;
    parts.keyField.help(local ? fill(t.keyNone, { name: pick(spec.name) }) : t.keyStays);
    parts.getKey.hidden = !spec.keyUrl;
    if (spec.keyUrl) {
      parts.getKey.href = spec.keyUrl;
      parts.getKey.replaceChildren(el("span", "", fill(t.getKey, { name: pick(spec.name).split(/[（(]/)[0].trim() })), icon("out", "setup-icon setup-icon-sm"));
    }
    // A service with no address of its own, or one on this computer, needs the fold open.
    if (spec.id === "other" || local) parts.fold.open = true;
    for (const f of [parts.keyField, parts.modelField, parts.baseField]) f.error("");
    wayError("key", "");
    freeNote();
    fillModelList();
  }

  function freeNote() {
    parts.modelField.help(parts.modelInput.value.trim() === "openrouter/free" ? t.freeNote : t.modelNameHelp);
  }

  // The saved service's own list of models, for the model field to offer.
  let modelListing = null;
  async function fillModelList() {
    parts.modelList.replaceChildren();
    if (!state?.configured || parts.service.value !== state.provider) return;
    if (!modelListing) {
      try {
        modelListing = (await ctx.api("models")).models || [];
      } catch {
        modelListing = [];
      }
    }
    for (const row of modelListing) {
      const option = new Option(row.free ? `${row.id} · ${t.free}` : row.id, row.id);
      parts.modelList.append(option);
    }
  }

  function keySubmit() {
    const spec = providerSpec(parts.service.value);
    const saved = state?.configured && spec.id === state.provider;
    if (spec.id !== "ollama" && !saved && !parts.key.value.trim()) {
      parts.keyField.error(t.errors.key_required);
      parts.key.focus();
      return;
    }
    connect(
      { provider: spec.id, apiKey: parts.key.value.trim(), baseUrl: parts.base.value.trim(), model: parts.modelInput.value.trim() },
      "key",
    );
  }

  // Where a code from the save belongs: under its field, else under the way's button.
  function placeError(where, code, text) {
    if (where === "key") {
      if (["key_required", "key_again", "key_rejected", "key_malformed"].includes(code)) {
        parts.keyField.error(text);
        parts.key.focus();
        return;
      }
      if (code === "model_required") {
        parts.fold.open = true;
        parts.modelField.error(text);
        parts.modelInput.focus();
        return;
      }
      if (["invalid_url", "https_required"].includes(code)) {
        parts.fold.open = true;
        parts.baseField.error(text);
        parts.base.focus();
        return;
      }
    }
    if (["name_required", "invalid_character"].includes(code)) {
      character.nameField.error(text);
      parts.character.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    wayError(where, text);
  }

  function wayError(where, text) {
    for (const node of root.querySelectorAll(`.setup-way-error[data-way="${where}"]`)) {
      node.textContent = text;
      node.hidden = !text;
    }
  }

  // Every way ends in the save the earlier page made: the service, the key, and the character as it stands.
  async function connect(payload, where) {
    if (model.working) return;
    model.working = where;
    wayError(where, "");
    for (const f of [parts.keyField, parts.modelField, parts.baseField]) f.error("");
    renderWorking();
    try {
      state = await ctx.api("config", { ...characterValues(), ...payload });
      if (where === "key") parts.key.value = "";
      await afterConnect();
    } catch (error) {
      const code = error instanceof TypeError ? "offline" : error.message;
      placeError(where, code, say(code));
    } finally {
      model.working = "";
      renderWorking();
    }
  }

  async function afterConnect() {
    model.done = true;
    model.open = false;
    model.checked = { ok: true, now: true };
    modelListing = null;
    // Text written here before there was a model is saved once there is one.
    if (character.picked === "custom" && personaEdited()) {
      try {
        state = await ctx.api("persona", { text: character.persona.value });
      } catch (error) {
        character.personaField.error(say(error));
      }
    }
    await loadPersona(true);
    ctx.changed();
    renderModel();
    renderCharacter();
    parts.done.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderWorking() {
    const where = model.working;
    for (const node of parts.ways.querySelectorAll("button[data-way]")) {
      const mine = node.dataset.way === where;
      node.disabled = Boolean(where);
      node.classList.toggle("setup-busy", mine);
      node.setAttribute("aria-busy", String(mine));
    }
    relabel(parts.keySave, where === "key" ? t.connecting : t.connect);
    const spec = providerSpec(parts.service.value);
    parts.keyProgress.textContent = where === "key" ? fill(t.checkingKey, { name: pick(spec.name) }) : "";
    for (const node of [parts.service, parts.key, parts.modelInput, parts.base]) node.readOnly = where === "key";
    parts.service.disabled = where === "key";
    renderSignin();
  }

  async function runCheck() {
    if (model.checking) return;
    model.checking = true;
    renderModel();
    try {
      const value = await ctx.api("look/check", {});
      model.checked = { ok: value.ok, error: value.error, now: true };
    } catch (error) {
      model.checked = { ok: false, error: error instanceof TypeError ? "offline" : error.message, now: true };
    } finally {
      model.checking = false;
      renderModel();
    }
  }

  function renderModel() {
    const on = Boolean(state?.configured);
    const failing = model.checked ? !model.checked.ok : Boolean(state?.agentRunning && state?.modelUnreachable);
    parts.status.classList.toggle("setup-status-on", on && !failing);
    parts.status.classList.toggle("setup-status-bad", on && failing);
    parts.status.classList.toggle("setup-status-off", !on);
    if (on) {
      parts.statusTitle.replaceChildren(
        el("span", "setup-status-service", providerName(state.provider)),
        el("span", "setup-status-sep", "·"),
        el("span", "setup-status-model", state.model),
      );
      parts.statusLine.textContent = model.checking
        ? t.checking
        : failing
          ? t.notAnswering
          : model.checked
            ? t.answersNow
            : t.answers;
    } else {
      parts.statusTitle.textContent = t.noneTitle;
      parts.statusLine.textContent = t.noneHint;
    }
    // Why a check failed, in full, under the short line.
    const why = on && !model.checking && model.checked && !model.checked.ok ? say(model.checked.error) : "";
    parts.statusWhy.textContent = why;
    parts.statusWhy.hidden = !why;
    parts.status.classList.toggle("setup-status-checking", model.checking);
    parts.checkButton.hidden = !on;
    busy(parts.checkButton, model.checking, model.checking ? t.checking : t.check);
    parts.changeButton.hidden = !on || model.done;
    relabel(parts.changeButton, model.open ? t.changeClose : t.change);
    parts.changeButton.setAttribute("aria-expanded", String(model.open));
    parts.done.hidden = !(on && model.done);
    if (on) parts.doneText.textContent = fill(t.doneText, { name: state.name || t.it });
    parts.ways.hidden = on && !model.open;
    renderSignin();
  }

  // =========================================================== character ==

  const character = {
    // The ready personality picked here, or "custom" for text of one's own.
    picked: "custom",
    // The persona as last loaded; edits are compared with it.
    shown: null,
    saving: false,
    justSaved: false,
  };

  function buildCharacter() {
    const node = section("character", t.characterTitle, t.characterHint);
    const name = input();
    name.maxLength = 64;
    name.placeholder = t.namePlaceholder;
    const nameField = field(t.name, name, t.nameHelp);
    nameField.wrap.classList.add("setup-field-name");
    name.addEventListener("input", () => {
      nameField.error("");
      renderCharacter();
    });

    const chipsField = el("div", "setup-field");
    const chipsLabel = el("p", "setup-label", t.startFrom);
    chipsLabel.id = "setup-chips-label";
    const chips = el("div", "setup-chips");
    chips.setAttribute("role", "radiogroup");
    chips.setAttribute("aria-labelledby", chipsLabel.id);
    chipsField.append(chipsLabel, chips);

    const persona = el("textarea", "setup-input setup-textarea");
    persona.rows = 7;
    persona.spellcheck = false;
    const personaField = field(t.persona, persona, t.personaHelp);
    const count = el("span", "setup-count");
    personaField.head.append(count);
    persona.addEventListener("input", () => {
      personaField.error("");
      // Writing in the box makes the character one's own.
      character.picked = "custom";
      renderCharacter();
    });

    // A ready personality picked: its text is the server's, so the page says what changes instead.
    const swap = el("div", "setup-swap");
    const swapText = el("p", "setup-swap-text");
    const swapOwn = el("p", "setup-swap-own", t.replaceOwn);
    const swapBack = el("button", "setup-button setup-button-link", t.backToOwn);
    swapBack.type = "button";
    swapBack.addEventListener("click", () => {
      character.picked = "custom";
      renderCharacter();
      persona.focus();
    });
    swap.append(swapText, swapOwn, swapBack);

    const foot = el("div", "setup-foot");
    const save = button("setup-button-primary", t.saveCharacter, saveCharacter);
    const note = el("p", "setup-foot-note");
    note.setAttribute("aria-live", "polite");
    foot.append(save, note);
    const error = el("p", "setup-error");
    error.setAttribute("role", "alert");
    error.hidden = true;

    node.append(nameField.wrap, chipsField, personaField.wrap, swap, foot, error);
    Object.assign(character, { name, nameField, chips, persona, personaField, count, swap, swapText, swapOwn, save, note, error });
    return node;
  }

  function buildChips() {
    // "Write it later" is the basic character the box already holds: "Write my own" covers it.
    const ids = ["custom", ...catalog.characters.map((c) => c.id).filter((id) => id !== "template")];
    character.chips.replaceChildren();
    for (const id of ids) {
      const chip = el("button", "setup-chip");
      chip.type = "button";
      chip.setAttribute("role", "radio");
      chip.dataset.id = id;
      const spec = characterSpec(id);
      if (spec?.avatar) {
        const face = el("span", "setup-chip-face");
        const img = el("img");
        img.alt = "";
        img.src = spec.avatar;
        face.append(img);
        chip.append(face);
      } else if (id === "custom") {
        chip.append(icon("pen", "setup-icon setup-chip-icon"));
      } else {
        chip.append(el("span", "setup-chip-letter", Array.from(characterWords(id).title)[0] || ""));
      }
      const words = characterWords(id);
      chip.append(el("span", "setup-chip-name", id === "custom" ? t.own : words.title));
      if (words.line) chip.title = words.line;
      chip.addEventListener("click", () => choose(id));
      chip.addEventListener("keydown", chipKeys);
      character.chips.append(chip);
    }
  }

  // Arrow keys move through the chips, as in any group of choices.
  function chipKeys(event) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const all = [...character.chips.children];
    const next = all[(all.indexOf(event.currentTarget) + step + all.length) % all.length];
    next.focus();
    choose(next.dataset.id);
  }

  function choose(id) {
    const before = character.picked;
    character.picked = id;
    // A name nobody chose follows the character; a typed one stays.
    const field = character.name;
    const current = field.value.trim();
    const ownName = (spec) => (spec?.defaultNames ? spec.defaultNames[speaks()] || spec.defaultNames.en : "");
    const someones = catalog.characters.flatMap((c) => (c.defaultNames ? Object.values(c.defaultNames) : []));
    const next = ownName(characterSpec(id));
    if (next && (!current || someones.includes(current))) field.value = next;
    if (id === "custom" && before !== "custom" && someones.includes(current) && state?.name) field.value = state.name;
    // Back on the saved character: the box shows its text as it was.
    if (id === state?.character && character.shown !== null) character.persona.value = character.shown;
    renderCharacter();
  }

  const personaEdited = () => character.shown !== null && character.persona.value.trim() !== character.shown;
  // A name or a ready personality goes through the save the model part uses; text of one's own alone does not.
  function characterChanges() {
    const name = character.name.value.trim() !== (state?.name || "");
    const ready = character.picked !== "custom" && character.picked !== state?.character;
    const text = character.picked === "custom" && personaEdited();
    return { name, ready, text, config: name || ready };
  }

  // The character's part of the save /api/config takes.
  function characterValues() {
    const changes = characterChanges();
    const picked = character.picked;
    const id = picked !== "custom" ? picked : changes.text ? "custom" : state?.character || "custom";
    let avatar = state?.avatar || "";
    // A portrait goes with a ready personality, unless the person's own picture is in use.
    if (changes.ready && avatar !== "own") avatar = characterSpec(picked)?.avatar ? picked : "";
    return { name: character.name.value.trim(), character: id, avatar, lang: speaks() };
  }

  async function saveCharacter() {
    if (character.saving) return;
    const changes = characterChanges();
    if (!changes.config && !changes.text) return;
    character.saving = true;
    character.justSaved = false;
    character.error.hidden = true;
    renderCharacter();
    try {
      if (changes.config) {
        if (!character.name.value.trim()) throw new Error("name_required");
        // The saved service and key stay; the save checks the model once more and restarts the character.
        state = await ctx.api("config", {
          provider: state.provider,
          apiKey: "",
          baseUrl: state.baseUrl,
          model: state.model,
          ...characterValues(),
        });
      }
      if (changes.text) state = await ctx.api("persona", { text: character.persona.value });
      await loadPersona(true);
      ctx.changed();
      character.justSaved = true;
      renderModel();
    } catch (error) {
      const code = error instanceof TypeError ? "offline" : error.message;
      if (["name_required", "invalid_character"].includes(code)) character.nameField.error(say(code));
      else if (code === "invalid_persona") character.personaField.error(say(code));
      else {
        character.error.textContent = say(code);
        character.error.hidden = false;
      }
    } finally {
      character.saving = false;
      renderCharacter();
    }
  }

  async function loadPersona(again = false) {
    // Unsaved edits stay when the page is opened again.
    if (!again && character.shown !== null && personaEdited()) return;
    try {
      const { text } = await ctx.api("persona");
      character.shown = text.trim();
      character.persona.value = character.shown;
      character.picked = state?.character && state.character !== "template" ? state.character : "custom";
      if (character.picked !== "custom" && !characterSpec(character.picked)) character.picked = "custom";
    } catch (error) {
      character.personaField.error(say(error));
    }
    character.name.value = state?.name || "";
    renderCharacter();
  }

  function renderCharacter() {
    const picked = character.picked;
    for (const chip of character.chips.children) {
      const on = chip.dataset.id === picked;
      chip.setAttribute("aria-checked", String(on));
      chip.tabIndex = on ? 0 : -1;
    }
    // The saved ready character shows its text; another one, not saved yet, says what saving does.
    const swapping = picked !== "custom" && picked !== state?.character;
    character.personaField.wrap.hidden = swapping;
    character.swap.hidden = !swapping;
    if (swapping) {
      const words = characterWords(picked);
      character.swapText.textContent = fill(t.replaceNote, {
        title: words.title,
        line: words.line ? (lang === "zh" ? `：${words.line}。` : `: ${words.line}.`) : lang === "zh" ? "。" : ".",
      });
      character.swapOwn.hidden = state?.character !== "custom";
    }
    const limit = catalog?.personaLimit || 16000;
    const length = Array.from(character.persona.value).length;
    character.count.textContent = `${length} / ${limit}`;
    character.count.classList.toggle("setup-count-over", length > limit);

    const changes = characterChanges();
    const configured = Boolean(state?.configured);
    // Without a model only the text can be saved; the rest waits for the connection.
    const savable = configured ? changes.config || changes.text : changes.text;
    busy(character.save, character.saving, character.saving ? t.savingCharacter : t.saveCharacter);
    character.save.disabled = character.saving || !savable;
    const edited = changes.config || changes.text;
    if (edited) character.justSaved = false;
    character.note.textContent =
      !configured && changes.config ? t.needModel : character.justSaved && !character.saving ? t.savedCharacter : "";
    character.note.classList.toggle("setup-foot-note-ok", character.justSaved);
  }

  // ============================================================= figure ==

  const look = { figure: "", figures: [], saving: "" };

  function buildFigure() {
    const node = section("figure", t.figureTitle, t.figureHint);
    const grid = el("div", "setup-figures");
    grid.setAttribute("role", "radiogroup");
    grid.setAttribute("aria-labelledby", "setup-title-figure");
    const error = el("p", "setup-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    node.append(grid, error);
    Object.assign(look, { grid, error });
    return node;
  }

  // ======================================================== this computer ==

  // Shown only where the computer has it (GET /api/desk/shortcuts); "other" is another copy's link.
  const start = { login: "off", uvx: false, saving: false, known: false };
  // Hiding during games (GET/POST /api/quiet/settings) and remarks on what is in front (/api/remarks/settings).
  const quiet = { saving: false };
  const remarks = { on: true, ignore: [], saving: false };
  // Whether the character reads what mail and private messages say (/api/privacy/settings).
  const secret = { on: false, saving: false, known: false, asking: false, service: null };

  function buildComputer() {
    const node = section("computer", t.computerTitle);
    const list = el("div", "setup-options");
    list.append(buildStart(), buildQuiet(), buildRemarks(), buildPrivate());
    node.append(list);
    return node;
  }

  function buildStart() {
    const row = el("div", "setup-option");
    row.hidden = true;
    const words = el("div", "setup-option-words");
    const name = el("label", "setup-option-name", t.startTitle);
    name.htmlFor = "setup-start-login";
    const about = el("p", "setup-option-text", t.startText);
    const other = el("div", "setup-option-other");
    other.hidden = true;
    const mine = button("setup-button-secondary setup-button-sm", t.startMine, () => setStart(true));
    other.append(el("span", "", t.startOther), mine);
    const error = el("p", "setup-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    words.append(name, about, other, error);
    const box = el("input", "setup-switch");
    box.type = "checkbox";
    box.id = "setup-start-login";
    box.setAttribute("role", "switch");
    box.addEventListener("change", () => setStart(box.checked));
    row.append(words, box);
    Object.assign(start, { row, about, other, mine, error, box });
    return row;
  }

  function renderStart() {
    const { about, other, mine, box, login, uvx, saving, known } = start;
    box.checked = login === "on";
    // Under uvx it can only be turned off; not read yet, it cannot be changed.
    box.disabled = saving || !known || (uvx && login !== "on");
    about.textContent = uvx && login !== "on" ? t.startUvx : t.startText;
    other.hidden = login !== "other" || uvx;
    mine.disabled = saving;
  }

  // Read each time Settings opens: the earlier page or the first run may have changed it since.
  async function loadStart() {
    if (start.saving) return;
    try {
      const value = await ctx.api("desk/shortcuts");
      if (start.saving) return;
      start.row.hidden = !value.login_supported;
      if (!value.login_supported) return;
      Object.assign(start, { login: value.login, uvx: value.uvx, known: true });
      start.error.hidden = true;
    } catch (error) {
      // Another device has no say over this computer's sign-in: the row stays hidden,
      // and the switches below act on the computer it runs on, not this one.
      if (error?.message === "local_only") {
        start.row.hidden = true;
        document.getElementById("setup-title-computer").textContent = t.computerTitleHost;
        return;
      }
      // Read before: what was read stays. Never read: shown, switched off, with what went wrong.
      if (start.known) return;
      start.row.hidden = false;
      start.error.textContent = error?.message === "desk_shortcut_failed" ? t.startUnread : say(error);
      start.error.hidden = false;
    }
    renderStart();
  }

  async function setStart(on) {
    start.saving = true;
    start.error.hidden = true;
    renderStart();
    try {
      const value = await ctx.api("desk/shortcut", { which: "login", on });
      Object.assign(start, { login: value.login, uvx: value.uvx });
    } catch (error) {
      start.error.textContent = say(error);
      start.error.hidden = false;
    } finally {
      start.saving = false;
      renderStart();
    }
  }

  function errorLine() {
    const line = el("p", "setup-error");
    line.setAttribute("role", "alert");
    line.hidden = true;
    return line;
  }
  function failed(line, error) {
    line.textContent = say(error);
    line.hidden = false;
  }

  function buildQuiet() {
    const { row, box, about } = switchRow("quiet", t.quietTitle, t.quietText, (node) => setQuiet(node.checked));
    const now = el("p", "setup-option-now");
    now.hidden = true;
    const error = errorLine();
    about.after(now, error);
    box.disabled = true;
    Object.assign(quiet, { box, now, error });
    return row;
  }

  // Hidden right now is only ever seen from another device: this window in front never counts.
  async function loadQuiet() {
    if (quiet.saving) return;
    try {
      const [value, now] = await Promise.all([ctx.api("quiet/settings"), ctx.api("quiet")]);
      if (quiet.saving) return;
      quiet.box.checked = value.on;
      quiet.box.disabled = false;
      quiet.now.textContent = t.quietNow[now.why] || "";
      quiet.now.hidden = !(value.on && now.quiet);
      quiet.error.hidden = true;
    } catch (error) {
      failed(quiet.error, error);
    }
  }

  async function setQuiet(on) {
    quiet.saving = true;
    quiet.box.disabled = true;
    quiet.error.hidden = true;
    try {
      quiet.box.checked = (await ctx.api("quiet/settings", { on })).on;
      if (!on) quiet.now.hidden = true;
    } catch (error) {
      quiet.box.checked = !on;
      failed(quiet.error, error);
    } finally {
      quiet.saving = false;
      quiet.box.disabled = false;
    }
    // Back on: whether it is hiding right now is read again.
    if (quiet.box.checked) loadQuiet();
  }

  // As many programs as the server keeps.
  const IGNORE_MAX = 50;

  function buildRemarks() {
    const { row, box, about } = switchRow("remarks", t.remarksTitle, t.remarksText, (node) => saveRemarks({ on: node.checked }));
    const error = errorLine();
    const part = el("div", "setup-field setup-ignore");
    const label = el("span", "setup-label", t.ignoreLabel);
    label.id = "setup-ignore-label";
    const list = el("div", "setup-words");
    list.setAttribute("aria-labelledby", label.id);
    const help = el("p", "setup-help", t.ignoreHelp);
    help.id = "setup-ignore-help";
    const add = input("setup-word-input setup-ignore-input");
    add.placeholder = t.ignoreAdd;
    add.maxLength = 64;
    add.setAttribute("aria-label", t.ignoreAdd);
    add.setAttribute("aria-describedby", help.id);
    add.addEventListener("keydown", (event) => {
      const name = add.value.trim().replace(/\s+/g, " ");
      if (event.key !== "Enter" || event.isComposing || !name) return;
      event.preventDefault();
      // One already there takes no second place.
      if (remarks.ignore.some((n) => n.toLowerCase() === name.toLowerCase())) {
        add.value = "";
        return;
      }
      saveRemarks({ ignore: [...remarks.ignore, name] }).then((done) => {
        if (done) add.value = "";
        add.focus();
      });
    });
    part.append(label, list, help);
    about.after(error);
    // Under the switch too, across the whole card.
    row.append(part);
    Object.assign(remarks, { box, error, list, add });
    renderRemarks();
    return row;
  }

  function renderRemarks() {
    const { box, list, add, on, ignore, saving, known } = remarks;
    box.checked = on;
    box.disabled = saving || !known;
    list.replaceChildren(
      ...ignore.map((name) => {
        const chip = el("span", "setup-word");
        // The chip goes with its button, so the keyboard lands back on the add field.
        const off = iconButton("setup-word-off", "cross", t.ignoreRemove(name), () =>
          saveRemarks({ ignore: remarks.ignore.filter((n) => n !== name) }).then(() => remarks.add.focus()));
        off.disabled = saving;
        chip.append(el("span", "", name), off);
        return chip;
      }),
    );
    if (ignore.length < IGNORE_MAX) list.append(add);
    add.disabled = saving || !known;
  }

  async function loadRemarks() {
    if (remarks.saving) return;
    try {
      const value = await ctx.api("remarks/settings");
      if (remarks.saving) return;
      Object.assign(remarks, { on: value.on, ignore: value.ignore, known: true });
      remarks.error.hidden = true;
    } catch (error) {
      failed(remarks.error, error);
    }
    renderRemarks();
  }

  // The server answers with the cleaned whole: names trimmed, no doubles.
  async function saveRemarks(change) {
    remarks.saving = true;
    remarks.error.hidden = true;
    renderRemarks();
    try {
      const value = await ctx.api("remarks/settings", change);
      Object.assign(remarks, { on: value.on, ignore: value.ignore });
      return true;
    } catch (error) {
      failed(remarks.error, error);
      return false;
    } finally {
      remarks.saving = false;
      renderRemarks();
    }
  }

  // On only after the words on where the text goes are confirmed; off at once.
  function buildPrivate() {
    const { row, box, about } = switchRow("private", t.privateTitle, "", (node) => {
      if (node.checked) {
        node.checked = false;
        secret.asking = true;
        renderPrivate();
        secret.yes.focus();
        return;
      }
      savePrivate(false);
    });
    const ask = el("div", "setup-option-other");
    const words = el("span", "");
    const yes = button("setup-button-primary setup-button-sm", t.privateYes, () => savePrivate(true));
    const no = button("setup-button-secondary setup-button-sm", t.privateNo, () => {
      secret.asking = false;
      renderPrivate();
      box.focus();
    });
    ask.append(words, yes, no);
    const error = errorLine();
    about.after(ask, error);
    Object.assign(secret, { box, about, ask, words, yes, error });
    renderPrivate();
    return row;
  }

  function renderPrivate() {
    const { box, about, ask, words, yes, on, saving, known, asking, service: s } = secret;
    box.checked = on;
    const usable = !!s && s.configured && s.safe;
    box.disabled = saving || !known || (!on && !usable);
    if (s) {
      const where = t.privateWhere(s);
      about.textContent = !s.configured && !on ? t.privateNoModel
        : !s.safe && !on ? t.privateUnsafe(s.host)
        : on ? t.privateOn(where) : t.privateOff(where);
      words.textContent = t.privateAsk(where, s.local);
    }
    ask.hidden = !(asking && usable && !on);
    yes.disabled = saving;
  }

  async function loadPrivate() {
    if (secret.saving) return;
    try {
      const value = await ctx.api("privacy/settings");
      if (secret.saving) return;
      Object.assign(secret, { on: value.on, service: value, known: true });
      secret.error.hidden = true;
    } catch (error) {
      failed(secret.error, error);
    }
    renderPrivate();
  }

  async function savePrivate(on) {
    secret.saving = true;
    secret.error.hidden = true;
    renderPrivate();
    try {
      const value = await ctx.api("privacy/settings", { on });
      Object.assign(secret, { on: value.on, service: value, asking: false });
    } catch (error) {
      failed(secret.error, error);
    } finally {
      secret.saving = false;
      renderPrivate();
    }
  }

  // A painted figure is a sheet of four frames and shows its first; a drawn one is a single picture.
  function figureArt(key) {
    const box = el("span", "setup-figure-art");
    const sheet = new Image();
    sheet.alt = "";
    sheet.className = "setup-figure-sheet";
    sheet.onload = () => box.replaceChildren(sheet);
    sheet.onerror = () => {
      const drawing = el("img", "setup-figure-drawing");
      drawing.alt = "";
      drawing.src = `/assets/figures/${key}.svg`;
      box.replaceChildren(drawing);
    };
    sheet.src = `/assets/figures/${key}.webp`;
    return box;
  }

  function renderFigures() {
    const grid = look.grid;
    if (!grid.children.length && look.figures.length) {
      for (const row of look.figures) {
        const tile = el("button", "setup-figure");
        tile.type = "button";
        tile.setAttribute("role", "radio");
        tile.dataset.key = row.key;
        const check = el("span", "setup-figure-check");
        check.append(icon("check"));
        const label = el("span", "setup-figure-label");
        label.append(el("span", "setup-figure-name", row.name), el("span", "setup-figure-now", t.figureNow));
        tile.append(figureArt(row.key), label, check);
        tile.addEventListener("click", () => chooseFigure(row.key));
        tile.addEventListener("keydown", (event) => {
          const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
          if (!step) return;
          event.preventDefault();
          const all = [...grid.children];
          const next = all[(all.indexOf(tile) + step + all.length) % all.length];
          next.focus();
          chooseFigure(next.dataset.key);
        });
        grid.append(tile);
      }
    }
    for (const tile of grid.children) {
      const on = tile.dataset.key === look.figure;
      tile.setAttribute("aria-checked", String(on));
      tile.tabIndex = on ? 0 : -1;
      tile.classList.toggle("setup-busy", tile.dataset.key === look.saving);
    }
  }

  async function chooseFigure(key) {
    if (key === look.figure) return;
    const before = look.figure;
    // Marked at once: the file write behind it takes a moment and rarely fails.
    look.figure = key;
    look.saving = key;
    look.error.hidden = true;
    renderFigures();
    try {
      const value = await ctx.api("look", { figure: key, lang });
      look.figure = value.figure;
      // The app's own pictures of the character follow the pet.
      ctx.setFigure(value.figure);
    } catch (error) {
      look.figure = before;
      look.error.textContent = say(error);
      look.error.hidden = false;
    } finally {
      look.saving = "";
      renderFigures();
    }
  }

  async function loadFigures() {
    try {
      const value = await ctx.api(`look?lang=${lang}`);
      look.figure = value.figure;
      look.figures = value.figures;
    } catch (error) {
      look.error.textContent = say(error);
      look.error.hidden = false;
    }
    renderFigures();
  }

  // ============================================================ connect ==

  // The person's own accounts it may read: places.js draws them inside this section.
  function buildConnect() {
    const node = section("connect", t.connectTitle, t.connectHint);
    const body = el("div", "setup-connect");
    node.append(body);
    window.paPlaces.mount(body, ctx);
    return node;
  }

  // ============================================== shared by the next three ==

  // An alert in the Connect section's style, said above a part's controls.
  function alertBox() {
    const box = el("div", "places-alert setup-rec-alert");
    box.setAttribute("role", "alert");
    box.hidden = true;
    return {
      box,
      say(words) {
        box.replaceChildren(el("span", "places-alert-mark", "!"), el("span", "", words));
        box.hidden = false;
      },
      clear() {
        box.hidden = true;
      },
    };
  }

  function pill(text, tone, mark) {
    const node = el("span", `setup-pill setup-pill-${tone}`);
    if (mark) node.append(icon(mark, "setup-icon setup-icon-xs"));
    node.append(el("span", "", text));
    return node;
  }

  // A small icon button; an aria label says what it does.
  function iconButton(cls, mark, label, onClick) {
    const node = el("button", cls);
    node.type = "button";
    node.title = label;
    node.setAttribute("aria-label", label);
    node.append(icon(mark, "setup-icon setup-icon-sm"));
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }

  // A removal asks for a second click within a few seconds, as in Connect.
  function confirmClick(node, sure, work) {
    const was = { label: node.getAttribute("aria-label"), title: node.title };
    let armed = 0;
    let words = null;
    const disarm = () => {
      clearTimeout(armed);
      armed = 0;
      node.classList.remove("places-btn-armed");
      words?.remove();
      words = null;
      node.setAttribute("aria-label", was.label);
      node.title = was.title;
    };
    node.addEventListener("click", async () => {
      if (!armed) {
        node.classList.add("places-btn-armed");
        node.append((words = el("span", "places-remove-sure", sure)));
        node.setAttribute("aria-label", sure);
        node.title = sure;
        armed = setTimeout(disarm, 4000);
        return;
      }
      disarm();
      await work();
    });
    return node;
  }

  // One line with a switch, like start at sign-in.
  function switchRow(id, name, text, changed) {
    const row = el("div", "setup-option");
    const words = el("div", "setup-option-words");
    const label = el("label", "setup-option-name", name);
    label.htmlFor = `setup-switch-${id}`;
    const about = el("p", "setup-option-text", text);
    words.append(label, about);
    const box = el("input", "setup-switch");
    box.type = "checkbox";
    box.id = `setup-switch-${id}`;
    box.setAttribute("role", "switch");
    box.addEventListener("change", () => changed(box));
    row.append(words, box);
    return { row, box, about };
  }

  function ago(seconds) {
    const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
    if (minutes < 1) return t.ago.now;
    if (minutes < 60) return t.ago.m(minutes);
    if (minutes < 60 * 24) return t.ago.h(Math.round(minutes / 60));
    return t.ago.d(Math.round(minutes / 1440));
  }
  const percent = (rate) => (rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`);
  function duration(seconds) {
    if (seconds < 60) return t.seconds(seconds);
    const minutes = Math.round(seconds / 60);
    return minutes < 60 ? t.minutes(minutes) : t.hours(Math.floor(minutes / 60), minutes % 60);
  }
  let compact;
  const tokens = (n) => compact.format(n);
  // This month's row of the character's model calls, as the server keys it.
  function thisMonth(calls) {
    const now = new Date();
    return calls[`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`] || {};
  }

  // ============================================================ where ==

  // What can be reached and what the person reads (GET /api/situation). No place is shown or asked.
  // The languages a source can be in, each in its own words, so the list reads the same in any page language.
  const AUTONYMS = { zh: "中文", en: "English", ja: "日本語", ko: "한국어", ru: "Русский", pt: "Português", es: "Español",
                     fr: "Français", de: "Deutsch" };
  const LINE_PLATFORMS = [["bilibili.com", ["Bilibili", "哔哩哔哩"]], ["youtube.com", ["YouTube", "YouTube"]]];
  // The first probe takes about this long; the view is read again after it, up to PROBE_READS times.
  const PROBE_WAIT_MS = 6000;
  const PROBE_READS = 3;

  const where = { view: null, waited: 0 };

  function buildWhere() {
    const node = section("where", t.whereTitle, t.whereHint);
    node.classList.add("setup-rec");
    const line = el("p", "setup-where-line");
    line.setAttribute("aria-live", "polite");
    const alert = alertBox();
    const wrap = el("div", "setup-field");
    const title = el("span", "setup-label", t.canRead);
    title.id = "setup-langs-readable";
    const chips = el("div", "places-chips setup-lang-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-labelledby", title.id);
    for (const code of Object.keys(AUTONYMS)) {
      const chip = el("button", "places-chip setup-lang-chip", AUTONYMS[code]);
      chip.type = "button";
      chip.lang = code;
      chip.dataset.code = code;
      chip.addEventListener("click", () => toggleLang(code, chip));
      chips.append(chip);
    }
    wrap.append(title, chips);
    node.append(line, alert.box, wrap);
    Object.assign(where, { node, line, alert, chips });
    return node;
  }

  // Changes go out one at a time, each worked out from the view the one before it left, so quick clicks add up.
  let whereQueue = Promise.resolve();
  let wherePending = 0;
  function queueWhere(work) {
    wherePending += 1;
    where.node.setAttribute("aria-busy", "true");
    whereQueue = whereQueue.then(work).finally(() => {
      wherePending -= 1;
      if (!wherePending) where.node.removeAttribute("aria-busy");
    });
    return whereQueue;
  }

  function toggleLang(code, chip) {
    chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
    return queueWhere(() => {
      const list = where.view.factors.readable.value;
      return postWhere("readable", list.includes(code) ? list.filter((c) => c !== code) : [...list, code]);
    });
  }

  // One change; problems are said in `alert` (the Recommendations switch has its own).
  async function postWhere(name, value, alert = where.alert) {
    alert.clear();
    let done = true;
    try {
      where.view = await ctx.api("situation", { name, value });
    } catch (error) {
      alert.say(say(error));
      done = false;
    }
    renderWhere();
    return done;
  }

  async function loadWhere() {
    // The taste switch reads this view too: until there is one, it says here why it stays off.
    const first = !where.view;
    try {
      where.view = await ctx.api("situation");
      where.alert.clear();
      if (first) recs.alert.clear();
    } catch (error) {
      where.alert.say(say(error));
      if (first) recs.alert.say(say(error));
      return;
    }
    renderWhere();
    // The first probe runs while Settings first opens: read again until it is in, a few times at most.
    const unknown = Object.values(where.view.platforms).includes("unknown");
    if (where.waited < PROBE_READS && !where.view.probed && unknown) {
      where.waited += 1;
      setTimeout(loadWhere, PROBE_WAIT_MS);
    }
  }

  function renderWhere() {
    const view = where.view;
    if (!view) return;
    where.line.replaceChildren(...situationLine(view));
    for (const chip of where.chips.children)
      chip.setAttribute("aria-pressed", String(view.factors.readable.value.includes(chip.dataset.code)));
    renderRecsSwitch();
  }

  // "Bilibili ✓ · YouTube ✗ · reads 中文、English", the marks drawn.
  // Each separator sits at the start of the part after it, so a wrapped line never ends on one.
  function situationLine(view) {
    const sep = () => el("span", "setup-where-sep", "·");
    const parts = [];
    for (const [host, names] of LINE_PLATFORMS) {
      const state = view.platforms[host] || "unknown";
      const bit = el("span", `setup-where-site setup-where-${state}`);
      if (parts.length) bit.append(sep());
      bit.append(el("span", "", pick(names)),
                 icon(state === "up" ? "check" : state === "down" ? "cross" : "question", "setup-icon setup-icon-xs"),
                 el("span", "setup-sr", t.platform[state]));
      parts.push(bit);
    }
    const reads = view.factors.readable.value;
    if (reads.length) {
      const bit = el("span", "setup-where-site");
      bit.append(sep(), el("span", "", t.reads(reads.map((c) => AUTONYMS[c] || c).join(t.listSep))));
      parts.push(bit);
    }
    return parts;
  }

  // ======================================================= what it knows ==

  // The character's notes about the person (GET /api/profile), for them to read and correct.
  const know = { view: null, saving: false, telling: false, saved: "", told: "" };
  const TEXTS = ["owner", "character_learned"];
  // The route takes a text of up to 2000 characters and keeps three lines of the learned one.
  const KNOW_TEXT_MAX = 2000;
  const LEARNED_LINES = 3;

  function buildKnow() {
    const node = section("know", t.knowTitle, t.knowHint);
    node.classList.add("setup-rec");
    const alert = alertBox();
    const texts = {};
    for (const [name, label, help, rows] of [["owner", t.owner, t.ownerHelp, 6], ["character_learned", t.learned, t.learnedHelp, 3]]) {
      const area = el("textarea", "setup-input setup-textarea setup-know-text");
      area.rows = rows;
      area.maxLength = KNOW_TEXT_MAX;
      area.addEventListener("input", renderKnowFoot);
      const box = field(label, area, help);
      const pins = el("ul", "setup-pins");
      pins.setAttribute("aria-label", t.pinnedLine);
      box.wrap.append(pins);
      texts[name] = { box, area, pins, was: "" };
    }
    const save = button("setup-button-primary", t.saveKnow, saveKnow);
    const note = el("p", "setup-foot-note");
    note.setAttribute("aria-live", "polite");
    const foot = el("div", "setup-foot");
    foot.append(save, note);

    const leans = el("details", "setup-fold setup-leans");
    const leansSummary = el("summary", "setup-fold-summary");
    const leansWords = el("span");
    leansSummary.append(icon("chevron", "setup-fold-chevron"), leansWords);
    const leansFind = input("setup-lean-find");
    leansFind.type = "search";
    leansFind.placeholder = t.leansFind;
    leansFind.setAttribute("aria-label", t.leansFind);
    leansFind.addEventListener("input", renderLeans);
    const leansBody = el("div", "setup-lean-list");
    const leansInner = el("div", "setup-fold-body");
    leansInner.append(leansFind, leansBody);
    leans.append(leansSummary, leansInner);
    const leansField = el("div", "setup-field");
    leansField.append(el("span", "setup-label", t.leans), el("p", "setup-help", t.leansHelp), leans);

    const wordsField = el("div", "setup-field");
    const wordList = el("div", "setup-words");
    const wordInput = input("setup-word-input");
    wordInput.placeholder = t.wordAdd;
    wordInput.setAttribute("aria-label", t.wordAdd);
    wordInput.maxLength = 40;
    wordInput.addEventListener("keydown", (event) => {
      const word = wordInput.value.trim().replace(/\s+/g, " ");
      if (event.key !== "Enter" || event.isComposing || !word) return;
      event.preventDefault();
      // A word already there takes no second place.
      if (know.view.walk_words.some((w) => w.toLowerCase() === word.toLowerCase())) {
        wordInput.value = "";
        return;
      }
      editKnow({ walk_words: [...know.view.walk_words, word] }).then((done) => {
        if (done) wordInput.value = "";
        wordInput.focus();
      });
    });
    wordsField.append(el("span", "setup-label", t.words), wordList, el("p", "setup-help", t.wordsHelp));

    const rulesField = el("div", "setup-field");
    const rules = el("div", "setup-rules");
    const rulesHelp = el("p", "setup-help", t.rulesHelp);
    rulesField.append(el("span", "setup-label", t.rules), rules, rulesHelp);

    const tell = el("div", "setup-tell");
    const tellArea = el("textarea", "setup-input setup-textarea setup-tell-text");
    tellArea.maxLength = 1000;
    tellArea.rows = 3;
    tellArea.placeholder = t.tellPlaceholder;
    const tellBox = field(t.tell(ctx.name || (lang === "zh" ? "它" : "it")), tellArea);
    const tellSend = button("setup-button-secondary", t.tellSend, tellIt);
    tellArea.addEventListener("input", setKnowBusy);
    const tellNote = el("p", "setup-foot-note");
    tellNote.setAttribute("aria-live", "polite");
    const tellFoot = el("div", "setup-foot");
    tellFoot.append(tellSend, tellNote);
    tell.append(tellBox.wrap, tellFoot);

    const calls = el("p", "setup-quiet");
    node.append(alert.box, texts.owner.box.wrap, texts.character_learned.box.wrap, foot, tell, leansField, wordsField,
                rulesField, calls);
    Object.assign(know, { node, alert, texts, save, note, leans, leansWords, leansFind, leansBody, wordList, wordInput, rules,
                          rulesHelp, tellArea, tellSend, tellNote, tellBox, calls });
    tellSend.disabled = true;
    return node;
  }

  async function loadKnow() {
    if (know.saving || know.telling) return;
    try {
      know.view = await ctx.api("profile");
      know.alert.clear();
    } catch (error) {
      know.alert.say(say(error));
      return;
    }
    renderKnow();
  }

  const dirty = (name) => know.texts[name].area.value !== know.texts[name].was;

  function renderKnow() {
    const view = know.view;
    for (const name of TEXTS) {
      const text = know.texts[name];
      // What the person is typing is never written over.
      if (!dirty(name)) text.area.value = view[name];
      text.was = view[name];
      const pinned = view.pinned.filter((p) => p.field === name);
      text.pins.hidden = !pinned.length;
      text.pins.replaceChildren(...pinned.map((p) => pinRow(p)));
    }
    renderLeans();
    renderWords();
    renderRules();
    renderCalls(know.calls, view.calls);
    renderKnowFoot();
  }

  function pinRow(row) {
    const item = el("li", "setup-pin");
    item.append(icon("pin", "setup-icon setup-icon-xs setup-pin-mark"), el("span", "setup-pin-text", row.text),
                iconButton("setup-pin-off", "cross", t.unpin(row.text), () =>
                  editKnow({ pinned: know.view.pinned.filter((p) => p !== row) })));
    return item;
  }

  function renderKnowFoot() {
    const changed = TEXTS.some(dirty);
    busy(know.save, know.saving, know.saving ? t.savingKnow : t.saveKnow);
    know.note.textContent = know.saving ? t.rewriting : changed ? "" : know.saved;
    know.note.classList.toggle("setup-foot-note-ok", !know.saving && Boolean(know.saved) && !changed);
    const learned = know.texts.character_learned.area.value.split("\n").filter((line) => line.trim()).length;
    know.texts.character_learned.box.help(learned > LEARNED_LINES ? t.learnedOver : t.learnedHelp);
    setKnowBusy();
  }

  // A rewrite writes back the notes it started from, so nothing else here can change until it is back.
  function setKnowBusy() {
    const locked = know.saving || know.telling;
    for (const control of know.node.querySelectorAll(".setup-lean-range, .setup-word-input, .setup-word-off, .setup-pin-off, .setup-rule-off"))
      control.disabled = locked;
    know.save.disabled = locked || !TEXTS.some(dirty);
    if (!know.telling) know.tellSend.disabled = locked || !know.tellArea.value.trim();
  }

  // A changed text runs one rewrite before the answer comes, so this waits in words.
  async function saveKnow() {
    const changes = Object.fromEntries(TEXTS.filter(dirty).map((name) => [name, know.texts[name].area.value]));
    know.saving = true;
    know.saved = "";
    know.alert.clear();
    renderKnowFoot();
    try {
      const value = await ctx.api("profile", changes);
      for (const name of TEXTS) know.texts[name].was = know.texts[name].area.value;
      know.view = value;
      know.saved = value.rewritten ? t.savedKnow : state.configured ? t.savedLater : t.savedPlain;
    } catch (error) {
      know.alert.say(say(error));
    }
    know.saving = false;
    renderKnow();
  }

  // Leans, walk words, pins and rules: each saved as it changes.
  async function editKnow(changes) {
    know.alert.clear();
    let done = true;
    try {
      know.view = await ctx.api("profile", changes);
    } catch (error) {
      know.alert.say(say(error));
      done = false;
    }
    renderKnow();
    return done;
  }

  const LEANS_SHOWN = 12;
  function renderLeans() {
    const { sources, source_lean: lean } = know.view;
    const adjusted = sources.filter((s) => lean[s.key]).length;
    know.leansWords.textContent = t.leansOpen(adjusted, sources.length);
    if (!sources.length) return know.leansBody.replaceChildren(el("p", "setup-help", t.noSources));
    const scale = el("div", "setup-lean setup-lean-scale");
    scale.setAttribute("aria-hidden", "true");
    const ends = el("div", "setup-lean-ends");
    ends.append(el("span", "", t.less), el("span", "", t.more));
    scale.append(el("span"), ends);
    // Leaning ones first, then the catalogue's order; a few hundred sliders are found by name, not scrolled.
    const query = know.leansFind.value.trim().toLowerCase();
    const found = sources.filter((s) => !query || `${s.name} ${s.about} ${s.key}`.toLowerCase().includes(query));
    const rows = found.sort((a, b) => Boolean(lean[b.key]) - Boolean(lean[a.key]));
    const shown = rows.slice(0, Math.max(LEANS_SHOWN, adjusted));
    const left = rows.length - shown.length;
    know.leansBody.replaceChildren(scale, ...shown.map((source) => leanRow(source, lean[source.key] || 0)));
    if (left) know.leansBody.append(el("p", "setup-help setup-lean-left", t.leansLeft(left)));
    setKnowBusy();
  }

  function leanRow(source, value) {
    const row = el("div", "setup-lean");
    const words = el("div", "setup-lean-words");
    words.append(el("span", "setup-lean-name", source.name), el("span", "setup-lean-about", source.about));
    const range = el("input", "setup-lean-range");
    range.type = "range";
    range.min = "-1";
    range.max = "1";
    range.step = "0.25";
    range.value = String(value);
    range.setAttribute("aria-label", source.name);
    const said = (v) => (v > 0 ? `${t.more} ${v}` : v < 0 ? `${t.less} ${-v}` : "0");
    // The track fills from the middle to the thumb, so 0 reads as no lean either way.
    const mark = (v) => {
      range.style.setProperty("--lean", String(v));
      range.setAttribute("aria-valuetext", said(v));
      range.classList.toggle("setup-lean-set", v !== 0);
    };
    mark(value);
    range.addEventListener("input", () => mark(Number(range.value)));
    range.addEventListener("change", () => {
      const lean = { ...know.view.source_lean, [source.key]: Number(range.value) };
      editKnow({ source_lean: Object.fromEntries(Object.entries(lean).filter(([, v]) => v)) });
    });
    row.append(words, range);
    return row;
  }

  function renderWords() {
    const words = know.view.walk_words;
    know.wordList.replaceChildren(
      ...words.map((word) => {
        const chip = el("span", "setup-word");
        chip.append(el("span", "", word), iconButton("setup-word-off", "cross", t.wordRemove(word), () =>
          editKnow({ walk_words: words.filter((w) => w !== word) })));
        return chip;
      }),
    );
    if (words.length < 5) know.wordList.append(know.wordInput);
  }

  function renderRules() {
    const { rules, sources } = know.view;
    know.rulesHelp.hidden = !rules.length;
    if (!rules.length) return know.rules.replaceChildren(el("p", "setup-rules-empty", t.rulesEmpty));
    know.rules.replaceChildren(
      ...rules.map((rule) => {
        const source = rule.kind === "hide_source";
        const words = source ? t.ruleSource(sources.find((s) => s.key === rule.key)?.name || rule.key) : t.ruleTopic(rule.topic);
        const row = el("div", "setup-rule");
        const remove = iconButton("places-remove setup-rule-off", "cross", t.ruleRemove(words));
        // The rest go back as they are; the route keeps who made each one.
        confirmClick(remove, t.ruleSure, () => editKnow({ rules: rules.filter((r) => r !== rule) }));
        row.append(icon(source ? "ban" : "tag", "setup-icon setup-icon-sm setup-rule-mark"), el("span", "setup-rule-text", words), remove);
        return row;
      }),
    );
  }

  function renderCalls(node, calls) {
    const month = thisMonth(calls);
    const [judge, profile, pick] = ["judge", "profile", "pick"].map((kind) => month[kind] || { calls: 0, input: 0, output: 0 });
    const n = judge.calls + profile.calls + pick.calls;
    const used = [judge, profile, pick].reduce((sum, row) => sum + row.input + row.output, 0);
    node.textContent = n ? t.callsMonth(n, judge.calls, profile.calls, pick.calls, tokens(used)) : t.callsNone;
  }

  // The first run's free-text box, here too: one model call before the answer.
  async function tellIt() {
    know.telling = true;
    know.tellNote.textContent = "";
    know.tellBox.error("");
    busy(know.tellSend, true, t.tellWaiting);
    setKnowBusy();
    try {
      know.view = await ctx.api("profile/answer", { text: know.tellArea.value });
      know.tellArea.value = "";
      know.tellNote.textContent = know.view.rewritten ? t.tellDone : state.configured ? t.tellLater : t.tellKept;
    } catch (error) {
      know.tellBox.error(say(error));
    }
    know.telling = false;
    busy(know.tellSend, false, t.tellSend);
    if (know.view) renderKnow();
    else setKnowBusy();
  }

  // ===================================================== recommendations ==

  const recs = { numbers: null, posting: false };

  function buildRecs() {
    const node = section("recs", t.recsTitle, t.recsHint);
    node.classList.add("setup-rec");
    const model = switchRow("feed-model", t.model, t.modelText, setModel);
    model.box.disabled = true;
    const fold = el("details", "setup-fold setup-numbers");
    const summary = el("summary", "setup-fold-summary");
    summary.append(icon("chevron", "setup-fold-chevron"), el("span", "", t.numbers));
    const body = el("div", "setup-fold-body setup-numbers-body");
    body.setAttribute("aria-live", "polite");
    fold.append(summary, body);
    // Read each time it opens: the week moves on while Settings stays open.
    fold.addEventListener("toggle", () => fold.open && loadNumbers());
    const alert = alertBox();
    node.append(model.row, alert.box, fold);
    Object.assign(recs, { model, fold, body, alert });
    return node;
  }

  function renderRecsSwitch() {
    const on = where.view.factors.feed_model.value;
    recs.model.box.disabled = recs.posting;
    recs.model.box.checked = on;
    recs.model.about.textContent = on ? t.modelText : t.modelOff;
  }

  // The switch is a situation factor, but it says its problems here and the open numbers follow it.
  function setModel(box) {
    recs.posting = true;
    box.disabled = true;
    box.setAttribute("aria-busy", "true");
    return queueWhere(async () => {
      const done = await postWhere("feed_model", box.checked, recs.alert);
      recs.posting = false;
      box.removeAttribute("aria-busy");
      renderRecsSwitch();
      if (done && recs.fold.open) await loadNumbers();
    });
  }

  async function loadNumbers() {
    try {
      recs.numbers = await ctx.api("feed/numbers");
      recs.alert.clear();
    } catch (error) {
      recs.alert.say(say(error));
      return;
    }
    renderNumbers();
  }

  function renderNumbers() {
    const n = recs.numbers;
    const parts = [];
    if (!n.on) parts.push(el("p", "setup-quiet", t.numbersOff));

    const rows = ["list", "card", "chat", "other"].filter((key) => n.surfaces[key]?.shown);
    if (rows.length) {
      const scroll = el("div", "setup-table-wrap");
      const table = el("table", "setup-table");
      const head = el("tr");
      for (const words of [t.where, t.shown, t.opened, t.liked, t.skipped]) head.append(el("th", "", words));
      table.append(el("thead"), el("tbody"));
      table.tHead.append(head);
      for (const key of rows) {
        const s = n.surfaces[key];
        const row = el("tr");
        row.append(el("th", "", t.surface[key]), el("td", "", String(s.shown)), el("td", "", percent(s.open_rate)),
                   el("td", "", percent(s.like_rate)), el("td", "", percent(s.skip_hide_rate)));
        table.tBodies[0].append(row);
      }
      scroll.append(table);
      parts.push(scroll);
    } else parts.push(el("p", "setup-quiet", t.noShown));

    const facts = el("dl", "setup-stats");
    const fact = (term, value) => facts.append(el("dt", "", term), el("dd", "", value));
    fact(t.played, duration(n.play_s));
    fact(t.top5, n.list_opens ? t.top5Value(percent(n.list_opens_top5_share), n.list_opens) : "—");
    fact(t.pickLiked, t.ofN(percent(n.picks.character.like_rate), n.picks.character.shown));
    fact(t.modelLiked, t.ofN(percent(n.picks.model.like_rate), n.picks.model.shown));
    if (n.on) fact(t.slots, t.slotsValue(n.k_c));
    fact(t.fitted, n.model.at ? t.fittedValue(ago(n.model.at), n.model.rows) : t.notFitted);
    fact(t.gated, String(n.shown_on_gated_hosts));
    const judge = thisMonth(n.calls).judge;
    fact(t.judgeMonth, judge ? t.judgeValue(judge.calls, tokens(judge.input + judge.output)) : "—");
    parts.push(facts);

    const weights = el("div", "setup-weights");
    weights.append(el("h3", "setup-label", t.weights), el("p", "setup-help", t.weightsHelp));
    for (const key of ["char_fits", "char_love", "judged"]) weights.append(weightRow(key, n.learned[key]));
    parts.push(weights);
    recs.body.replaceChildren(...parts);
  }

  // A weight on a -3..3 line: a dot at its mean and a light bar one spread either side.
  const WEIGHT_SPAN = 3;
  // A mean this close to 0 hardly moves the ranking.
  const WEIGHT_FLAT = 0.25;
  function weightRow(key, { mean, sd }) {
    const row = el("div", "setup-weight");
    const at = (v) => `${((Math.max(-WEIGHT_SPAN, Math.min(WEIGHT_SPAN, v)) + WEIGHT_SPAN) / (2 * WEIGHT_SPAN)) * 100}%`;
    const bar = el("span", "setup-weight-bar");
    bar.setAttribute("aria-hidden", "true");
    const spread = el("span", "setup-weight-spread");
    spread.style.left = at(mean - sd);
    spread.style.right = `calc(100% - ${at(mean + sd)})`;
    const dot = el("span", "setup-weight-dot");
    dot.style.left = at(mean);
    bar.append(el("span", "setup-weight-zero"), spread, dot);
    // Said in words; the number itself is kept for a hover.
    const sign = mean > 0 ? "+" : mean < 0 ? "−" : "";
    const says = t.weightSays;
    const way = Math.abs(mean) < WEIGHT_FLAT ? says.flat : mean > 0 ? says.up : says.down;
    const value = el("span", "setup-weight-value", `${way} · ${sd > Math.abs(mean) ? says.unsure : says.sure}`);
    value.title = `${sign}${Math.abs(mean).toFixed(2)} ± ${sd.toFixed(2)}`;
    row.append(el("span", "setup-weight-name", t.weight[key]), bar, value);
    return row;
  }

  // =============================================================== more ==

  function buildMore() {
    const node = el("section", "setup-more");
    node.dataset.part = "more";
    const words = el("div", "setup-more-words");
    words.append(el("h2", "setup-more-title", t.moreTitle), el("p", "setup-more-text", t.moreText));
    const link = el("a", "setup-button setup-button-secondary setup-more-link");
    link.href = classicUrl();
    link.append(el("span", "setup-button-label", t.moreLink), icon("arrow"));
    node.append(words, link);
    return node;
  }

  // ============================================================== frame ==

  async function mount(node, context) {
    ctx = context;
    lang = ctx.lang === "zh" ? "zh" : "en";
    t = WORDS[lang];
    root = el("div", "setup-page");
    root.lang = lang === "zh" ? "zh-CN" : "en";
    const head = el("header", "setup-head");
    head.append(el("h1", "setup-title", t.title), el("p", "setup-intro", t.intro));
    const loading = el("div", "setup-loading");
    for (let i = 0; i < 3; i++) loading.append(el("div", "setup-loading-block"));
    root.append(head, loading);
    node.replaceChildren(root);
    try {
      [state, catalog] = await Promise.all([ctx.api("state"), ctx.api("catalog")]);
    } catch (error) {
      loading.replaceWith(el("p", "setup-error setup-error-page", say(error)));
      return;
    }
    parts.model = buildModel();
    parts.character = buildCharacter();
    parts.figure = buildFigure();
    parts.connect = buildConnect();
    compact = new Intl.NumberFormat(root.lang, { notation: "compact", maximumFractionDigits: 1 });
    parts.where = buildWhere();
    parts.know = buildKnow();
    parts.recs = buildRecs();
    parts.computer = buildComputer();
    loading.replaceWith(parts.model, parts.character, parts.figure, parts.connect, parts.where, parts.know, parts.recs,
                        parts.computer, buildMore());
    window.paPlaces.show();
    buildChips();
    parts.service.value = state.configured ? state.provider : catalog.providers[0].id;
    serviceChanged(false);
    renderModel();
    renderCharacter();
    // The persona and the figures change the page's height when they arrive: a part asked for is found after.
    const filled = Promise.all([loadPersona(), loadFigures(), loadStart(), loadQuiet(), loadRemarks(), loadPrivate(), loadWhere(),
                                loadKnow()]);
    // A sign-in still waiting from before is picked up again.
    ctx.api("signin")
      .then((value) => (value.state === "waiting" || value.state === "verifying") && signinFollow(value))
      .catch(() => {});
    ctx.api("detect")
      .then((value) => {
        model.found = value;
        renderFound();
      })
      .catch(() => {});
    if (waitingPart) {
      const part = waitingPart;
      waitingPart = "";
      filled.then(() => show(part));
    }
  }

  // Opened again: the model may have been connected or changed elsewhere since.
  async function refresh() {
    if (model.working || character.saving) return;
    try {
      const fresh = await ctx.api("state");
      if (model.working || character.saving) return;
      if (fresh.configured !== state.configured || fresh.provider !== state.provider || fresh.model !== state.model)
        model.checked = null;
      state = fresh;
    } catch {
      return;
    }
    renderModel();
    renderCharacter();
  }

  // Asked for before the page finished loading: done once it has.
  let waitingPart = "";
  function show(part) {
    if (!parts.model) {
      waitingPart = part || "";
      return;
    }
    waitingPart = "";
    refresh();
    loadStart();
    loadQuiet();
    loadRemarks();
    loadPrivate();
    loadWhere();
    loadKnow();
    if (recs.fold.open) loadNumbers();
    window.paPlaces.show();
    const target = { model: parts.model, character: parts.character, figure: parts.figure, connect: parts.connect,
                     where: parts.where, know: parts.know, recs: parts.recs }[part];
    if (!target) return;
    // Asked for the model while one works: the ways to change it open.
    if (part === "model" && state?.configured) {
      model.open = true;
      renderModel();
    }
    target.scrollIntoView({ block: "start" });
    target.querySelector(".setup-section-title").focus({ preventScroll: true });
  }

  window.paSetup = { mount, show };
})();
