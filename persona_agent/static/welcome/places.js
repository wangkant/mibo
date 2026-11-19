// Connect, a section of Settings: the person's own accounts the character may read, one card each.
// The public internet it reads on its own; nothing about that is shown here.
// Settings mounts it once and calls show() each time the section comes up.
(() => {
  "use strict";

  // A Latin name inside a Chinese sentence gets a space on each side.
  const latin = (words) => /^[\x20-\x7e]+$/.test(words);
  const spaced = (words) => (latin(words) ? ` ${words} ` : words);
  // A name that starts or ends a Chinese clause: a space only on the side that meets Chinese.
  const before = (words) => (latin(words) ? `${words} ` : words);
  const after = (words) => (latin(words) ? ` ${words}` : words);
  const WORDS = {
    zh: {
      later: "即将支持",
      state: {
        off: "未连接",
        on: "读取中",
        paused: "已暂停",
        problem: "需要处理",
        soon: "即将支持",
        pending: "连接中",
      },
      connect: "连接",
      manage: "管理",
      close: "收起",
      show: "显示",
      hide: "隐藏",
      cancel: "取消",
      refresh: "刷新",
      refreshing: "正在刷新…",
      unread: "尚未读取",
      brought: (when, n) => (n ? `${when}读取 · 带回 ${n} 条` : `${when}读取 · 无新内容`),
      lastRead: (when) => `上次读取：${when}`,
      ago: { now: "刚刚", m: (n) => `${n} 分钟前`, h: (n) => `${n} 小时前`, d: (n) => `${n} 天前` },

      mail: "邮箱",
      mailAbout: "读取订阅邮件和通知，从中挑选值得你看的内容。",
      mailReading: (n) => `正在读取 ${n} 个邮箱`,
      mailPaused: "已连接的邮箱均已暂停",
      mailUnavailable: "暂时无法读取邮箱信息。请稍后重试。",
      mailReads: (letters) =>
        letters
          ? "读取订阅邮件、通知和他人写给你的邮件。不会发送、删除或标记任何邮件。密码和读取的内容只保存在本机。"
          : "只读取订阅邮件和通知，不读取他人写给你的邮件。不会发送、删除或标记任何邮件。密码和读取的内容只保存在本机。",
      readThis: (address) => `读取 ${address}`,
      removeMail: (address) => `断开 ${address}`,
      removeSure: "断开这个邮箱？",
      letters: "读取私人邮件",
      lettersNote: "关闭时只读取订阅和通知；开启后也会读取他人写给你的邮件。",
      addAnother: "添加邮箱",
      pickProvider: "邮箱类型",
      addressHelp: "输入地址后会自动识别邮箱类型；无法识别时请在下方选择。",
      pickFirst: "输入地址或选择邮箱类型后，将显示下一步。",
      openCode: (name) => `打开 ${name}`,
      howTo: (name, secret) => `先在 ${name} 获取${spaced(secret)}`,
      howToOther: "操作步骤",
      help: "官方说明",
      address: "邮箱地址",
      host: "IMAP 服务器",
      hostHelp: "通过 TLS 连接 993 端口；如使用其他端口，请写成 imap.example.com:995 的形式。",
      secretHelp: (secret) => `粘贴刚获取的${spaced(secret)}，而非平时的登录密码。`,
      secretHelpOther: "邮箱提供给邮件客户端使用的密码。",
      signIn: "连接",
      signingIn: "正在登录…",
      mailDone: (address) => `已连接 ${address}，正在读取。`,
      mailShort: {
        mail_login_failed: "登录被拒绝，密码可能已失效",
        mail_unreachable: "无法连接邮箱服务器",
        mail_refused: "无法打开收件箱",
        mail_failed: "邮箱服务器出错",
      },
      lastFailed: "上次读取失败",
      pair: (who, what) => `${who}：${what}`,

      discord: "Discord",
      discordAbout: "读取你选择的服务器频道中的新消息。",
      discordSoon: "Discord 连接即将支持。",
      discordUnavailable: "暂时无法读取 Discord 信息。请稍后重试。",
      discordIntro: "Discord 需要通过你自己创建的机器人读取，共四步：",
      discordSteps: [
        "打开 Discord 开发者后台，点击右上角的 New Application，名称任意（例如 personagent）。",
        "点击左侧的 Bot，找到 Message Content Intent 并开启，然后点击 Save Changes。",
        "在同一 Bot 页面点击 Reset Token，确认后复制显示的 token。",
        "将 token 粘贴到下方，点击「连接」。",
      ],
      devPortal: "打开开发者后台",
      token: "Bot token",
      tokenPlaceholder: "粘贴 token",
      tokenHelp: "token 相当于机器人的密码，只保存在本机。请勿发送给任何人。",
      connecting: "正在连接…",
      botAs: (name) => `已连接机器人 ${name}`,
      inviteTitle: "邀请机器人加入服务器",
      inviteNote: "在打开的页面中选择服务器并点击授权；你需要拥有该服务器的“管理服务器”权限。完成后回到这里点击「刷新」。",
      invite: "邀请到服务器",
      channels: "读取的频道",
      channelsNote: "只读取已开启频道中的新消息。",
      channelCount: (on, all) => `${on} / ${all}`,
      noServers: "机器人尚未加入任何服务器。请用上方按钮邀请，然后点击「刷新」。",
      noChannels: "机器人在此服务器中看不到文字频道。",
      readChannel: (name) => `读取 #${name}`,
      discordReading: (n) => (n ? `正在读取 ${n} 个频道` : "已连接，尚未选择频道"),
      discordReads:
        "只读取你开启的频道，不会发言或做任何修改。token 和读取的消息只保存在本机。",
      disconnect: "断开 Discord",
      disconnecting: "正在断开…",

      // The other accounts, from GET /api/accounts.
      a: {
        about: {
          qq: "读取加入了你的 QQ 机器人的群，以及发给它的消息。",
          wechat: "读取你发给微信 ClawBot 的文字和链接。",
          bilibili: "读取你关注的 UP 主发布的新视频和动态。",
          weibo: "读取你关注的人发布的新微博。",
          zhihu: "读取你关注的人的新回答、文章和视频。",
          youtube: "读取你添加的频道发布的新视频。",
          outlook: "读取 Outlook / Hotmail 收件箱中的订阅和通知。",
          slack: "读取你在 Slack 中开启的频道和私信。",
          github: "读取你的 GitHub 通知：审阅请求和提及你的讨论。",
          matrix: "读取你开启的未加密 Matrix 房间。",
        },
        start: { qr: "获取二维码", browser: "登录", code: "获取验证码", fields: "连接", paste: "连接" },
        starting: "正在准备…",
        warnTitle: "连接前须知",
        warnOk: "我已了解",
        qrSay: (name) => `使用手机${spaced(name)}扫码`,
        qrNote: "扫码后按手机上的提示确认，此处会自动完成连接。",
        qrScanned: "已扫码，请在手机上确认。",
        browserOpened: "已在浏览器中打开登录页。登录并授权后，此处会自动完成连接。",
        browserAgain: "重新打开",
        browserOpen: "在浏览器中打开登录页，登录并授权后，此处会自动完成连接。",
        openSignIn: "打开登录页",
        copyLink: "复制链接",
        copy: "复制",
        copied: "已复制",
        codeSay: (host) => `打开 ${host}，输入以下代码：`,
        codeOpen: (host) => `打开 ${host}`,
        windowSay: (name) => `登录窗口已打开。请在该窗口中登录${after(name)}，完成后此处会自动完成连接。`,
        windowNote: "该窗口由 personagent 打开，登录信息只保存在本机，不影响你平时使用的浏览器。",
        windowStop: "如需取消，关闭该窗口即可。",
        waiting: "正在等待你完成操作…",
        expired: "本次连接已过期。",
        again: "重新开始",
        retry: "重试",
        connectedAs: (account) => `已连接 ${account}`,
        connected: "已连接",
        reconnect: "重新连接",
        addMore: "添加频道",
        choices: { qq: "读取的群", slack: "读取的频道和私信", matrix: "读取的房间", youtube: "读取的频道", other: "读取范围" },
        choicesNote: "只读取已开启的项目。",
        choicesEmpty: {
          qq: "暂无群。将机器人加入群后，稍后会显示在这里。",
          slack: "暂未读取到会话。请点击「刷新」。",
          matrix: "暂无可读取的房间；加密房间不会列出。",
          other: "暂无可选项。",
        },
        choose: (name) => `读取 ${name}`,
        invite: "邀请到更多服务器",
        disconnect: "断开",
        disconnectSure: "断开这个账号？",
        done: "已连接，正在读取。",
        unavailable: "暂时无法读取其他账号。请稍后重试。",
        lookInside: "查看详情",
        // A problem, in a few words for the card's line; the full sentence is inside.
        short: {
          signed_out: "登录已失效",
          page_changed: "页面已改版，暂时无法读取",
          unreachable: "无法连接",
          limited: "请求过多，稍后读取",
          failed: "上次读取失败",
        },
      },

      errors: {
        accounts_unknown: "该账号类型已不存在。请刷新页面。",
        accounts_invalid: "提交的内容无效。请刷新页面后重试。",
        local_only: "此步骤需在运行 personagent 的电脑上操作。",
        offline: "无法连接到 personagent。请关闭后重新打开。",
        qq_expired: "二维码已过期。请重新获取。",
        qq_rejected: "QQ 不再接受该机器人的凭据。请重新扫码连接。",
        qq_offline: "QQ 机器人尚未上线或已下线。请在 QQ 开放平台查看其状态。",
        qq_banned: "QQ 封禁了这个机器人。",
        qq_refused: "QQ 拒绝了连接，机器人可能没有接收群消息的权限。",
        wechat_expired: "二维码已过期。请重新获取。",
        wechat_no_qr: "微信未返回二维码。请稍后重试。",
        wechat_verify_needed: "微信要求额外验证。请在手机上完成验证后重新扫码。",
        wechat_blocked: "微信暂时不允许此连接。请稍后重试。",
        wechat_paused: "微信已暂停 ClawBot，稍后将自动重试。",
        wechat_session_expired: "微信连接已失效。请重新扫码连接。",
        github_token_invalid: "令牌无效。请复制完整的令牌后重新粘贴。",
        github_token_refused: "该令牌无法读取通知。请通过链接新建 classic 令牌，只勾选 notifications。",
        matrix_homeserver_invalid: "服务器地址无效，须以 https 开头。如不确定，请填写 matrix.org。",
        matrix_password_missing: "该服务器需要密码登录。请填写密码。",
        matrix_login_unsupported: "暂不支持该服务器的登录方式。",
        matrix_login_rejected: "用户名或密码不正确。",
        slack_port_busy: "Slack 登录所需的本机端口 53134 已被其他程序占用。请关闭该程序后重试。",
        youtube_invalid: "无法识别频道。请每行粘贴一个频道链接或 @账号名。",
        youtube_not_found: "未找到这些频道。请检查链接或账号名。",
        mail_invalid: "地址或密码格式不正确。请检查后重试。",
        mail_login_failed: (secret) =>
          secret
            ? `登录被拒绝。请检查地址，并确认填写的是${spaced(secret)}，而非平时的登录密码。`
            : "登录被拒绝。请检查地址、服务器和密码。",
        mail_unreachable: "无法连接邮箱服务器。请检查网络后重试。",
        mail_exists: "该邮箱已连接。",
        mail_refused: "登录成功，但无法打开收件箱。请检查邮箱设置中是否已开启 IMAP。",
        mail_failed: "邮箱服务器返回了意外的响应。请稍后重试。",
        mail_unknown: "该邮箱已不存在。请刷新页面。",
        discord_token_invalid: "token 无效。请在 Bot 页面重新点击 Reset Token，复制完整的 token 后粘贴。",
        discord_unreachable: "无法连接 Discord。请检查网络或代理后重试。",
        discord_intent_missing: "尚未开启 Message Content Intent。请在 Bot 页面开启并保存，然后点击「连接」。",
        discord_invalid: "这不像是 token。请在 Bot 页面点击 Reset Token，完整复制新生成的 token。",
        discord_not_connected: "Discord 尚未连接。请先粘贴 token 进行连接。",
        discord_failed: "Discord 返回了意外的响应。请稍后重试。",
        generic: "操作失败。请重试。",
      },
      // An account's code by what comes after its key, such as bilibili_signed_out; `name` is the account's.
      kinds: {
        invalid: () => "填写的内容无效。请检查后重试。",
        not_ready: (name) => `${before(name)}连接即将支持。`,
        not_connected: (name) => `${before(name)}尚未连接。请先连接。`,
        denied: (name) => `${before(name)}未获得授权。请重试并点击同意。`,
        expired: () => "等待超时，本次连接已过期。请重新开始。",
        unreachable: (name) => `无法连接${after(name)}。请检查网络或代理后重试。`,
        failed: (name) => `${before(name)}返回了意外的响应。请稍后重试。`,
        limited: (name) => `${before(name)}提示请求过多。请稍后重试。`,
        signed_out: (name) => `${before(name)}的登录已失效。请重新连接。`,
        window_closed: () => "登录窗口已关闭。如需连接，请重新开始。",
        browser_missing: () => "本机未找到 Edge 或 Chrome。请安装后重试。",
        browser_support_missing: () => "当前版本缺少打开登录窗口所需的组件。请换用带网页支持的版本后重试。",
        browser_start_failed: () => "无法打开登录窗口。请重试。",
        page_changed: (name) => `${before(name)}的页面已改版，暂时无法读取。请等待 personagent 更新。`,
      },
    },
    en: {
      later: "On the way",
      state: {
        off: "Not connected",
        on: "Reading",
        paused: "Paused",
        problem: "Needs a look",
        soon: "Coming soon",
        pending: "Connecting",
      },
      connect: "Connect",
      manage: "Manage",
      close: "Close",
      show: "Show",
      hide: "Hide",
      cancel: "Cancel",
      refresh: "Refresh",
      refreshing: "Refreshing…",
      unread: "Not read yet",
      brought: (when, n) => (n ? `Read ${when} · brought ${n}` : `Read ${when} · nothing new`),
      lastRead: (when) => `Last read ${when}`,
      ago: {
        now: "just now",
        m: (n) => `${n} min ago`,
        h: (n) => (n === 1 ? "1 hour ago" : `${n} hours ago`),
        d: (n) => (n === 1 ? "yesterday" : `${n} days ago`),
      },

      mail: "Mail",
      mailAbout: "Reads newsletters and notifications, and picks out what is worth your time.",
      mailReading: (n) => (n === 1 ? "Reading 1 mailbox" : `Reading ${n} mailboxes`),
      mailPaused: "Every mailbox is paused",
      mailUnavailable: "Mail cannot be reached right now. Come back in a little while.",
      mailReads: (letters) =>
        letters
          ? "Reads newsletters, notifications and the letters people write you. Read only: nothing is ever sent, deleted or marked. The password and what is read stay on this computer."
          : "Reads only newsletters and notifications, not the letters people write you. Read only: nothing is ever sent, deleted or marked. The password and what is read stay on this computer.",
      readThis: (address) => `Read ${address}`,
      removeMail: (address) => `Disconnect ${address}`,
      removeSure: "Disconnect this mailbox?",
      letters: "Read personal letters too",
      lettersNote: "Off, it reads only newsletters and notifications. On, it reads the letters people write you too.",
      addAnother: "Connect another mailbox",
      pickProvider: "Which mail do you use?",
      addressHelp: "Type the address and the mail it belongs to is picked; if it is not, pick it below.",
      pickFirst: "Type the address or pick the kind of mail, and the next step shows up.",
      openCode: (name) => `Open ${name}`,
      howTo: (name, secret) => `First, get the ${secret} from ${name}`,
      howToOther: "Here is how",
      help: "Their instructions",
      address: "Email address",
      host: "IMAP server",
      hostHelp: "Read over TLS on port 993; for another port write imap.example.com:995.",
      secretHelp: (secret) => `Paste the ${secret} you just made, not your usual password.`,
      secretHelpOther: "The password your mailbox gives mail apps.",
      signIn: "Connect",
      signingIn: "Signing in…",
      mailDone: (address) => `Connected ${address}. I am reading it now.`,
      mailShort: {
        mail_login_failed: "sign-in refused; the password may have expired",
        mail_unreachable: "the server cannot be reached",
        mail_refused: "the inbox would not open",
        mail_failed: "the server had a problem",
      },
      lastFailed: "Last read failed",
      pair: (who, what) => `${who}: ${what}`,

      discord: "Discord",
      discordAbout: "Reads new messages in the server channels you pick.",
      discordSoon: "Connecting Discord is almost ready.",
      discordUnavailable: "Discord cannot be reached right now. Come back in a little while.",
      discordIntro: "Discord is read through a bot you make yourself. It takes four steps:",
      discordSteps: [
        "Open the Discord Developer Portal, choose New Application at the top right and give it any name, such as personagent.",
        "Choose Bot on the left, find Message Content Intent, switch it on and choose Save Changes.",
        "On the same Bot page choose Reset Token, confirm, and copy the token it shows.",
        "Paste the token below and choose Connect.",
      ],
      devPortal: "Open the Developer Portal",
      token: "Bot token",
      tokenPlaceholder: "Paste the token",
      tokenHelp: "The token is the bot's password. It is kept only on this computer; never send it to anyone.",
      connecting: "Connecting…",
      botAs: (name) => `Connected as ${name}`,
      inviteTitle: "Invite it to your servers",
      inviteNote: "Pick a server on the page that opens and choose Authorize; you need Manage Server there. Then come back and choose Refresh.",
      invite: "Invite to a server",
      channels: "Channels to read",
      channelsNote: "New messages in the channels switched on are read; the rest are left alone.",
      channelCount: (on, all) => `${on} / ${all}`,
      noServers: "It is not in any server yet. Invite it with the button above, then choose Refresh.",
      noChannels: "It cannot see any text channels in this server.",
      readChannel: (name) => `Read #${name}`,
      discordReading: (n) => (n ? `Reading ${n} ${n === 1 ? "channel" : "channels"}` : "Connected, no channels picked yet"),
      discordReads:
        "Reads only the channels you switch on; it never speaks or changes anything. The token and the messages read stay on this computer.",
      disconnect: "Disconnect Discord",
      disconnecting: "Disconnecting…",

      a: {
        about: {
          qq: "Reads the groups that add your QQ bot and what is sent to it.",
          wechat: "Reads the words and links you send to WeChat's ClawBot.",
          bilibili: "Reads new videos and posts from the people you follow.",
          weibo: "Reads new posts from the people you follow.",
          zhihu: "Reads new answers, articles and videos from the people you follow.",
          youtube: "Reads new videos from the channels you paste.",
          outlook: "Reads the newsletters and notifications in your Outlook or Hotmail inbox.",
          slack: "Reads the Slack channels and direct messages you switch on.",
          github: "Reads your GitHub notifications: review requests and mentions.",
          matrix: "Reads the Matrix rooms you switch on that are not encrypted.",
        },
        start: { qr: "Show the QR code", browser: "Sign in", code: "Get a code", fields: "Connect", paste: "Connect" },
        starting: "Getting ready…",
        warnTitle: "Before you connect",
        warnOk: "I understand, go on",
        qrSay: (name) => `Scan this with ${name} on your phone`,
        qrNote: "Confirm on your phone as it asks, and this picks up on its own.",
        qrScanned: "Scanned. Confirm it on your phone.",
        browserOpened: "The sign-in page is open in your browser. Sign in and allow it, and this picks up on its own.",
        browserAgain: "Not there? Open it again",
        browserOpen: "Open the sign-in page in your browser. Sign in and allow it, and this picks up on its own.",
        openSignIn: "Open the sign-in page",
        copyLink: "Copy link",
        copy: "Copy",
        copied: "Copied",
        codeSay: (host) => `Open ${host} and enter this code:`,
        codeOpen: (host) => `Open ${host}`,
        windowSay: (name) => `A sign-in window is open. Sign in to ${name} there, and this picks up on its own.`,
        windowNote: "The window is personagent's own: the sign-in stays on this computer and does not touch your usual browser.",
        windowStop: "To stop, just close that window.",
        waiting: "Waiting for you to finish…",
        expired: "This attempt has expired.",
        again: "Start again",
        retry: "Try again",
        connectedAs: (account) => `Connected as ${account}`,
        connected: "Connected",
        reconnect: "Connect again",
        addMore: "Add more channels",
        choices: {
          qq: "Groups to read",
          slack: "Channels and messages to read",
          matrix: "Rooms to read",
          youtube: "Channels to read",
          other: "What to read",
        },
        choicesNote: "The ones switched on are read; the rest are left alone.",
        choicesEmpty: {
          qq: "No groups yet. Add the bot to a group and it shows up here in a little while.",
          slack: "No conversations read yet. Try Refresh.",
          matrix: "No rooms it can read yet; encrypted rooms are not listed.",
          other: "Nothing to pick here yet.",
        },
        choose: (name) => `Read ${name}`,
        invite: "Invite to more servers",
        disconnect: "Disconnect",
        disconnectSure: "Disconnect this account?",
        done: "Connected. I am reading it now.",
        unavailable: "The other accounts cannot be reached right now. Come back in a little while.",
        lookInside: "Open it to see what happened",
        short: {
          signed_out: "Signed out",
          page_changed: "Its pages changed; cannot read for now",
          unreachable: "Cannot be reached",
          limited: "Too many requests; reading later",
          failed: "Last read failed",
        },
      },

      errors: {
        accounts_unknown: "That kind of account is gone. Reload the page.",
        accounts_invalid: "What was sent is not right. Reload the page and try again.",
        local_only: "This step is done on the computer personagent runs on.",
        offline: "personagent cannot be reached. Close it and open it again.",
        qq_expired: "The QR code has expired. Get a new one.",
        qq_rejected: "QQ no longer takes this bot's credentials. Scan again to connect.",
        qq_offline: "The QQ bot is not live yet, or has gone offline. Check it on the QQ Open Platform.",
        qq_banned: "QQ has banned this bot.",
        qq_refused: "QQ refused the connection; the bot may not be allowed to receive group messages.",
        wechat_expired: "The QR code has expired. Get a new one.",
        wechat_no_qr: "WeChat did not give a QR code this time. Try again in a little while.",
        wechat_verify_needed: "WeChat wants an extra check. Finish it on your phone, then scan again.",
        wechat_blocked: "WeChat is not allowing this connection for now. Try again later.",
        wechat_paused: "WeChat paused the ClawBot. It is tried again on its own in a while.",
        wechat_session_expired: "The connection to WeChat has ended. Scan again to connect.",
        github_token_invalid: "That token is not right. Copy the whole string and paste it again.",
        github_token_refused:
          "That token cannot read notifications. Make a classic token from the link with only notifications ticked.",
        matrix_homeserver_invalid: "That server address is not right; it starts with https. If unsure, use matrix.org.",
        matrix_password_missing: "This server signs in with a password. Fill it in too.",
        matrix_login_unsupported: "This server's way of signing in is not supported yet.",
        matrix_login_rejected: "The user name or password is not right.",
        slack_port_busy: "Port 53134 on this computer, which Slack's sign-in needs, is taken by another program. Close it and try again.",
        youtube_invalid: "No channel was recognised. Paste one channel link or @handle per line.",
        youtube_not_found: "Those channels were not found. Check the links or handles.",
        mail_invalid: "The address or password is not in the right form. Check them and try again.",
        mail_login_failed: (secret) =>
          secret
            ? `Sign-in was refused. Check the address, and that you pasted the ${secret}, not your usual password.`
            : "Sign-in was refused. Check the address, the server and the password.",
        mail_unreachable: "The mail server cannot be reached. Check the connection and try again.",
        mail_exists: "That mailbox is already connected.",
        mail_refused: "Signed in, but the mailbox would not open the inbox. Check that IMAP is on in its settings.",
        mail_failed: "The mail server gave an unexpected answer. Try again in a little while.",
        mail_unknown: "That mailbox is gone. Reload the page.",
        discord_token_invalid: "That token is not right. On the Bot page choose Reset Token again and paste the whole string.",
        discord_unreachable: "Discord cannot be reached. Check the connection or proxy and try again.",
        discord_intent_missing: "Message Content Intent is not on yet. Switch it on on the Bot page, save, then connect again.",
        discord_invalid: "That does not look like a token. On the Bot page choose Reset Token and copy the whole new string.",
        discord_not_connected: "Discord is not connected yet. Paste a token and connect first.",
        discord_failed: "Discord gave an unexpected answer. Try again in a little while.",
        generic: "That did not work. Try once more.",
      },
      kinds: {
        invalid: () => "What was filled in is not right. Check it and try again.",
        not_ready: (name) => `Connecting ${name} is not ready yet. Coming soon.`,
        not_connected: (name) => `${name} is not connected yet. Connect it first.`,
        denied: (name) => `${name} did not allow it. Try again and choose to allow.`,
        expired: () => "It took too long and this attempt expired. Start again.",
        unreachable: (name) => `${name} cannot be reached. Check the connection or proxy and try again.`,
        failed: (name) => `${name} gave an unexpected answer. Try again in a little while.`,
        limited: (name) => `${name} says there were too many requests. Try again in a little while.`,
        signed_out: (name) => `The sign-in to ${name} has ended. Connect it again.`,
        window_closed: () => "The sign-in window was closed. To connect, start again.",
        browser_missing: () => "No Edge or Chrome was found on this computer. Install one and try again.",
        browser_support_missing: () =>
          "This copy lacks what opens the sign-in window. Use a copy with web support and try again.",
        browser_start_failed: () => "The sign-in window did not open. Try again.",
        page_changed: (name) => `${name} changed its pages and cannot be read for now, until personagent is updated.`,
      },
    },
  };
  // While mail is being read the page asks this often how it went.
  const POLL_MS = 2500;
  const DEV_PORTAL = "https://discord.com/developers/applications";
  const SVG = "http://www.w3.org/2000/svg";
  const MAIL = ["M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 17V7A1.5 1.5 0 0 1 5 5.5z", "M4 7l8 6 8-6"];
  const DISCORD = [
    "M7.5 6.5c1.4-.6 2.9-1 4.5-1s3.1.4 4.5 1c1.6 2.4 2.5 5 2.5 8.2-1.4 1.2-3 2-4.6 2.3l-.9-1.5",
    "M7.5 6.5C5.9 8.9 5 11.5 5 14.7c1.4 1.2 3 2 4.6 2.3l.9-1.5",
    "M8.5 15c2.2.9 4.8.9 7 0",
    "M9.6 11.8h.01",
    "M14.4 11.8h.01",
  ];
  const WECHAT = [
    "M10 5C6.1 5 3 7.5 3 10.6c0 1.7.9 3.2 2.4 4.3l-.6 2.2 2.6-1.3c.8.2 1.7.4 2.6.4",
    "M15.5 9.8c3 0 5.5 2 5.5 4.5 0 1.3-.7 2.5-1.8 3.3l.4 1.9-2.1-1.1c-.6.2-1.3.3-2 .3-3 0-5.5-2-5.5-4.4s2.5-4.5 5.5-4.5z",
  ];
  const CHECK = ["M5 12.5l4.5 4.5L19 7.5"];
  const CROSS = ["M7 7l10 10", "M17 7L7 17"];
  const PLUS = ["M12 5v14", "M5 12h14"];
  const OUT = ["M14 5h5v5", "M19 5l-8 8", "M17 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h4"];
  const SHIELD = ["M12 3.5l7 2.6v5.3c0 4.4-3 7.9-7 9.1-4-1.2-7-4.7-7-9.1V6.1z", "M9 12l2.2 2.2L15.5 10"];
  const REFRESH = ["M4.5 12a7.5 7.5 0 0 1 13-5.1", "M19.5 12a7.5 7.5 0 0 1-13 5.1", "M17.5 3.5v3.6h-3.6", "M6.5 20.5v-3.6h3.6"];
  const EYE = ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z", "M12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6z"];
  const EYE_OFF = ["M4 4l16 16", "M9.9 5.8c.7-.2 1.4-.3 2.1-.3 6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.4", "M6.5 7.6C3.9 9.3 2.5 12 2.5 12S6 18.5 12 18.5c1.6 0 3-.5 4.2-1.1", "M10 10a2.8 2.8 0 0 0 4 4"];
  const HASH = ["M10 4L8 20", "M16 4l-2 16", "M4.5 9h15", "M4 15h15"];
  const PLAY = ["M4.5 7.5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-9a3 3 0 0 1-3-3z", "M10.5 9.3v5.4l4.5-2.7z"];
  const COPY = ["M9 9h9.5a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z", "M15.5 9V5.5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1V15a1 1 0 0 0 1 1h3"];
  const INFO = ["M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z", "M12 11v5", "M12 7.8h.01"];

  // The other accounts (GET /api/accounts) are listed after mail, in this order, and Discord last:
  // its own card stands for its entry. One not ready yet waits under "On the way".
  const ORDER = ["qq", "wechat", "bilibili", "weibo", "zhihu", "youtube", "outlook", "slack", "github", "matrix"];
  // Every mark is a plain line drawing in the service's colour.
  const PENGUIN = [
    "M12 3.5c-2.9 0-4.7 2.4-4.7 5.6 0 1.2-.8 2.3-1.6 3.7-.9 1.7-1 3.3-.4 3.6.5.2 1.1-.5 1.5-1.2.3 1.1 1 2 1.8 2.6",
    "M12 3.5c2.9 0 4.7 2.4 4.7 5.6 0 1.2.8 2.3 1.6 3.7.9 1.7 1 3.3.4 3.6-.5.2-1.1-.5-1.5-1.2-.3 1.1-1 2-1.8 2.6",
    "M8.6 17.8c-1.1.4-1.8.9-1.8 1.4 0 .8 1.6 1.3 3.3 1.3.8 0 1.4-.2 1.9-.5.5.3 1.1.5 1.9.5 1.7 0 3.3-.5 3.3-1.3 0-.5-.7-1-1.8-1.4",
    "M10.3 8.6h.01",
    "M13.7 8.6h.01",
  ];
  const TV = ["M4.5 8.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2z", "M8.5 3.5l2.5 3", "M15.5 3.5l-2.5 3", "M9.5 11.5v1.5", "M14.5 11.5v1.5"];
  const WEIBO = [
    "M10.5 9.5c-3.9 0-7 2.3-7 5s3.1 4.5 7 4.5 7-1.9 7-4.5-3.1-5-7-5z",
    "M10 13a1.7 1.7 0 1 1 0 3.4 1.7 1.7 0 0 1 0-3.4z",
    "M15.5 4.5a4.5 4.5 0 0 1 4 4.5",
    "M15.3 7.3a1.9 1.9 0 0 1 1.7 1.8",
  ];
  const ASK = ["M6 4.5h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z", "M10 9a2 2 0 1 1 2.8 1.8c-.5.3-.8.7-.8 1.2", "M12 14h.01"];
  const OCTOCAT = [
    "M9.5 20v-2.6c-2.6.6-3.2-1.2-3.2-1.2",
    "M14.5 20v-2.9c0-.8-.3-1.3-.6-1.6 2-.2 4-1 4-4.4 0-1-.3-1.8-.9-2.4.1-.3.4-1.2-.1-2.5 0 0-.8-.2-2.5.9a8.5 8.5 0 0 0-4.4 0C8.3 4.9 7.5 5.2 7.5 5.2c-.5 1.3-.2 2.2-.1 2.5-.6.6-.9 1.4-.9 2.4 0 3.4 2 4.2 4 4.4-.3.2-.5.6-.6 1.1",
  ];
  const BRACKETS = ["M7 4.5H4.5v15H7", "M17 4.5h2.5v15H17", "M8.5 15v-5.2", "M8.5 11c0-.9.7-1.4 1.6-1.4s1.7.5 1.7 1.4v4", "M11.8 11c0-.9.7-1.4 1.6-1.4s1.7.5 1.7 1.4v4"];
  const MARKS = { qq: PENGUIN, wechat: WECHAT, bilibili: TV, weibo: WEIBO, zhihu: ASK, youtube: PLAY, outlook: MAIL,
                  slack: HASH, github: OCTOCAT, matrix: BRACKETS };
  // While a sign-in waits, the page asks this often how it went. It goes on while Settings is out of
  // sight: some connectors finish a sign-in only when asked (a site's window, a scanned code).
  const ACCOUNT_POLL_MS = 2000;
  const WAITING = new Set(["browser", "code", "qr", "window"]);
  // Signed in through personagent's own window, which only the page's asking ends.
  const SITES = new Set(["bilibili", "weibo", "zhihu"]);

  let ctx, t;
  let root, mailCard, discordCard, cardList, accountsNote, later, laterGrid;
  // key -> {entry, card, parts, flow, timer}
  const accounts = new Map();
  let placed = "";
  // A site's sign-in left open before the page was last loaded is looked for once.
  let resumed = false;
  // Signing in opens things on the computer personagent runs on, so another device cannot start one.
  const remote = () => Boolean(ctx.state?.remote);
  let mail = null;
  let mailFailed = false;
  let discord = null;
  // "soon" while the page server has no Discord yet, "failed" when it could not be read.
  let discordWhy = "";
  let provider = "";
  let adding = false;
  let mailTimer = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function icon(paths, cls = "places-icon") {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls);
    for (const d of paths) {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }

  function button(cls, text, onClick, paths) {
    const node = el("button", `places-btn ${cls}`);
    node.type = "button";
    if (paths) node.append(icon(paths));
    if (text) node.append(el("span", "", text));
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }

  // A button that says it is working while `work` runs, and is itself again after.
  async function busy(node, words, work) {
    const label = node.querySelector("span");
    const was = label ? label.textContent : "";
    node.disabled = true;
    node.classList.add("places-busy");
    if (label && words) label.textContent = words;
    try {
      return await work();
    } finally {
      if (node.isConnected) {
        node.disabled = false;
        node.classList.remove("places-busy");
        if (label) label.textContent = was;
      }
    }
  }

  // A step that cannot be undone, such as a disconnect, asks once in the middle of the window.
  function confirmClick(node, sure, work) {
    node.addEventListener("click", async () => {
      if (await ctx.confirm({ title: sure, ok: t.a.disconnect })) await work();
    });
    return node;
  }

  function outLink(cls, text, href) {
    const node = el("a", `places-btn ${cls}`);
    node.href = href;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    node.append(el("span", "", text), icon(OUT));
    return node;
  }

  function switchFor(on, label, changed) {
    const box = el("input", "places-switch");
    box.type = "checkbox";
    box.setAttribute("role", "switch");
    box.checked = on;
    box.setAttribute("aria-label", label);
    box.addEventListener("change", () => changed(box));
    return box;
  }

  // A labelled field: the label above, then the control, then a line of help.
  function field(label, control, help) {
    const box = el("label", "places-field");
    box.append(el("span", "places-label", label), control);
    if (help) box.append(el("span", "places-help", help));
    return box;
  }

  function input(type, placeholder) {
    const node = el("input", "places-input");
    node.type = type;
    node.autocomplete = "off";
    node.spellcheck = false;
    node.required = true;
    if (placeholder) node.placeholder = placeholder;
    return node;
  }

  // A secret: hidden as typed, with a button inside its end to show it.
  function secretInput(placeholder) {
    const wrap = el("span", "places-secret");
    const node = input("password", placeholder);
    node.classList.add("places-secret-input");
    const reveal = el("button", "places-reveal");
    reveal.type = "button";
    const paint = () => {
      const shown = node.type === "text";
      reveal.replaceChildren(icon(shown ? EYE_OFF : EYE), el("span", "", shown ? t.hide : t.show));
      reveal.setAttribute("aria-pressed", String(shown));
    };
    reveal.addEventListener("click", () => {
      node.type = node.type === "password" ? "text" : "password";
      paint();
      node.focus();
    });
    paint();
    wrap.append(node, reveal);
    return { wrap, node };
  }

  function alertBox() {
    const box = el("div", "places-alert");
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

  function note(paths, words) {
    const box = el("p", "places-note");
    box.append(icon(paths), el("span", "", words));
    return box;
  }

  function failure(error, secret) {
    const said = t.errors[error?.message] || t.errors.generic;
    return typeof said === "function" ? said(secret) : said;
  }

  function ago(when) {
    const at = typeof when === "number" ? when * 1000 : Date.parse(when);
    if (!at) return "";
    const minutes = Math.max(0, Math.round((Date.now() - at) / 60000));
    if (minutes < 1) return t.ago.now;
    if (minutes < 60) return t.ago.m(minutes);
    if (minutes < 60 * 24) return t.ago.h(Math.round(minutes / 60));
    return t.ago.d(Math.round(minutes / 1440));
  }

  // ------------------------------------------------------------ one card --

  // Every kind of account is the same card: a mark, its name and state, one line,
  // and a body that opens in place with that kind's own flow.
  function card(kind, name, mark) {
    const node = el("section", `places-card places-card-${kind}`);
    const head = el("div", "places-card-head");
    const badge = el("span", `places-mark places-mark-${kind}`);
    badge.setAttribute("aria-hidden", "true");
    if (typeof mark === "string") badge.append(el("span", "places-mark-text", mark));
    else badge.append(icon(mark, "places-mark-icon"));
    const words = el("div", "places-card-words");
    const top = el("div", "places-card-top");
    const pill = el("span", "places-pill");
    top.append(el("h3", "places-card-title", name), pill);
    const line = el("p", "places-card-line");
    words.append(top, line);
    const action = el("button", "places-btn places-btn-sm");
    action.type = "button";
    action.hidden = true;
    head.append(badge, words, action);
    const body = el("div", "places-card-body");
    body.id = `places-body-${kind}`;
    body.hidden = true;
    action.setAttribute("aria-controls", body.id);
    node.append(head, body);

    const self = {
      node,
      body,
      state: "",
      get open() {
        return !body.hidden;
      },
      set(state, words, openable = true) {
        self.state = state;
        node.dataset.state = state;
        pill.textContent = state ? t.state[state] : "";
        pill.hidden = !state;
        line.textContent = words;
        action.hidden = !openable;
        if (!openable) self.toggle(false);
        paintAction();
      },
      toggle(open = body.hidden) {
        const opening = open && body.hidden;
        body.hidden = !open;
        node.classList.toggle("places-card-open", open);
        if (self.state) paintAction();
        if (opening && self.onOpen) self.onOpen();
      },
      onOpen: null,
    };
    function paintAction() {
      const open = !body.hidden;
      action.className = `places-btn places-btn-sm ${
        open ? "places-btn-ghost" : "places-btn-secondary"
      }`;
      action.textContent = open ? t.close : self.state === "off" ? t.connect : t.manage;
      action.setAttribute("aria-expanded", String(open));
    }
    action.addEventListener("click", () => self.toggle());
    return self;
  }

  // ------------------------------------------------------------- the page --

  // Settings holds it as a section of its own, which brings its own heading.
  function mount(node, context) {
    ctx = context;
    t = WORDS[ctx.lang === "zh" ? "zh" : "en"];
    root = el("div", "places-root");
    root.lang = ctx.lang === "zh" ? "zh-CN" : "en";

    mailCard = card("mail", t.mail, MAIL);
    discordCard = card("discord", t.discord, DISCORD);
    mailCard.set("", "", false);
    discordCard.set("", "", false);
    cardList = el("div", "places-cards");
    cardList.append(mailCard.node, discordCard.node);

    // Kinds with no way in yet: the same card, with no flow to open.
    later = el("div", "places-later");
    laterGrid = el("div", "places-later-grid");
    later.append(el("h4", "places-later-title", t.later), laterGrid);
    later.hidden = true;

    // Said when the other accounts could not be listed at all.
    accountsNote = note(INFO, t.a.unavailable);
    accountsNote.classList.add("places-note-expired", "places-accounts-note");
    accountsNote.hidden = true;

    mountMail();
    mountDiscord();
    root.append(cardList, accountsNote, later);
    node.replaceChildren(root);
  }

  function show() {
    loadMail();
    loadDiscord();
    loadAccounts();
  }

  // ---------------------------------------------------------------- mail --

  let mailParts;

  function mountMail() {
    const reads = note(SHIELD, "");
    const done = el("div", "places-done");
    done.hidden = true;
    const accounts = el("div", "places-list");
    const option = el("label", "places-option");
    const optionWords = el("span", "places-row-words");
    optionWords.append(el("span", "places-row-name", t.letters), el("span", "places-row-about", t.lettersNote));
    const letters = switchFor(false, t.letters, async (box) => {
      try {
        mail = await ctx.api("mail/options", { letters: box.checked });
        drawMail();
      } catch {
        box.checked = !box.checked;
      }
    });
    option.append(optionWords, letters);
    const form = el("div", "places-mail-connect");
    mailCard.body.append(reads, done, accounts, option, form);
    mailParts = { reads, done, accounts, option, letters, form, formKey: "" };
  }

  async function loadMail() {
    clearTimeout(mailTimer);
    try {
      mail = await ctx.api(`mail?lang=${ctx.lang === "zh" ? "zh" : "en"}`);
      mailFailed = false;
    } catch {
      mailFailed = true;
    }
    drawMail();
  }

  function drawMail() {
    if (mailFailed && !mail) {
      mailCard.set("problem", t.mailUnavailable, false);
      return;
    }
    const on = mail.accounts.filter((a) => a.on);
    const broken = on.find((a) => a.error);
    const last = on.map((a) => a.at).filter(Boolean).sort().pop();
    if (!mail.accounts.length) mailCard.set("off", t.mailAbout);
    else if (broken) mailCard.set("problem", t.pair(broken.address, t.mailShort[broken.error] || t.errors.generic));
    else if (!on.length) mailCard.set("paused", t.mailPaused);
    else mailCard.set("on", [t.mailReading(on.length), last && t.lastRead(ago(last))].filter(Boolean).join(" · "));

    const { reads, accounts, option, letters } = mailParts;
    reads.lastChild.textContent = t.mailReads(mail.letters);
    accounts.hidden = option.hidden = !mail.accounts.length;
    letters.checked = mail.letters;
    accounts.replaceChildren(...mail.accounts.map(accountRow));
    drawMailForm();

    // Asked until the read ends, also while Settings is out of sight; a read takes a few seconds.
    clearTimeout(mailTimer);
    if (mail.running) mailTimer = setTimeout(loadMail, POLL_MS);
  }

  function accountRow(account) {
    const row = el("div", "places-row");
    row.classList.toggle("places-row-off", !account.on);
    const named = mail.providers.find((p) => p.key === account.provider);
    const words = el("div", "places-row-words");
    const status = el("span", "places-row-status");
    if (account.error) {
      status.classList.add("places-row-status-error");
      status.textContent = `${t.lastFailed} · ${t.mailShort[account.error] || t.errors.generic}`;
    } else status.textContent = account.at ? t.brought(ago(account.at), account.count) : t.unread;
    words.append(
      el("span", "places-row-name", account.address),
      el("span", "places-row-about", named ? named.name : account.provider),
      status,
    );
    const toggle = switchFor(account.on, t.readThis(account.address), async (box) => {
      try {
        mail = await ctx.api("mail/toggle", { key: account.key, on: box.checked });
        drawMail();
      } catch {
        box.checked = !box.checked;
      }
    });
    const remove = el("button", "places-remove");
    remove.type = "button";
    remove.title = t.removeMail(account.address);
    remove.setAttribute("aria-label", t.removeMail(account.address));
    remove.append(icon(CROSS));
    // Its app password goes with it, so it asks first.
    confirmClick(remove, t.removeSure, async () => {
      remove.disabled = true;
      try {
        mail = await ctx.api("mail/remove", { key: account.key });
        mailParts.done.hidden = true;
        drawMail();
      } catch {
        remove.disabled = false;
      }
    });
    row.append(words, toggle, remove);
    return row;
  }

  // The connect flow: the address and the kinds of mail are built once each time it opens, and the
  // rest again only when the kind changes, so typing is never lost.
  function drawMailForm() {
    const open = adding || !mail.accounts.length;
    const key = open ? "open" : "closed";
    if (key !== mailParts.formKey) {
      mailParts.formKey = key;
      mailParts.detailKey = null;
      const box = mailParts.form;
      if (!open) {
        box.className = "places-mail-connect places-mail-connect-closed";
        box.replaceChildren(
          button("places-btn-dashed", t.addAnother, () => {
            adding = true;
            drawMailForm();
            mailParts.address?.focus();
          }, PLUS),
        );
        return;
      }
      box.className = "places-mail-connect";
      box.replaceChildren(mailForm());
    }
    if (open) drawMailDetail();
  }

  // The kind of mail an address belongs to, by its domain.
  function providerOf(address) {
    const domain = address.trim().toLowerCase().split("@")[1] || "";
    return mail.providers.find((p) => (p.domains || []).includes(domain))?.key || "";
  }

  function closeMailForm() {
    adding = false;
    provider = "";
    drawMailForm();
  }

  // One paste: the address picks its kind of mail, a button opens the page where the code is made,
  // and only the code is asked for after it.
  function mailForm() {
    const form = el("form", "places-form");
    const address = input("email", "you@example.com");
    address.inputMode = "email";
    address.addEventListener("input", () => {
      const found = providerOf(address.value);
      if (found && found !== provider) {
        provider = found;
        drawMailDetail();
      }
    });
    const chips = el("div", "places-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-label", t.pickProvider);
    for (const p of mail.providers) {
      const chip = el("button", "places-chip", p.name);
      chip.type = "button";
      chip.dataset.key = p.key;
      chip.addEventListener("click", () => {
        provider = provider === p.key ? "" : p.key;
        drawMailDetail();
      });
      chips.append(chip);
    }
    const kinds = el("div", "places-field");
    kinds.append(el("span", "places-label", t.pickProvider), chips);
    const fields = el("div", "places-fields");
    fields.append(field(t.address, address, t.addressHelp), kinds);
    const detail = el("div", "places-mail-detail");

    const said = alertBox();
    const go = el("button", "places-btn places-btn-primary");
    go.type = "submit";
    go.append(el("span", "", t.signIn));
    const actions = el("div", "places-actions");
    actions.append(go);
    if (mail.accounts.length) actions.append(button("places-btn-ghost", t.cancel, closeMailForm));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const chosen = mail.providers.find((p) => p.key === provider);
      if (!chosen) return;
      const { host, secret } = mailParts;
      said.clear();
      for (const node of [address, host, secret]) node?.removeAttribute("aria-invalid");
      await busy(go, t.signingIn, async () => {
        try {
          mail = await ctx.api("mail/add", {
            provider: chosen.key,
            address: address.value.trim(),
            secret: secret.value.trim(),
            ...(host ? { host: host.value.trim() } : {}),
          });
          const added = address.value.trim();
          secret.value = "";
          adding = false;
          provider = "";
          const done = mailParts.done;
          const mark = el("span", "places-done-mark");
          mark.append(icon(CHECK));
          done.replaceChildren(mark, el("span", "", t.mailDone(added)));
          done.hidden = false;
          drawMail();
        } catch (error) {
          said.say(failure(error, chosen.host ? chosen.secret : ""));
          const blame = error.message === "mail_login_failed" ? secret : error.message === "mail_invalid" ? address : null;
          blame?.setAttribute("aria-invalid", "true");
        }
      });
    });
    form.append(fields, detail, said.box, actions);
    Object.assign(mailParts, { address, chips, detail, go, host: null, secret: null });
    return form;
  }

  function drawMailDetail() {
    const { chips, detail, go } = mailParts;
    for (const chip of chips.children) chip.setAttribute("aria-pressed", String(chip.dataset.key === provider));
    const chosen = mail.providers.find((p) => p.key === provider);
    go.hidden = !chosen;
    if (mailParts.detailKey === provider) return;
    mailParts.detailKey = provider;
    if (!chosen) {
      mailParts.host = mailParts.secret = null;
      detail.replaceChildren(el("p", "places-wait-line", t.pickFirst));
      return;
    }
    const how = el("div", "places-how");
    const howHead = el("div", "places-how-head");
    // "Other" asks for its own password, not a code made elsewhere.
    const other = !chosen.host;
    howHead.append(el("p", "places-how-title", other ? t.howToOther : t.howTo(chosen.name, chosen.secret)));
    if (chosen.help) howHead.append(outLink("places-btn-link", t.help, chosen.help));
    const steps = el("ol", "places-steps");
    for (const step of chosen.steps) steps.append(el("li", "", step));
    how.append(howHead, steps);
    if (chosen.code) {
      const open = el("div", "places-how-open");
      open.append(outLink("places-btn-secondary places-btn-sm", t.openCode(chosen.name), chosen.code));
      how.append(open);
    }
    const fields = el("div", "places-fields");
    let host = null;
    if (!chosen.host) {
      host = input("text", "imap.example.com");
      fields.append(field(t.host, host, t.hostHelp));
    }
    const secret = secretInput(chosen.secret);
    const label = chosen.secret.charAt(0).toUpperCase() + chosen.secret.slice(1);
    fields.append(field(label, secret.wrap, other ? t.secretHelpOther : t.secretHelp(chosen.secret)));
    mailParts.host = host;
    mailParts.secret = secret.node;
    detail.replaceChildren(how, fields);
  }

  // ------------------------------------------------------------- discord --

  let discordParts;

  function mountDiscord() {
    const reads = note(SHIELD, t.discordReads);
    const said = alertBox();
    const connect = el("div", "places-discord-connect");
    const connected = el("div", "places-discord-on");
    discordCard.body.append(reads, said.box, connect, connected);
    discordParts = { reads, said, connect, connected, shown: "" };
  }

  async function loadDiscord() {
    try {
      discord = await ctx.api("discord");
      discordWhy = "";
    } catch (error) {
      // FastAPI's own answer for a route that is not there: the backend has not landed yet.
      discordWhy = error.message === "Not Found" ? "soon" : "failed";
    }
    drawDiscord();
  }

  async function discordDo(path, payload) {
    await ctx.api(`discord/${path}`, payload || {});
    discord = await ctx.api("discord");
    drawDiscord();
  }

  function channelsOn() {
    return discord.servers.flatMap((s) => s.channels.filter((c) => c.on).map((c) => c.id));
  }

  function paintDiscordCard() {
    if (discordWhy === "soon") return discordCard.set("soon", t.discordSoon, false);
    if (discordWhy === "failed" && !discord) return discordCard.set("problem", t.discordUnavailable, false);
    const n = discord.connected ? channelsOn().length : 0;
    // The sentence itself is said once, inside.
    if (discord.problem) discordCard.set("problem", t.a.lookInside);
    else if (!discord.connected) discordCard.set("off", t.discordAbout);
    else discordCard.set("on", [t.discordReading(n), discord.last && t.lastRead(ago(discord.last))].filter(Boolean).join(" · "));
  }

  function drawDiscord() {
    paintDiscordCard();
    if (!discord) return;
    const { said, connect, connected } = discordParts;
    if (discord.problem) said.say(failure({ message: discord.problem }));
    else said.clear();
    connect.hidden = discord.connected;
    connected.hidden = !discord.connected;
    // The token form is built once per stretch of not being connected, so what is typed stays.
    if (!discord.connected && discordParts.shown !== "connect") {
      discordParts.shown = "connect";
      connect.replaceChildren(discordForm());
    }
    if (discord.connected) {
      discordParts.shown = "connected";
      connected.replaceChildren(...discordConnected());
    }
  }

  function discordForm() {
    const form = el("form", "places-form");
    form.append(el("p", "places-intro", t.discordIntro));
    const steps = el("ol", "places-steps places-steps-big");
    t.discordSteps.forEach((words, n) => {
      const step = el("li", "", words);
      if (n === 0) {
        const link = outLink("places-btn-secondary places-btn-sm", t.devPortal, DEV_PORTAL);
        step.append(el("br"), link);
      }
      steps.append(step);
    });
    const token = secretInput(t.tokenPlaceholder);
    const fields = el("div", "places-fields");
    fields.append(field(t.token, token.wrap, t.tokenHelp));
    const said = alertBox();
    const go = el("button", "places-btn places-btn-primary");
    go.type = "submit";
    go.append(el("span", "", t.connect));
    const actions = el("div", "places-actions");
    actions.append(go);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      said.clear();
      token.node.removeAttribute("aria-invalid");
      await busy(go, t.connecting, async () => {
        try {
          await discordDo("connect", { token: token.node.value.trim() });
          token.node.value = "";
        } catch (error) {
          said.say(failure(error));
          if (error.message === "discord_token_invalid" || error.message === "discord_invalid")
            token.node.setAttribute("aria-invalid", "true");
        }
      });
    });
    form.append(steps, fields, said.box, actions);
    return form;
  }

  // The account a card is connected to: green with a tick, or amber with a mark while it has a problem.
  function accountBar(problem) {
    const bar = el("div", problem ? "places-bot places-bot-problem" : "places-bot");
    const mark = el("span", "places-bot-mark");
    if (problem) mark.append(el("span", "places-bot-bang", "!"));
    else mark.append(icon(CHECK));
    bar.append(mark);
    return bar;
  }

  function discordConnected() {
    const bot = accountBar(Boolean(discord.problem));
    const words = el("div", "places-row-words");
    const named = discord.problem ? discord.bot.name : t.botAs(discord.bot.name);
    words.append(el("span", "places-row-name", named), el("span", "places-row-about places-mono", discord.bot.id));
    const refresh = button("places-btn-secondary places-btn-sm", t.refresh, async () => {
      await busy(refresh, t.refreshing, async () => {
        try {
          await discordDo("refresh");
        } catch (error) {
          discordParts.said.say(failure(error));
        }
      });
    }, REFRESH);
    bot.append(words, refresh);

    const invite = el("div", "places-invite");
    const inviteWords = el("div", "places-row-words");
    inviteWords.append(el("span", "places-step-title", t.inviteTitle), el("span", "places-row-about", t.inviteNote));
    invite.append(inviteWords, outLink("places-btn-secondary", t.invite, discord.invite));

    const channels = el("div", "places-channels");
    const channelsHead = el("div", "places-sub-head");
    channelsHead.append(el("span", "places-step-title", t.channels), el("span", "places-row-about", t.channelsNote));
    channels.append(channelsHead);
    if (!discord.servers.length) channels.append(el("p", "places-empty", t.noServers));
    for (const server of discord.servers) channels.append(serverBox(server));

    const foot = el("div", "places-foot");
    const remove = button("places-btn-danger places-btn-sm", t.disconnect);
    confirmClick(remove, t.a.disconnectSure, () =>
      busy(remove, t.disconnecting, async () => {
        try {
          await discordDo("remove");
        } catch (error) {
          discordParts.said.say(failure(error));
        }
      }),
    );
    foot.append(remove);
    return [bot, invite, channels, foot];
  }

  function serverBox(server) {
    const box = el("div", "places-server");
    const head = el("div", "places-server-head");
    const initial = el("span", "places-server-mark", Array.from(server.name.trim())[0] || "#");
    const on = server.channels.filter((c) => c.on).length;
    const count = el("span", "places-count", t.channelCount(on, server.channels.length));
    count.classList.toggle("places-count-some", on > 0);
    head.append(initial, el("span", "places-server-name", server.name), count);
    box.append(head);
    if (!server.channels.length) box.append(el("p", "places-empty", t.noChannels));
    for (const channel of server.channels) {
      const row = el("label", "places-channel");
      row.classList.toggle("places-row-off", !channel.on);
      const name = el("span", "places-channel-name");
      name.append(icon(HASH, "places-icon places-hash"), el("span", "", channel.name));
      row.append(
        name,
        switchFor(channel.on, t.readChannel(channel.name), async (box) => {
          // Painted in place, so the switch just used keeps its focus.
          const paint = () => {
            row.classList.toggle("places-row-off", !channel.on);
            const lit = server.channels.filter((c) => c.on).length;
            count.textContent = t.channelCount(lit, server.channels.length);
            count.classList.toggle("places-count-some", lit > 0);
            paintDiscordCard();
          };
          channel.on = box.checked;
          paint();
          try {
            await ctx.api("discord/channels", { on: channelsOn() });
          } catch (error) {
            channel.on = box.checked = !box.checked;
            paint();
            discordParts.said.say(failure(error));
          }
        }),
      );
      box.append(row);
    }
    return box;
  }

  // ------------------------------------------------------------ accounts --

  const pick = (pair) => (Array.isArray(pair) ? pair[ctx.lang === "zh" ? 1 : 0] : pair || "");
  const nameOf = (entry) => pick(entry.name);

  // What a code means, for this account: its own sentence, else one by what follows its key.
  function says(code, entry) {
    if (!code) return t.errors.generic;
    const own = t.errors[code];
    if (own) return typeof own === "function" ? own() : own;
    const kind = entry && code.startsWith(`${entry.key}_`) ? code.slice(entry.key.length + 1) : "";
    return t.kinds[kind] ? t.kinds[kind](nameOf(entry)) : t.errors.generic;
  }
  const codeOf = (error) => (error instanceof TypeError ? "offline" : error?.message || "generic");
  // The same, in a few words for a card's line.
  function shortSays(code, entry) {
    const kind = code && entry && code.startsWith(`${entry.key}_`) ? code.slice(entry.key.length + 1) : "";
    return t.a.short[kind] || t.a.lookInside;
  }

  async function loadAccounts() {
    let listing;
    try {
      listing = await ctx.api("accounts");
    } catch {
      // The cards already drawn stay as they are; with none drawn, the list says what is missing.
      accountsNote.hidden = accounts.size > 0;
      return false;
    }
    accountsNote.hidden = true;
    for (const entry of listing.accounts) {
      if (entry.key === "discord") continue;
      const a = accounts.get(entry.key) || makeAccount(entry);
      a.entry = entry;
      drawAccount(a);
    }
    place();
    if (!resumed) {
      resumed = true;
      for (const a of accounts.values()) if (SITES.has(a.entry.key) && !a.entry.connected) resume(a);
    }
    return true;
  }

  // A site's window still open from before the page was loaded: its sign-in is waited for again.
  async function resume(a) {
    if (remote() || a.flow.phase !== "idle") return;
    try {
      const answer = await ctx.api(`accounts/poll?key=${encodeURIComponent(a.entry.key)}`);
      if (answer.state === "pending" && a.flow.phase === "idle") setFlow(a, { phase: "window" });
    } catch {
      // No window open (it answers window_closed): nothing to pick up.
    }
  }

  // Ready ones in the list, in ORDER, the rest under "On the way"; moved only when that changes.
  function place() {
    const rank = (key) => (ORDER.includes(key) ? ORDER.indexOf(key) : ORDER.length);
    const all = [...accounts.values()].sort((x, y) => rank(x.entry.key) - rank(y.entry.key));
    const ready = all.filter((a) => a.entry.ready);
    const soon = all.filter((a) => !a.entry.ready);
    const order = `${ready.map((a) => a.entry.key)}|${soon.map((a) => a.entry.key)}`;
    if (order === placed) return;
    placed = order;
    cardList.replaceChildren(mailCard.node, ...ready.map((a) => a.card.node), discordCard.node);
    laterGrid.replaceChildren(...soon.map((a) => a.card.node));
    later.hidden = !soon.length;
  }

  function makeAccount(entry) {
    const mark = MARKS[entry.key] || (Array.from(nameOf(entry))[0] || "?").toUpperCase();
    const c = card(entry.key, nameOf(entry), mark);
    const reads = note(SHIELD, "");
    const said = alertBox();
    const done = el("div", "places-done");
    done.hidden = true;
    const flow = el("div", "places-flow");
    const on = el("div", "places-account-on");
    c.body.append(reads, said.box, done, on, flow);
    const a = { entry, card: c, parts: { reads, said, done, flow, on }, flow: { phase: "idle" }, timer: 0, accepted: false };
    // Opened while not connected: a kind that only asks for fields shows them at once.
    c.onOpen = () => {
      const e = a.entry;
      if (!e.connected && !remote() && a.flow.phase === "idle" && (e.how === "fields" || e.how === "paste") &&
          !(e.warn && !a.accepted))
        begin(a);
    };
    accounts.set(entry.key, a);
    return a;
  }

  function paintAccount(a) {
    const e = a.entry;
    const c = a.card;
    const about = t.a.about[e.key] || pick(e.reads);
    if (!e.ready) return c.set("soon", about, false);
    if (WAITING.has(a.flow.phase) || a.flow.phase === "starting") return c.set("pending", about);
    if (e.connected && e.problem) return c.set("problem", [e.account, shortSays(e.problem, e)].filter(Boolean).join(" · "));
    if (e.connected)
      return c.set("on", [e.account, e.last ? t.lastRead(ago(e.last)) : t.unread].filter(Boolean).join(" · "));
    c.set("off", about);
  }

  function drawAccount(a) {
    const e = a.entry;
    paintAccount(a);
    if (!e.ready) return;
    const { reads, said, on } = a.parts;
    reads.lastChild.textContent = pick(e.reads);
    if (e.connected && e.problem) said.say(says(e.problem, e));
    else said.clear();
    on.hidden = !e.connected;
    if (e.connected) on.replaceChildren(...accountOn(a));
    else on.replaceChildren();
    drawFlow(a);
  }

  // ---- connecting

  function setFlow(a, flow) {
    clearTimeout(a.timer);
    a.flow = flow;
    if (flow.phase !== "idle") a.parts.done.hidden = true;
    paintAccount(a);
    drawFlow(a);
    if (WAITING.has(flow.phase)) follow(a);
  }

  async function begin(a, values = {}) {
    setFlow(a, { phase: "starting" });
    try {
      answered(a, await ctx.api("accounts/start", { key: a.entry.key, values }));
    } catch (error) {
      setFlow(a, { phase: "failed", error: codeOf(error) });
    }
  }

  // Each shape start() answers with.
  function answered(a, answer) {
    if (answer.done) return finish(a);
    if (answer.fields) return setFlow(a, { phase: "fields", fields: answer.fields, link: answer.link || "", error: answer.error || "" });
    if (answer.window) return setFlow(a, { phase: "window" });
    if ("browser" in answer) return setFlow(a, { phase: "browser", url: answer.browser, opened: Boolean(answer.opened) });
    if (answer.code) return setFlow(a, { phase: "code", code: answer.code, verify: answer.verify || "" });
    if (answer.qr) return setFlow(a, { phase: "qr", qr: answer.qr, scanned: false });
    setFlow(a, { phase: "failed", error: "generic" });
  }

  // Asks how the sign-in went until it is no longer waiting; a newer flow ends the old one.
  function follow(a) {
    const ticket = a.flow;
    a.timer = setTimeout(async () => {
      if (a.flow !== ticket) return;
      let answer;
      try {
        answer = await ctx.api(`accounts/poll?key=${encodeURIComponent(a.entry.key)}`);
      } catch (error) {
        // The app away for a moment: ask again. An answer with an error comes here too (ctx.api throws on it).
        const code = codeOf(error);
        answer = error instanceof TypeError ? { state: "pending" }
          : { state: code.endsWith("_expired") ? "expired" : "failed", error: code };
      }
      if (a.flow !== ticket) return;
      if (answer.state === "pending" || answer.state === "scanned") {
        if (answer.state === "scanned" && !ticket.scanned) {
          ticket.scanned = true;
          drawFlow(a);
        }
        return follow(a);
      }
      if (answer.state === "done") return finish(a);
      setFlow(a, { phase: answer.state === "expired" ? "expired" : "failed", error: answer.error || "" });
    }, ACCOUNT_POLL_MS);
  }

  async function finish(a) {
    // Drawn connected at once, so it never shows "connected" beside a Connect button while the list reloads.
    a.entry = { ...a.entry, connected: true, problem: "" };
    a.parts.said.clear();
    setFlow(a, { phase: "idle" });
    drawAccount(a);
    const done = a.parts.done;
    const mark = el("span", "places-done-mark");
    mark.append(icon(CHECK));
    done.replaceChildren(mark, el("span", "", t.a.done));
    done.hidden = false;
    await loadAccounts();
  }

  function cancelFlow(a) {
    setFlow(a, { phase: "idle" });
  }

  function waitLine(words = t.a.waiting) {
    const line = el("p", "places-wait-line places-waiting");
    line.append(el("span", "places-spinner"), el("span", "", words));
    return line;
  }

  function copyButton(text, label) {
    const node = button("places-btn-secondary places-btn-sm", label, null, COPY);
    const words = node.querySelector("span");
    node.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const area = el("textarea");
        area.value = text;
        document.body.append(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      words.textContent = t.a.copied;
      setTimeout(() => (words.textContent = label), 1600);
    });
    return node;
  }

  function hostOf(url) {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  function drawFlow(a) {
    const e = a.entry;
    const f = a.flow;
    const box = a.parts.flow;
    // Drawn again only when what it shows changes, so what is typed or scanned stays.
    const key = `${f.phase}:${f.scanned ? 1 : 0}:${e.connected ? 1 : 0}:${a.accepted ? 1 : 0}`;
    if (box.dataset.shown === key && box.flowOf === f) return;
    box.dataset.shown = key;
    box.flowOf = f;
    box.className = `places-flow places-flow-${f.phase}`;
    const cancel = () => button("places-btn-ghost places-btn-sm", t.cancel, () => cancelFlow(a));
    const actions = (...nodes) => {
      const row = el("div", "places-actions");
      row.append(...nodes);
      return row;
    };
    const startButton = (words = t.a.start[e.how] || t.connect) =>
      button("places-btn-primary", words, () => begin(a));

    if (f.phase === "idle") {
      if (e.connected) return box.replaceChildren();
      if (remote()) return box.replaceChildren(note(INFO, t.errors.local_only));
      if (e.warn && !a.accepted) {
        const warn = el("div", "places-warn");
        warn.setAttribute("role", "group");
        const head = el("p", "places-warn-title");
        head.append(icon(INFO), el("span", "", t.a.warnTitle));
        warn.append(
          head,
          el("p", "places-warn-text", pick(e.warn)),
          actions(button("places-btn-primary places-btn-sm", t.a.warnOk, () => {
            a.accepted = true;
            if (e.how === "fields" || e.how === "paste") begin(a);
            else setFlow(a, { phase: "idle" });
          })),
        );
        return box.replaceChildren(warn);
      }
      return box.replaceChildren(actions(startButton()));
    }
    if (f.phase === "starting") return box.replaceChildren(waitLine(t.a.starting));
    if (f.phase === "fields") return box.replaceChildren(fieldsForm(a, f));
    if (f.phase === "qr") {
      const panel = el("div", "places-wait-panel");
      const frame = el("div", "places-qr");
      const image = el("img");
      image.src = f.qr;
      image.alt = t.a.qrSay(nameOf(e));
      frame.append(image);
      const words = el("div", "places-wait-words");
      words.append(
        el("p", "places-step-title", t.a.qrSay(nameOf(e))),
        el("p", "places-row-about", t.a.qrNote),
        f.scanned ? el("p", "places-wait-line places-wait-ok", t.a.qrScanned) : waitLine(),
        actions(cancel()),
      );
      panel.append(frame, words);
      return box.replaceChildren(panel);
    }
    if (f.phase === "browser") {
      const words = el("div", "places-wait-words");
      words.append(el("p", "places-intro", f.opened ? t.a.browserOpened : t.a.browserOpen));
      const links = f.opened
        ? [outLink("places-btn-link", t.a.browserAgain, f.url)]
        : [outLink("places-btn-primary places-btn-sm", t.a.openSignIn, f.url), copyButton(f.url, t.a.copyLink)];
      words.append(actions(...links), waitLine(), actions(cancel()));
      return box.replaceChildren(words);
    }
    if (f.phase === "code") {
      const host = hostOf(f.verify);
      const words = el("div", "places-wait-words");
      const code = el("div", "places-code");
      code.append(el("span", "places-code-text", f.code), copyButton(f.code, t.a.copy));
      words.append(
        el("p", "places-intro", t.a.codeSay(host)),
        code,
        actions(outLink("places-btn-primary places-btn-sm", t.a.codeOpen(host), f.verify)),
        waitLine(),
        actions(cancel()),
      );
      return box.replaceChildren(words);
    }
    if (f.phase === "window") {
      const words = el("div", "places-wait-words");
      // No Cancel here: only the page's asking notices the sign-in and closes the window, so the
      // attempt ends when the person closes that window, and the asking goes on until then.
      words.append(
        el("p", "places-intro", t.a.windowSay(nameOf(e))),
        note(SHIELD, t.a.windowNote),
        waitLine(),
        el("p", "places-help", t.a.windowStop),
      );
      return box.replaceChildren(words);
    }
    // Expired or failed: what happened, and the way to start again.
    let told;
    // Nothing went wrong when it only waited too long, or the person closed the sign-in window.
    const soft = f.phase === "expired" || Boolean(f.error?.endsWith("_window_closed"));
    if (soft) {
      told = note(INFO, f.error ? says(f.error, e) : t.a.expired);
      told.classList.add("places-note-expired");
    } else {
      const said = alertBox();
      said.say(says(f.error, e));
      told = said.box;
    }
    const again = startButton(soft ? t.a.again : t.a.retry);
    box.replaceChildren(told, actions(again, ...(e.connected ? [cancel()] : [])));
  }

  function fieldsForm(a, f) {
    const e = a.entry;
    const form = el("form", "places-form");
    const fields = el("div", "places-fields");
    const controls = [];
    for (const ask of f.fields) {
      let node;
      let control;
      if (ask.multiline) {
        node = control = el("textarea", "places-input places-textarea");
        node.rows = 5;
        node.spellcheck = false;
      } else if (ask.secret) {
        const secret = secretInput("");
        node = secret.node;
        control = secret.wrap;
      } else {
        node = control = input("text");
      }
      node.required = false;
      node.name = ask.key;
      controls.push(node);
      fields.append(field(pick(ask.label), control, pick(ask.help)));
    }
    const said = alertBox();
    if (f.error) said.say(says(f.error, e));
    const go = el("button", "places-btn places-btn-primary");
    go.type = "submit";
    go.append(el("span", "", t.connect));
    const row = actions1(go);
    if (e.connected) row.append(button("places-btn-ghost", t.cancel, () => cancelFlow(a)));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = {};
      for (const node of controls) if (node.value.trim()) values[node.name] = node.value.trim();
      if (!Object.keys(values).length) return controls[0]?.focus();
      said.clear();
      await busy(go, t.connecting, async () => {
        try {
          answered(a, await ctx.api("accounts/start", { key: e.key, values }));
        } catch (error) {
          said.say(says(codeOf(error), e));
        }
      });
    });
    form.append(fields);
    if (f.link) form.append(actions1(outLink("places-btn-secondary places-btn-sm", t.a.codeOpen(hostOf(f.link)), f.link)));
    form.append(said.box, row);
    return form;
  }

  function actions1(...nodes) {
    const row = el("div", "places-actions");
    row.append(...nodes);
    return row;
  }

  // ---- connected

  function accountOn(a) {
    const e = a.entry;
    const nodes = [];
    const bar = accountBar(Boolean(e.problem));
    const words = el("div", "places-row-words");
    const status = e.last ? (a.count !== undefined ? t.brought(ago(e.last), a.count) : t.lastRead(ago(e.last))) : t.unread;
    // With a problem it does not claim to be connected: the account, and the alert above says the rest.
    const who = e.problem ? e.account || nameOf(e) : e.account ? t.a.connectedAs(e.account) : t.a.connected;
    words.append(el("span", "places-row-name", who), el("span", "places-row-about", status));
    const refresh = button("places-btn-secondary places-btn-sm", t.refresh, async () => {
      await busy(refresh, t.refreshing, async () => {
        try {
          const { count, ...entry } = await ctx.api("accounts/refresh", { key: e.key });
          a.entry = entry;
          a.count = count;
          a.parts.said.clear();
        } catch (error) {
          a.parts.said.say(says(codeOf(error), e));
          return;
        }
        drawAccount(a);
      });
    }, REFRESH);
    bar.append(words, refresh);
    nodes.push(bar);

    if (e.invite) {
      const invite = el("div", "places-invite");
      invite.append(outLink("places-btn-secondary", t.a.invite, e.invite));
      nodes.push(invite);
    }
    if (e.choices.length || ["qq", "slack", "matrix"].includes(e.key)) nodes.push(choicesBox(a));

    const foot = el("div", "places-foot places-foot-split");
    const left = el("div", "places-actions");
    // Both start a sign-in again, which only the computer personagent runs on can do.
    const again = remote() ? null : e.problem ? [t.a.reconnect, REFRESH] : e.key === "youtube" ? [t.a.addMore, PLUS] : null;
    if (again) left.append(button("places-btn-secondary places-btn-sm", again[0], () => begin(a), again[1]));
    const remove = button("places-btn-danger places-btn-sm", t.a.disconnect);
    confirmClick(remove, t.a.disconnectSure, () =>
      busy(remove, t.disconnecting, async () => {
        try {
          a.entry = await ctx.api("accounts/revoke", { key: e.key });
          a.count = undefined;
          a.parts.done.hidden = true;
          setFlow(a, { phase: "idle" });
          drawAccount(a);
        } catch (error) {
          a.parts.said.say(says(codeOf(error), e));
        }
      }),
    );
    foot.append(left, remove);
    nodes.push(foot);
    return nodes;
  }

  function choicesBox(a) {
    const e = a.entry;
    const box = el("div", "places-server");
    const head = el("div", "places-server-head");
    const count = el("span", "places-count");
    const paint = () => {
      const lit = a.entry.choices.filter((c) => c.on).length;
      count.textContent = t.channelCount(lit, a.entry.choices.length);
      count.classList.toggle("places-count-some", lit > 0);
    };
    head.append(el("span", "places-server-name", t.a.choices[e.key] || t.a.choices.other), count);
    box.append(head);
    if (!e.choices.length) box.append(el("p", "places-empty", t.a.choicesEmpty[e.key] || t.a.choicesEmpty.other));
    for (const choice of e.choices) {
      const row = el("label", "places-channel");
      row.classList.toggle("places-row-off", !choice.on);
      const name = el("span", "places-channel-name");
      name.append(el("span", "", choice.name));
      row.append(
        name,
        switchFor(choice.on, t.a.choose(choice.name), async (input) => {
          // Painted in place, so the switch just used keeps its focus.
          choice.on = input.checked;
          row.classList.toggle("places-row-off", !choice.on);
          paint();
          try {
            const entry = await ctx.api("accounts/choose", {
              key: e.key,
              on: a.entry.choices.filter((c) => c.on).map((c) => c.id),
            });
            a.entry = { ...entry, choices: a.entry.choices };
          } catch (error) {
            choice.on = input.checked = !input.checked;
            row.classList.toggle("places-row-off", !choice.on);
            paint();
            a.parts.said.say(says(codeOf(error), e));
          }
        }),
      );
      box.append(row);
    }
    paint();
    const wrap = el("div", "places-channels");
    wrap.append(box, el("p", "places-help", t.a.choicesNote));
    return wrap;
  }

  window.paPlaces = { mount, show };
})();
