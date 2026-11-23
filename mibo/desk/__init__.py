"""Mibo operating other programs on the computer, for the person, when they ask.

Off until the person turns it on in Settings. A program is found by the name the
person uses for it, the way Start finds one, and opened from Start when it is
not open (`names`). Each program is granted the first time it is needed,
and only the granted program's windows are
read or touched (`grants`). `uia` sees a window as numbered lines and acts through UI Automation; `gate`
sorts an action into free or one with an effect outside, which the person
confirms in the chat; `strip` is the border, the strip with Stop and "I'll take
over", the stop keys and the pause when the person uses the window; `hands`
puts them together for one task asked for in chat. Windows only.
"""
