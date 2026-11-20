"""The forty MiniWoB++ tasks this bench runs: what a browser helper for an ordinary person meets in small.
(name, group). Left out: drawing and dragging, canvas shapes and colours, timing and dexterity games, puzzles
and arithmetic, the terminal and text editor, and the -nodelay/-easy/-hard copies of a task already here."""

TASKS = [
    # clicking the right button or link
    ("click-button", "click"), ("click-button-sequence", "click"), ("click-link", "click"),
    ("click-dialog", "click"), ("click-dialog-2", "click"), ("click-widget", "click"),
    ("click-option", "click"), ("click-menu", "click"),
    # filling and submitting forms
    ("enter-text", "form"), ("enter-text-2", "form"), ("enter-date", "form"), ("enter-time", "form"),
    ("form-sequence-2", "form"), ("multi-layouts", "form"), ("multi-orderings", "form"),
    ("login-user", "form"), ("login-user-popup", "form"),
    # dropdowns and date pickers
    ("choose-list", "picker"), ("choose-date-easy", "picker"), ("choose-date", "picker"),
    # checkboxes, tabs, collapsibles, a tree
    ("click-checkboxes", "toggle"), ("click-checkboxes-soft", "toggle"), ("click-checkboxes-transfer", "toggle"),
    ("click-tab", "toggle"), ("click-tab-2", "toggle"), ("click-collapsible-2", "toggle"), ("navigate-tree", "toggle"),
    # search boxes and suggestions
    ("search-engine", "search"), ("use-autocomplete", "search"),
    # scrolling to find
    ("click-scroll-list", "scroll"), ("scroll-text", "scroll"),
    # reading a value and using it
    ("read-table", "read"), ("find-word", "read"), ("copy-paste", "read"), ("phone-book", "read"),
    # inbox-like and feed-like
    ("email-inbox", "inbox"), ("email-inbox-forward-nl", "inbox"), ("email-inbox-reply", "inbox"),
    ("social-media-some", "inbox"),
    # a flow over several screens
    ("book-flight", "flow"),
]
